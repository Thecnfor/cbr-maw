import type {
  ChatRequest,
  ChatResponse,
  DataCard,
  DecisionCard,
  Evidence,
  ExperimentMode,
  Health,
  Scenario,
  TraceEvent,
} from "@/lib/types";

/** 统一 API 错误：保留 HTTP 状态码，优先展示后端中文 detail。 */
export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

function defaultMessage(status: number): string {
  if (status === 0) return "无法连接后端服务，请确认 FastAPI（127.0.0.1:8000）已启动。";
  if (status === 404) return "未找到请求的资源。";
  if (status === 422) return "请求参数校验失败，请检查日期格式与模式取值。";
  if (status === 503) return "核心服务尚未就绪，请稍后重试。";
  if (status >= 500) return "服务内部错误，请查看服务日志。";
  return `请求失败（HTTP ${status}）。`;
}

function extractDetail(payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const record = payload as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg?: unknown }).msg ?? "");
        }
        return "";
      })
      .filter(Boolean);
    if (parts.length) return parts.join("；");
  }
  if (typeof record.hint === "string") return record.hint;
  return "";
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      signal,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch (error) {
    if (isAbortError(error)) throw error;
    throw new ApiError(0, defaultMessage(0));
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    const detail = extractDetail(payload) || defaultMessage(response.status);
    throw new ApiError(response.status, detail);
  }

  return payload as T;
}

export function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error && error.message) return error.message;
  return "请求失败，请稍后重试。";
}

/* -------------------------------------------------------------------------- */
/* 只读资源                                                                     */
/* -------------------------------------------------------------------------- */

let healthPromise: Promise<Health> | null = null;
let scenariosPromise: Promise<Scenario[]> | null = null;

export function loadHealth(force = false): Promise<Health> {
  if (!force && healthPromise) return healthPromise;
  healthPromise = request<Health>("/api/health").catch((error: unknown) => {
    healthPromise = null;
    throw error;
  });
  return healthPromise;
}

export function loadScenarios(force = false): Promise<Scenario[]> {
  if (!force && scenariosPromise) return scenariosPromise;
  scenariosPromise = request<Scenario[]>("/api/scenarios").catch((error: unknown) => {
    scenariosPromise = null;
    throw error;
  });
  return scenariosPromise;
}

/* -------------------------------------------------------------------------- */
/* 决策卡                                                                       */
/* -------------------------------------------------------------------------- */

export interface DecisionParams {
  asOf: string;
  scenario: string;
  mode: ExperimentMode;
}

export function getDecision(
  params: DecisionParams,
  options: { refresh?: boolean; signal?: AbortSignal } = {},
): Promise<DecisionCard> {
  const query = new URLSearchParams();
  if (params.asOf) query.set("as_of", params.asOf);
  if (params.scenario) query.set("scenario", params.scenario);
  query.set("mode", params.mode);
  if (options.refresh) query.set("refresh", "true");
  return request<DecisionCard>(`/api/decision?${query.toString()}`, {}, options.signal);
}

export function postChat(body: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  return request<ChatResponse>(
    "/api/chat",
    { method: "POST", body: JSON.stringify(body) },
    signal,
  );
}

export async function getEvidence(evidenceId: string, signal?: AbortSignal): Promise<Evidence> {
  return request<Evidence>(`/api/evidence/${encodeURIComponent(evidenceId)}`, {}, signal);
}

export async function getDataCards(signal?: AbortSignal): Promise<DataCard[]> {
  return request<DataCard[]>("/api/data-cards", {}, signal);
}

export async function getTrace(runId: string, signal?: AbortSignal): Promise<TraceEvent[]> {
  return request<TraceEvent[]>(`/api/trace/${encodeURIComponent(runId)}`, {}, signal);
}

/* -------------------------------------------------------------------------- */
/* 只读资源缓存（避免切换页签 / 页面时重复请求，不做轮询）                       */
/* -------------------------------------------------------------------------- */

const traceCache = new Map<string, TraceEvent[]>();
const traceInflight = new Map<string, Promise<TraceEvent[]>>();

/**
 * 把流式运行期间收到的 trace 事件直接写入缓存：
 * 决策完成后「核验与协同过程」可立即渲染，无需再等一次 GET /api/trace/{run_id}。
 */
export function primeTraceCache(runId: string, events: TraceEvent[]): void {
  if (!runId || !events.length) return;
  traceCache.set(runId, events);
}

export function loadTrace(runId: string, force = false): Promise<TraceEvent[]> {
  if (!runId) return Promise.resolve([]);
  if (!force) {
    const cached = traceCache.get(runId);
    if (cached) return Promise.resolve(cached);
    const pending = traceInflight.get(runId);
    if (pending) return pending;
  }
  const promise = getTrace(runId)
    .then((events) => {
      traceCache.set(runId, events);
      return events;
    })
    .finally(() => {
      traceInflight.delete(runId);
    });
  traceInflight.set(runId, promise);
  return promise;
}

let dataCardsPromise: Promise<DataCard[]> | null = null;

export function loadDataCards(force = false): Promise<DataCard[]> {
  if (!force && dataCardsPromise) return dataCardsPromise;
  dataCardsPromise = getDataCards().catch((error: unknown) => {
    dataCardsPromise = null;
    throw error;
  });
  return dataCardsPromise;
}

/** 仅供会话内调试 / 测试使用。 */
export function resetApiCaches(): void {
  healthPromise = null;
  scenariosPromise = null;
  dataCardsPromise = null;
  traceCache.clear();
  traceInflight.clear();
}
