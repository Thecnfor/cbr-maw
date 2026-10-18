import { ApiError, isAbortError, type DecisionParams } from "@/lib/api";
import type {
  ChatRequest,
  ChatResponse,
  DecisionCard,
  StageEvent,
  StreamErrorPayload,
  TraceEvent,
} from "@/lib/types";

/**
 * SSE 客户端（fetch + ReadableStream）。
 *
 * 契约见 docs/design/ai-native-interaction-spec.md §1：
 * - GET  /api/decision/stream  事件：run / stage / trace / decision / error
 * - POST /api/chat/stream      事件：run / stage / trace / chat / error
 *
 * 失败分层：
 * - StreamUnavailableError → 端点/代理不支持 SSE，调用方自动回退同步端点；
 * - StreamProtocolError    → 连上了但协议不完整（无最终业务事件 / 超时），不静默回退；
 * - ApiError               → 业务失败（error 事件），直接展示后端中文说明；
 * - AbortError             → 用户取消，不转换为错误。
 */

const DEFAULT_TIMEOUT_MS = 300_000;

export class StreamUnavailableError extends Error {
  constructor(message = "流式接口不可用，已回退同步请求。") {
    super(message);
    this.name = "StreamUnavailableError";
  }
}

export class StreamProtocolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StreamProtocolError";
  }
}

interface LinkedSignal {
  signal: AbortSignal;
  timedOut: () => boolean;
  cleanup: () => void;
}

function linkAbort(external: AbortSignal | undefined, timeoutMs: number): LinkedSignal {
  const controller = new AbortController();
  let timedOut = false;

  const abortFromExternal = () => controller.abort(external?.reason);
  if (external) {
    if (external.aborted) abortFromExternal();
    else external.addEventListener("abort", abortFromExternal, { once: true });
  }

  let timer: ReturnType<typeof setTimeout> | null = null;
  if (timeoutMs > 0) {
    timer = setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException("流式请求超时", "TimeoutError"));
    }, timeoutMs);
  }

  return {
    signal: controller.signal,
    timedOut: () => timedOut,
    cleanup: () => {
      if (timer !== null) clearTimeout(timer);
      external?.removeEventListener("abort", abortFromExternal);
    },
  };
}

async function cancelBody(response: Response): Promise<void> {
  try {
    await response.body?.cancel();
  } catch {
    // 连接已关闭时忽略
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null ? (value as Record<string, unknown>) : null;
}

/* -------------------------------------------------------------------------- */
/* SSE 解析                                                                     */
/* -------------------------------------------------------------------------- */

type SSEMessageHandler = (event: string, payload: unknown) => void;

async function pumpSSE(response: Response, onMessage: SSEMessageHandler): Promise<void> {
  const body = response.body;
  if (!body) throw new StreamUnavailableError("流式响应没有可读取的响应体，已回退同步请求。");

  const reader = body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let eventName = "message";
  let dataLines: string[] = [];
  let sawParsedEvent = false;

  const dispatch = () => {
    if (!dataLines.length) {
      eventName = "message";
      return;
    }
    const data = dataLines.join("\n");
    const event = eventName || "message";
    eventName = "message";
    dataLines = [];

    let payload: unknown = null;
    if (data) {
      try {
        payload = JSON.parse(data) as unknown;
      } catch {
        return; // 单行坏 JSON 不应中断整条流
      }
    }
    sawParsedEvent = true;
    onMessage(event, payload);
  };

  const handleLine = (rawLine: string) => {
    const line = rawLine.endsWith("\r") ? rawLine.slice(0, -1) : rawLine;
    if (!line) {
      dispatch();
      return;
    }
    if (line.startsWith(":")) return; // 心跳注释 `: ping`

    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") eventName = value || "message";
    else if (field === "data") dataLines.push(value);
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index = buffer.indexOf("\n");
      while (index >= 0) {
        handleLine(buffer.slice(0, index));
        buffer = buffer.slice(index + 1);
        index = buffer.indexOf("\n");
      }
    }
    buffer += decoder.decode();
    if (buffer) {
      handleLine(buffer);
      if (dataLines.length) dispatch();
    }
    if (!sawParsedEvent) {
      throw new StreamProtocolError("流式响应为空或未包含可解析事件，请重试。");
    }
  } finally {
    try {
      await reader.cancel();
    } catch {
      // ignore
    }
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }
}

interface RunSSEOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  onMessage: SSEMessageHandler;
}

async function runSSE(url: string, init: RequestInit, options: RunSSEOptions): Promise<void> {
  const linked = linkAbort(options.signal, options.timeoutMs ?? DEFAULT_TIMEOUT_MS);

  const timeoutError = () =>
    new StreamProtocolError("流式请求超时（300 秒），请重试或稍后使用同步接口。");

  try {
    let response: Response;
    try {
      response = await fetch(url, {
        ...init,
        signal: linked.signal,
        cache: "no-store",
        headers: {
          Accept: "text/event-stream",
          ...(init.body ? { "Content-Type": "application/json" } : {}),
          ...init.headers,
        },
      });
    } catch (error) {
      if (linked.timedOut()) throw timeoutError();
      if (isAbortError(error)) throw error;
      throw new StreamUnavailableError("无法连接流式接口，已回退同步请求。");
    }

    if (!response.ok) {
      await cancelBody(response);
      throw new StreamUnavailableError(
        `流式接口返回 HTTP ${response.status}，已回退同步请求。`,
      );
    }

    const contentType = (response.headers.get("content-type") ?? "").toLowerCase();
    if (!contentType.includes("text/event-stream")) {
      await cancelBody(response);
      throw new StreamUnavailableError("流式接口未返回 text/event-stream，已回退同步请求。");
    }

    try {
      await pumpSSE(response, options.onMessage);
    } catch (error) {
      if (linked.timedOut()) throw timeoutError();
      throw error;
    }
  } finally {
    linked.cleanup();
  }
}

/* -------------------------------------------------------------------------- */
/* decision/stream                                                              */
/* -------------------------------------------------------------------------- */

export interface DecisionStreamOptions {
  refresh?: boolean;
  signal?: AbortSignal;
  timeoutMs?: number;
  onRun?: (runId: string) => void;
  onStage?: (stage: StageEvent) => void;
  onTrace?: (event: TraceEvent) => void;
  onDecision?: (decision: DecisionCard) => void;
}

export interface DecisionStreamResult {
  decision: DecisionCard;
  runId: string | null;
  traceEvents: TraceEvent[];
  stages: StageEvent[];
}

function parseStageEvent(payload: Record<string, unknown>): StageEvent | null {
  if (typeof payload.stage !== "string" || !payload.stage) return null;
  return {
    stage: payload.stage,
    label: typeof payload.label === "string" ? payload.label : null,
    role: typeof payload.role === "string" ? payload.role : null,
    status: typeof payload.status === "string" ? payload.status : "started",
    action: typeof payload.action === "string" ? payload.action : null,
    ts: typeof payload.ts === "string" ? payload.ts : null,
  };
}

function parseStreamError(payload: Record<string, unknown>): StreamErrorPayload {
  return {
    status: typeof payload.status === "number" ? payload.status : 0,
    message:
      typeof payload.message === "string" && payload.message
        ? payload.message
        : "流式生成失败，请稍后重试。",
  };
}

/** 驾驶台决策流：收集 trace/stage 供 RunProgress 使用，最终返回 DecisionCard。 */
export async function streamDecision(
  params: DecisionParams,
  options: DecisionStreamOptions = {},
): Promise<DecisionStreamResult> {
  const query = new URLSearchParams();
  if (params.asOf) query.set("as_of", params.asOf);
  if (params.scenario) query.set("scenario", params.scenario);
  query.set("mode", params.mode);
  if (options.refresh) query.set("refresh", "true");

  let decision: DecisionCard | null = null;
  let runId: string | null = null;
  let streamError: StreamErrorPayload | null = null;
  const traceEvents: TraceEvent[] = [];
  const stages: StageEvent[] = [];

  await runSSE(
    `/api/decision/stream?${query.toString()}`,
    { method: "GET" },
    {
      signal: options.signal,
      timeoutMs: options.timeoutMs,
      onMessage: (event, payload) => {
        const record = asRecord(payload);
        if (!record) return;

        if (event === "run") {
          const id = typeof record.run_id === "string" ? record.run_id : null;
          if (id) {
            runId = id;
            options.onRun?.(id);
          }
          return;
        }

        if (event === "stage") {
          const stage = parseStageEvent(record);
          if (!stage) return;
          stages.push(stage);
          options.onStage?.(stage);
          return;
        }

        if (event === "trace") {
          const trace = record as unknown as TraceEvent;
          traceEvents.push(trace);
          options.onTrace?.(trace);
          return;
        }

        if (event === "decision") {
          if (typeof record.run_id !== "string") return;
          decision = record as unknown as DecisionCard;
          options.onDecision?.(decision);
          return;
        }

        if (event === "error") {
          streamError = parseStreamError(record);
        }
      },
    },
  );

  if (streamError) {
    const error = streamError as StreamErrorPayload;
    throw new ApiError(error.status ?? 0, error.message ?? "流式生成失败，请稍后重试。");
  }
  if (!decision) {
    throw new StreamProtocolError("流式响应已结束，但未收到最终决策卡（decision 事件）。");
  }
  return { decision, runId, traceEvents, stages };
}

/* -------------------------------------------------------------------------- */
/* chat/stream                                                                  */
/* -------------------------------------------------------------------------- */

export interface ChatStreamOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
  onRun?: (runId: string) => void;
  onStage?: (stage: StageEvent) => void;
  onTrace?: (event: TraceEvent) => void;
  onChat?: (response: ChatResponse) => void;
}

export interface ChatStreamResult {
  chat: ChatResponse;
  runId: string | null;
  traceEvents: TraceEvent[];
  stages: StageEvent[];
}

/** 对话流：最终业务事件为 `chat`。 */
export async function streamChat(
  body: ChatRequest,
  options: ChatStreamOptions = {},
): Promise<ChatStreamResult> {
  let chat: ChatResponse | null = null;
  let runId: string | null = null;
  let streamError: StreamErrorPayload | null = null;
  const traceEvents: TraceEvent[] = [];
  const stages: StageEvent[] = [];

  await runSSE(
    "/api/chat/stream",
    { method: "POST", body: JSON.stringify(body) },
    {
      signal: options.signal,
      timeoutMs: options.timeoutMs,
      onMessage: (event, payload) => {
        const record = asRecord(payload);
        if (!record) return;

        if (event === "run") {
          const id = typeof record.run_id === "string" ? record.run_id : null;
          if (id) {
            runId = id;
            options.onRun?.(id);
          }
          return;
        }

        if (event === "stage") {
          const stage = parseStageEvent(record);
          if (!stage) return;
          stages.push(stage);
          options.onStage?.(stage);
          return;
        }

        if (event === "trace") {
          const trace = record as unknown as TraceEvent;
          traceEvents.push(trace);
          options.onTrace?.(trace);
          return;
        }

        if (event === "chat") {
          if (typeof record.reply !== "string") return;
          chat = record as unknown as ChatResponse;
          options.onChat?.(chat);
          return;
        }

        if (event === "error") {
          streamError = parseStreamError(record);
        }
      },
    },
  );

  if (streamError) {
    const error = streamError as StreamErrorPayload;
    throw new ApiError(error.status ?? 0, error.message ?? "流式对话失败，请稍后重试。");
  }
  if (!chat) {
    throw new StreamProtocolError("流式响应已结束，但未收到最终对话响应（chat 事件）。");
  }
  return { chat, runId, traceEvents, stages };
}
