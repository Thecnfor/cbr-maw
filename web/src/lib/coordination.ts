import { fmtClock } from "@/lib/format";
import { actionLabel, roleMeta } from "@/lib/labels";
import type { StageEvent, TraceEvent } from "@/lib/types";

/**
 * 协同阶段 R0–R5 的唯一映射（与 SSE 契约 §1.3 一致）。
 * 运行中活动流、Chat 阶段进度与「协同过程」审计时间线共用这一份定义，
 * 避免三处各写一套阶段名。
 */
export type CoordinationStageCode = "R0" | "R1" | "R2" | "R3" | "R4" | "R5";
export type TraceBucket = CoordinationStageCode | "other";

export interface CoordinationStageMeta {
  code: CoordinationStageCode;
  index: number;
  title: string;
  description: string;
}

export const COORDINATION_STAGES: readonly CoordinationStageMeta[] = [
  {
    code: "R0",
    index: 0,
    title: "主体分析",
    description: "监管 / 投资 / 融资主体独立分析",
  },
  {
    code: "R1",
    index: 1,
    title: "证据共享",
    description: "黑板证据共享与去重",
  },
  {
    code: "R2",
    index: 2,
    title: "交叉验证",
    description: "关键数值与引文交叉核验",
  },
  {
    code: "R3",
    index: 3,
    title: "分歧识别",
    description: "事实 / 方向 / 偏好冲突检测",
  },
  {
    code: "R4",
    index: 4,
    title: "冲突协调",
    description: "协调轮次、权威裁定与 HITL",
  },
  {
    code: "R5",
    index: 5,
    title: "决策汇总",
    description: "决策卡定稿与核验报告",
  },
] as const;

export const STAGE_CODES: readonly CoordinationStageCode[] = COORDINATION_STAGES.map(
  (stage) => stage.code,
);

export function isCoordinationStage(value: string | null | undefined): value is CoordinationStageCode {
  return Boolean(value) && (STAGE_CODES as readonly string[]).includes(String(value));
}

export function stageMeta(code: string | null | undefined): CoordinationStageMeta | null {
  const key = String(code ?? "").toUpperCase();
  return COORDINATION_STAGES.find((stage) => stage.code === key) ?? null;
}

const ACTION_BUCKET: Record<string, TraceBucket> = {
  run_start: "R0",
  analysis_start: "R0",
  analysis_done: "R0",
  signal: "R0",
  tool_call: "R0",
  llm_call: "R0",
  kb_search: "R0",
  claim: "R0",
  evidence_share: "R1",
  evidence_share_summary: "R1",
  evidence_dedup: "R1",
  cross_check: "R2",
  cross_check_summary: "R2",
  cross_validate: "R2",
  verify: "R2",
  conflict_detection: "R3",
  conflict: "R3",
  conflict_resolution: "R4",
  conflict_resolved: "R4",
  coordination_round: "R4",
  hitl: "R4",
  finalize: "R5",
};

export function traceBucket(action: string | null | undefined): TraceBucket {
  return ACTION_BUCKET[String(action ?? "")] ?? "other";
}

export function traceBucketMeta(bucket: TraceBucket): {
  code: string;
  title: string;
  description: string;
} {
  if (bucket === "other") {
    return {
      code: "其他",
      title: "其他事件",
      description: "异常、预算或未归类的审计事件",
    };
  }
  const meta = stageMeta(bucket);
  return meta
    ? { code: meta.code, title: meta.title, description: meta.description }
    : { code: bucket, title: bucket, description: "" };
}

function toFinite(value: unknown): number {
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : 0;
}

export interface TraceTimelineGroup {
  bucket: TraceBucket;
  code: string;
  title: string;
  description: string;
  events: TraceEvent[];
  /** 组内首末事件的时间跨度（真实墙钟），不是逐事件耗时相加。 */
  spanMs: number;
  latencyMs: number;
  tokens: number;
  toolCalls: number;
}

/** 把 trace 按 R0–R5 分组（保留空分组，便于一眼看到完整协同过程）。 */
export function groupTraceEvents(events: TraceEvent[]): TraceTimelineGroup[] {
  const buckets = new Map<TraceBucket, TraceEvent[]>();
  for (const code of STAGE_CODES) buckets.set(code, []);
  buckets.set("other", []);

  for (const event of events) {
    const bucket = traceBucket(event.action);
    const list = buckets.get(bucket);
    if (list) list.push(event);
  }

  const ordered: TraceBucket[] = [...STAGE_CODES, "other"];
  return ordered.map((bucket) => {
    const list = buckets.get(bucket) ?? [];
    const meta = traceBucketMeta(bucket);
    const timestamps = list
      .map((event) => parseTimestamp(event.ts))
      .filter((value): value is number => value !== null);
    const spanMs =
      timestamps.length > 1 ? Math.max(...timestamps) - Math.min(...timestamps) : 0;
    return {
      bucket,
      code: meta.code,
      title: meta.title,
      description: meta.description,
      events: list,
      spanMs,
      latencyMs: list.reduce((sum, event) => sum + toFinite(event.latency_ms), 0),
      tokens: list.reduce((sum, event) => sum + toFinite(event.tokens), 0),
      toolCalls: list.filter((event) => event.action === "tool_call").length,
    };
  });
}

/* -------------------------------------------------------------------------- */
/* 运行中时间线（来自 stage 事件）                                               */
/* -------------------------------------------------------------------------- */

export type StageProgressStatus = "pending" | "active" | "done";

export interface StageTimelineNode extends CoordinationStageMeta {
  status: StageProgressStatus;
  label: string | null;
  role: string | null;
  startedAt: number | null;
  finishedAt: number | null;
}

function parseTimestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * 由 `stage` 事件构造 R0–R5 时间线。
 * 采用「后一阶段开始 → 前一阶段自动完成」的收敛规则，避免后端只发 started 时卡住。
 */
export function buildStageTimeline(stageEvents: StageEvent[]): StageTimelineNode[] {
  const nodes: StageTimelineNode[] = COORDINATION_STAGES.map((stage) => ({
    ...stage,
    status: "pending" as StageProgressStatus,
    label: null,
    role: null,
    startedAt: null,
    finishedAt: null,
  }));

  for (const event of stageEvents) {
    const meta = stageMeta(event.stage);
    if (!meta) continue;
    const index = meta.index;
    const node = nodes[index];
    if (!node) continue;

    for (let previous = 0; previous < index; previous += 1) {
      const earlier = nodes[previous];
      if (earlier && earlier.status !== "done") earlier.status = "done";
    }

    const ts = parseTimestamp(event.ts);
    const status = String(event.status ?? "started");
    if (status === "finished") {
      node.status = "done";
      if (ts !== null) node.finishedAt = ts;
    } else {
      node.status = "active";
      if (ts !== null && node.startedAt === null) node.startedAt = ts;
    }
    if (event.label) node.label = event.label;
    if (event.role) node.role = event.role;
  }

  return nodes;
}

export interface RoleStageState {
  role: string;
  label: string;
  focus: string;
  status: StageProgressStatus;
  stage: string | null;
}

export const PRIMARY_ROLES = ["regulator", "investor", "financing"] as const;

/** 三个主体 chip：监管 / 投资 / 融资。 */
export function buildRoleStates(stageEvents: StageEvent[]): RoleStageState[] {
  const states = new Map<string, RoleStageState>();
  for (const role of PRIMARY_ROLES) {
    const meta = roleMeta(role);
    states.set(role, {
      role,
      label: meta.label,
      focus: meta.focus,
      status: "pending",
      stage: null,
    });
  }

  for (const event of stageEvents) {
    const role = String(event.role ?? "");
    const state = states.get(role);
    if (!state) continue;
    const status = String(event.status ?? "started");
    state.status = status === "finished" ? "done" : "active";
    state.stage = event.stage ?? state.stage;
  }

  return [...states.values()];
}

/* -------------------------------------------------------------------------- */
/* 活动流描述                                                                   */
/* -------------------------------------------------------------------------- */

export interface ActivityDescription {
  title: string;
  detail: string;
  clock: string;
}

export function describeTraceEvent(event: TraceEvent): ActivityDescription {
  const role = roleMeta(event.role).label;
  const action = actionLabel(event.action);
  const title = event.role ? `${role} · ${action}` : action;

  const parts: string[] = [];
  if (event.tool) parts.push(event.tool);
  if (typeof event.latency_ms === "number" && event.latency_ms > 0) {
    parts.push(`${Math.round(event.latency_ms)}ms`);
  }
  if (typeof event.tokens === "number" && event.tokens > 0) {
    parts.push(`${event.tokens} tokens`);
  }
  if (!parts.length && event.step) parts.push(`步骤 ${event.step}`);
  if (!parts.length && event.detail) {
    const message = event.detail.message ?? event.detail.summary ?? event.detail.reason;
    if (typeof message === "string" && message.trim()) parts.push(message.trim());
  }

  return {
    title,
    detail: parts.join(" · "),
    clock: fmtClock(event.ts),
  };
}

/** 事件类型的状态点颜色（只用语义色 / 中性色）。 */
export function traceToneClass(action: string | null | undefined): string {
  if (action === "verify" || action === "finalize" || action === "analysis_done") {
    return "bg-success";
  }
  if (action === "conflict" || action === "conflict_detection" || action === "hitl") {
    return "bg-warning";
  }
  if (action === "agent_error" || action === "budget_exceeded") {
    return "bg-destructive";
  }
  return "bg-muted-foreground/50";
}
