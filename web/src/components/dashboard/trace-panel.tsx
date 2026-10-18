import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ListTree, Rows3 } from "lucide-react";

import { MicroLabel } from "@/components/common/detail-row";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { ActivityItem } from "@/components/dashboard/activity-item";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import { groupTraceEvents } from "@/lib/coordination";
import { summarizeTrace } from "@/lib/decision-utils";
import { fmtDuration, fmtTokens } from "@/lib/format";
import { actionLabel } from "@/lib/labels";
import type { TraceResource } from "@/lib/resources";
import type { TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

function SummaryCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface-2 px-2 py-1.5">
      <div className="text-tiny text-muted-foreground">{label}</div>
      <div className="metric-value text-caption font-medium text-foreground">{value}</div>
    </div>
  );
}

function eventKey(event: TraceEvent, index: number): string {
  return `${event.ts}-${event.step ?? ""}-${index}`;
}

interface TracePanelProps {
  runId: string | null | undefined;
  traceRef?: string | null;
  trace: TraceResource;
}

/**
 * 「协同过程」时间线（P1）：把审计 trace 按 R0–R5 分组，
 * 组头给出事件数 / 工具调用 / 耗时 / tokens，组内复用运行中活动流组件，
 * 点击任一事件可展开完整原始 JSON。
 */
export function TracePanel({ runId, traceRef, trace }: TracePanelProps) {
  const [filterAction, setFilterAction] = useState("all");
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set());
  const [expandedEvent, setExpandedEvent] = useState<string | null>(null);
  const initializedRef = useRef<string | null>(null);

  const summary = summarizeTrace(trace.events);
  const actionCounts = new Map<string, number>();
  for (const event of trace.events) {
    const key = event.action || "other";
    actionCounts.set(key, (actionCounts.get(key) ?? 0) + 1);
  }
  const actionOptions = [...actionCounts.entries()].sort((left, right) => right[1] - left[1]);

  const filtered = useMemo(
    () =>
      filterAction === "all"
        ? trace.events
        : trace.events.filter((event) => (event.action || "other") === filterAction),
    [filterAction, trace.events],
  );
  const groups = useMemo(() => groupTraceEvents(filtered), [filtered]);
  const visibleGroups = groups.filter(
    (group) => group.bucket !== "other" || group.events.length > 0,
  );

  useEffect(() => {
    const key = runId ?? "none";
    if (initializedRef.current === key) return;
    initializedRef.current = key;
    const first = groupTraceEvents(trace.events).find((group) => group.events.length > 0);
    setExpandedGroups(new Set(first ? [first.bucket] : []));
    setExpandedEvent(null);
  }, [runId, trace.events]);

  const toggleGroup = (bucket: string) => {
    setExpandedGroups((previous) => {
      const next = new Set(previous);
      if (next.has(bucket)) next.delete(bucket);
      else next.add(bucket);
      return next;
    });
  };

  return (
    <div className="border-t border-border pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <ListTree className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <MicroLabel>协同过程</MicroLabel>
          <span
            className="metric-value truncate text-tiny text-muted-foreground"
            title={runId ?? undefined}
          >
            {runId || "—"}
          </span>
        </div>
        {trace.events.length ? (
          <Select
            value={filterAction}
            onValueChange={(value) => {
              setFilterAction(value);
              setExpandedEvent(null);
            }}
          >
            <SelectTrigger className="w-[150px]" aria-label="按动作类型过滤协同过程">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部动作（{trace.events.length}）</SelectItem>
              {actionOptions.map(([action, count]) => (
                <SelectItem key={action} value={action}>
                  {actionLabel(action)}（{count}）
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>

      {trace.loading ? (
        <div className="mt-2 space-y-1.5" aria-busy="true" aria-label="协同过程加载中">
          <div className="grid grid-cols-2 gap-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-11" />
            ))}
          </div>
          <Skeleton className="h-[240px] rounded-lg" />
        </div>
      ) : trace.error ? (
        <ErrorState
          className="mt-2"
          title="协同过程读取失败"
          message={errorMessage(trace.error)}
          hint={
            runId
              ? `GET /api/trace/${runId} 未返回事件；轨迹可能在 artifacts/traces/<run_id>.jsonl，或编排层尚未实现 get_trace()。`
              : undefined
          }
          onRetry={trace.reload}
        />
      ) : trace.events.length === 0 ? (
        <EmptyState
          className="mt-2"
          title="本次运行未获取到协同过程"
          description={
            traceRef
              ? `决策卡 trace_ref：${traceRef}。若服务端未暴露轨迹文件，核验结果仍然有效。`
              : "编排层未提供 get_trace()，artifacts/traces/ 下也没有对应文件。"
          }
        />
      ) : (
        <>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <SummaryCell label="事件数" value={String(summary.events)} />
            <SummaryCell label="工具调用" value={String(summary.toolCalls)} />
            <SummaryCell label="累计耗时" value={fmtDuration(summary.latencyMs)} />
            <SummaryCell label="累计 tokens" value={fmtTokens(summary.tokens)} />
          </div>

          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <span className="flex items-center gap-1.5 text-tiny text-muted-foreground">
              <Rows3 className="size-3.5" aria-hidden="true" />
              R0–R5 分组时间线
            </span>
            <span className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() =>
                  setExpandedGroups(new Set(visibleGroups.map((group) => group.bucket)))
                }
                className="text-tiny text-muted-foreground underline-offset-2 transition-colors duration-150 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                展开全部
              </button>
              <span className="text-tiny text-muted-foreground" aria-hidden="true">
                ·
              </span>
              <button
                type="button"
                onClick={() => setExpandedGroups(new Set())}
                className="text-tiny text-muted-foreground underline-offset-2 transition-colors duration-150 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                收起全部
              </button>
            </span>
          </div>

          <ScrollArea className="mt-1.5 h-[340px] rounded-lg border border-border bg-surface-1">
            <ul>
              {visibleGroups.map((group) => {
                const expanded = expandedGroups.has(group.bucket);
                return (
                  <li key={group.bucket} className="border-b border-border last:border-b-0">
                    <button
                      type="button"
                      onClick={() => toggleGroup(group.bucket)}
                      aria-expanded={expanded}
                      className="flex w-full flex-wrap items-center gap-x-2 gap-y-0.5 px-2.5 py-2 text-left transition-colors duration-150 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
                    >
                      <ChevronDown
                        className={cn(
                          "size-3.5 shrink-0 text-muted-foreground transition-transform duration-150",
                          expanded && "rotate-180",
                        )}
                        aria-hidden="true"
                      />
                      <span className="metric-value text-tiny text-muted-foreground">
                        {group.code}
                      </span>
                      <span className="text-caption font-medium text-foreground">
                        {group.title}
                      </span>
                      <span className="text-tiny text-muted-foreground">
                        {group.events.length
                          ? `工具 ${group.toolCalls} · 跨度 ${fmtDuration(group.spanMs)} · ${fmtTokens(group.tokens)} tokens`
                          : "无事件"}
                      </span>
                      <Badge variant="outline" className="ml-auto text-tiny">
                        {group.events.length}
                      </Badge>
                    </button>

                    {expanded ? (
                      <div className="px-1.5 pb-2">
                        {group.events.length ? (
                          <ul className="space-y-0.5">
                            {group.events.map((event, index) => {
                              const key = eventKey(event, index);
                              return (
                                <ActivityItem
                                  key={key}
                                  event={event}
                                  variant="row"
                                  expanded={expandedEvent === key}
                                  onToggle={() =>
                                    setExpandedEvent((current) =>
                                      current === key ? null : key,
                                    )
                                  }
                                />
                              );
                            })}
                          </ul>
                        ) : (
                          <p className="px-1.5 pb-1 text-tiny text-muted-foreground">
                            当前过滤条件下该阶段没有事件。
                          </p>
                        )}
                      </div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </ScrollArea>

          <p className="mt-1.5 text-caption text-muted-foreground">
            点击阶段展开事件；点击事件查看完整原始 JSON（args_hash / result_hash / detail）。
          </p>
        </>
      )}
    </div>
  );
}
