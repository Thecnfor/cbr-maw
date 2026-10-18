import { Check, Loader2, Sparkles, Square } from "lucide-react";

import { ActivityItem } from "@/components/dashboard/activity-item";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  buildStageTimeline,
  COORDINATION_STAGES,
  type StageProgressStatus,
} from "@/lib/coordination";
import { fmtElapsed, useElapsedSeconds } from "@/lib/motion";
import type { StageEvent, TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatRunProgressProps {
  startedAt: number | null;
  active: boolean;
  stageEvents: StageEvent[];
  activities: TraceEvent[];
  usedFallback: boolean;
  onStop: () => void;
}

/**
 * 对话发送后的「协同分析中」阶段进度。
 * 阶段来自 SSE `stage` 事件；回退同步端点时明确标注本地估算，不伪造事件。
 */
export function ChatRunProgress({
  startedAt,
  active,
  stageEvents,
  activities,
  usedFallback,
  onStop,
}: ChatRunProgressProps) {
  const elapsed = useElapsedSeconds(startedAt, active);
  const hasEvents = stageEvents.length > 0;
  const fallbackMode = usedFallback && !hasEvents;
  const estimatedIndex = Math.min(
    COORDINATION_STAGES.length - 1,
    Math.floor(elapsed / 4),
  );

  const nodes = buildStageTimeline(stageEvents).map((node, index) => {
    if (fallbackMode) {
      const status: StageProgressStatus =
        index < estimatedIndex ? "done" : index === estimatedIndex ? "active" : "pending";
      return { ...node, status };
    }
    if (!hasEvents) {
      return { ...node, status: index === 0 ? ("active" as const) : ("pending" as const) };
    }
    return node;
  });

  const liveEvent = stageEvents.length ? stageEvents[stageEvents.length - 1] : null;
  const liveText = fallbackMode
    ? "已回退同步对话请求，等待最终回复"
    : liveEvent
      ? `${liveEvent.stage} ${liveEvent.label ?? ""}`.trim()
      : "协同分析已开始";
  const latestActivity = activities.length ? activities[activities.length - 1] : null;

  return (
    <div className="flex gap-2.5">
      <span
        className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface-1 text-foreground"
        aria-hidden="true"
      >
        <Sparkles className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1" role="region" aria-label="协同分析进度" aria-busy={active}>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption text-muted-foreground">
          <span className="font-medium text-foreground">协同助手</span>
          <span aria-hidden="true">·</span>
          <span>协同分析中</span>
          <Badge variant={usedFallback ? "warning" : "outline"} className="text-tiny">
            {usedFallback ? "同步回退" : "SSE 流式"}
          </Badge>
          <span className="metric-value ml-auto text-foreground">{fmtElapsed(elapsed)}</span>
        </div>

        <span className="sr-only" aria-live="polite" aria-atomic="true">
          {liveText}
        </span>

        <div className="mt-1 rounded-xl border border-border bg-surface-1 px-3.5 py-3">
          <div className="flex flex-wrap gap-1.5">
            {nodes.map((node) => (
              <span
                key={node.code}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-tiny",
                  node.status === "active"
                    ? "border-foreground/30 bg-surface-2 text-foreground"
                    : node.status === "done"
                      ? "border-border text-muted-foreground"
                      : "border-border/60 text-muted-foreground/60",
                )}
                title={node.label ?? node.description}
              >
                {node.status === "active" ? (
                  <Loader2 className="size-2.5 animate-spin" aria-hidden="true" />
                ) : node.status === "done" ? (
                  <Check className="size-2.5 text-success-ink" aria-hidden="true" />
                ) : null}
                <span className="metric-value">{node.code}</span>
                <span>{node.title}</span>
              </span>
            ))}
          </div>

          {latestActivity ? (
            <ul className="mt-1.5 border-t border-border pt-1.5">
              <ActivityItem event={latestActivity} />
            </ul>
          ) : null}

          <p className="mt-2 border-t border-border pt-2 text-caption leading-relaxed text-muted-foreground">
            {fallbackMode
              ? "后端未提供 /api/chat/stream 事件，已回退同步 /api/chat；阶段推进为本地估算，回复到达后一次性呈现。"
              : "阶段来自 SSE stage 事件；回复生成后将以打字机/淡入呈现（reduced-motion 直接显示）。"}
          </p>

          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-tiny text-muted-foreground">
              真实 LLM 约 12–24 秒；不会轮询，也不伪造中间结论。
            </span>
            <Button variant="outline" size="sm" onClick={onStop} disabled={!active}>
              <Square aria-hidden="true" />
              停止生成
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
