import { Activity, Check, Loader2, Square, Timer, Wifi, WifiOff } from "lucide-react";

import { MicroLabel } from "@/components/common/detail-row";
import { ActivityItem } from "@/components/dashboard/activity-item";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { StatusDot } from "@/components/ui/status-dot";
import {
  buildRoleStates,
  buildStageTimeline,
  COORDINATION_STAGES,
  type StageProgressStatus,
} from "@/lib/coordination";
import { truncateMiddle } from "@/lib/format";
import { roleMeta } from "@/lib/labels";
import { fmtElapsed, useElapsedSeconds } from "@/lib/motion";
import type { StageEvent, TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

interface RunProgressProps {
  startedAt: number | null;
  active: boolean;
  runId: string | null;
  stageEvents: StageEvent[];
  activities: TraceEvent[];
  usedFallback: boolean;
  onCancel: () => void;
}

function stageStatusLabel(status: StageProgressStatus): string {
  if (status === "done") return "完成";
  if (status === "active") return "进行中";
  return "等待";
}

function roleStatusLabel(status: StageProgressStatus): string {
  if (status === "done") return "已完成";
  if (status === "active") return "分析中";
  return "等待";
}

/**
 * 运行中面板：R0–R5 阶段时间线 + 三主体状态 + 最近活动 + 已用时 + 取消。
 *
 * 真实 SSE 时完全由 `stage` / `trace` 事件驱动；
 * 回退同步端点时没有事件可消费，会显式标注「同步回退 · 本地估算」，
 * 不把本地计时伪装成后端事件。
 */
export function RunProgress({
  startedAt,
  active,
  runId,
  stageEvents,
  activities,
  usedFallback,
  onCancel,
}: RunProgressProps) {
  const elapsed = useElapsedSeconds(startedAt, active);
  const hasEvents = stageEvents.length > 0;
  const fallbackMode = usedFallback && !hasEvents;
  const baseTimeline = buildStageTimeline(stageEvents);

  const estimatedIndex = Math.min(
    COORDINATION_STAGES.length - 1,
    Math.floor(elapsed / 4),
  );

  const nodes = baseTimeline.map((node, index) => {
    if (fallbackMode) {
      const status: StageProgressStatus =
        index < estimatedIndex ? "done" : index === estimatedIndex ? "active" : "pending";
      return {
        ...node,
        status,
        label:
          status === "active"
            ? "同步回退 · 阶段为本地估算"
            : node.label ?? node.description,
      };
    }
    if (!hasEvents) {
      return {
        ...node,
        status: index === 0 ? ("active" as const) : ("pending" as const),
      };
    }
    return node;
  });

  const roleStates = buildRoleStates(stageEvents).map((role) =>
    fallbackMode && role.status === "pending"
      ? { ...role, status: "active" as const }
      : role,
  );

  const doneCount = nodes.filter((node) => node.status === "done").length;
  const liveEvent = stageEvents.length ? stageEvents[stageEvents.length - 1] : null;
  const liveText = fallbackMode
    ? "已回退同步请求，等待最终结果"
    : liveEvent
      ? `${liveEvent.stage} ${liveEvent.label ?? ""}`.trim()
      : "协同运行已开始";

  return (
    <Card
      asChild
      className="overflow-hidden animate-fade"
    >
      <section aria-label="协同运行进度" aria-busy={active}>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-3">
          <Loader2 className="size-4 shrink-0 animate-spin text-muted-foreground" aria-hidden="true" />
          <h2 className="text-desc font-semibold tracking-tight text-foreground">协同运行中</h2>
          <Badge variant={usedFallback ? "warning" : "outline"} className="text-tiny">
            {usedFallback ? "同步回退" : "SSE 流式"}
          </Badge>
          {runId ? (
            <Badge variant="outline" className="max-w-[220px] font-mono text-tiny" title={runId}>
              <span className="truncate">{truncateMiddle(runId, 18, 8)}</span>
            </Badge>
          ) : null}
          <span className="ml-auto flex items-center gap-1.5 text-caption text-muted-foreground">
            <Timer className="size-3.5" aria-hidden="true" />
            已用时
            <span className="metric-value text-foreground">{fmtElapsed(elapsed)}</span>
          </span>
          <Button variant="outline" size="sm" onClick={onCancel} disabled={!active}>
            <Square aria-hidden="true" />
            取消运行
          </Button>
        </div>

        <span className="sr-only" aria-live="polite" aria-atomic="true">
          {liveText}
        </span>

        <div className="grid gap-4 p-4 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
          <div className="min-w-0">
            <div className="flex items-center justify-between gap-2">
              <MicroLabel>阶段时间线 R0–R5</MicroLabel>
              <span className="metric-value text-tiny text-muted-foreground">
                {doneCount}/{COORDINATION_STAGES.length}
              </span>
            </div>
            <ol className="mt-2">
              {nodes.map((node, index) => {
                const isLast = index === nodes.length - 1;
                return (
                  <li key={node.code} className="relative flex gap-2.5 pb-2.5 last:pb-0">
                    {!isLast ? (
                      <span
                        className="absolute left-[6px] top-4 h-[calc(100%-8px)] w-px bg-border"
                        aria-hidden="true"
                      />
                    ) : null}
                    <span
                      className={cn(
                        "relative z-10 mt-0.5 grid size-3.5 shrink-0 place-items-center rounded-full border",
                        node.status === "done"
                          ? "border-success bg-success"
                          : node.status === "active"
                            ? "border-foreground bg-surface-1"
                            : "border-border bg-surface-1",
                      )}
                      aria-hidden="true"
                    >
                      {node.status === "done" ? (
                        <Check className="size-2.5 text-primary-foreground" />
                      ) : node.status === "active" ? (
                        <Loader2 className="size-2.5 animate-spin text-foreground" />
                      ) : (
                        <span className="size-1 rounded-full bg-muted-foreground/40" />
                      )}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                        <span className="metric-value text-tiny text-muted-foreground">
                          {node.code}
                        </span>
                        <span
                          className={cn(
                            "text-caption font-medium",
                            node.status === "pending"
                              ? "text-muted-foreground"
                              : "text-foreground",
                          )}
                        >
                          {node.title}
                        </span>
                        <span className="text-tiny text-muted-foreground">
                          {stageStatusLabel(node.status)}
                        </span>
                        {node.role ? (
                          <span className="text-tiny text-muted-foreground">
                            {roleMeta(node.role).label}
                          </span>
                        ) : null}
                      </div>
                      <p className="truncate text-tiny text-muted-foreground" title={node.label ?? undefined}>
                        {node.label || node.description}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </div>

          <div className="min-w-0 space-y-3">
            <div>
              <MicroLabel>主体状态（监管 / 投资 / 融资）</MicroLabel>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {roleStates.map((role) => (
                  <span
                    key={role.role}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-caption",
                      role.status === "done"
                        ? "border-success/30 bg-success/10 text-foreground"
                        : role.status === "active"
                          ? "border-warning/40 bg-warning/10 text-foreground"
                          : "border-border text-muted-foreground",
                    )}
                    title={role.focus}
                  >
                    <StatusDot
                      status={
                        role.status === "done"
                          ? "success"
                          : role.status === "active"
                            ? "warning"
                            : "idle"
                      }
                      size="sm"
                      pulse={role.status === "active"}
                    />
                    <span className="font-medium">{role.label}</span>
                    <span className="text-tiny text-muted-foreground">
                      {roleStatusLabel(role.status)}
                    </span>
                  </span>
                ))}
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between gap-2">
                <MicroLabel>最近活动</MicroLabel>
                {hasEvents ? (
                  <span className="metric-value text-tiny text-muted-foreground">
                    {activities.length > 6 ? `最近 6 / 共 ${activities.length}` : `${activities.length} 条`}
                  </span>
                ) : null}
              </div>
              {hasEvents ? (
                <ul className="mt-1 divide-y divide-border rounded-lg border border-border bg-surface-2 px-2.5">
                  {activities.slice(-6).map((event, index) => (
                    <ActivityItem
                      key={`${event.ts}-${event.step ?? ""}-${index}`}
                      event={event}
                    />
                  ))}
                </ul>
              ) : (
                <div className="mt-1 rounded-lg border border-border bg-surface-2 px-2.5 py-2">
                  <p className="text-caption leading-relaxed text-muted-foreground">
                    {fallbackMode
                      ? "同步请求进行中：后端尚未提供 stage / trace 流式事件，完成后一次性返回决策卡与 trace。"
                      : "正在等待流式事件（run / stage / trace）…"}
                  </p>
                  <div className="mt-1.5 space-y-1" aria-hidden="true">
                    <div className="skeleton h-2.5 w-full" />
                    <div className="skeleton h-2.5 w-4/5" />
                    <div className="skeleton h-2.5 w-3/5" />
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-border px-4 py-2 text-caption text-muted-foreground">
          {usedFallback ? (
            <WifiOff className="size-3.5 shrink-0 text-warning-ink" aria-hidden="true" />
          ) : (
            <Wifi className="size-3.5 shrink-0 text-info-ink" aria-hidden="true" />
          )}
          <span>
            {usedFallback
              ? "同步回退：阶段推进为本地估算，不代表后端真实事件；结果仍来自同一次协同运行。"
              : "事件来自 /api/decision/stream 的 stage / trace；阶段与活动为真实运行轨迹。"}
            <span className="hidden md:inline">
              {" "}
              真实 LLM 约 12–24s；30 分钟缓存命中 &lt;50ms。
            </span>
          </span>
          <span className="ml-auto flex items-center gap-1.5">
            <Activity className="size-3.5" aria-hidden="true" />
            可随时取消；取消后保留上一次结果。
          </span>
        </div>
      </section>
    </Card>
  );
}
