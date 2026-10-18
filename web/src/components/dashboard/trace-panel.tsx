import { useState } from "react";
import { ListTree } from "lucide-react";

import { DetailRow, MicroLabel } from "@/components/common/detail-row";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { errorMessage } from "@/lib/api";
import { summarizeTrace } from "@/lib/decision-utils";
import { fmtClock, fmtDuration, fmtTokens } from "@/lib/format";
import { actionLabel, roleMeta } from "@/lib/labels";
import type { TraceResource } from "@/lib/resources";
import type { TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

function roleShort(role: string | null | undefined): string {
  return roleMeta(role).label.replace("主体", "").replace("者", "");
}

function actionDotClass(action: string | undefined): string {
  if (action === "verify" || action === "finalize") return "bg-success";
  if (action === "conflict" || action === "hitl") return "bg-warning";
  if (action === "agent_error" || action === "budget_exceeded") return "bg-destructive";
  return "bg-terminal-muted";
}

function SummaryCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface-2 px-2 py-1.5">
      <div className="text-tiny text-muted-foreground">{label}</div>
      <div className="metric-value text-caption font-medium text-foreground">{value}</div>
    </div>
  );
}

interface TracePanelProps {
  runId: string | null | undefined;
  traceRef?: string | null;
  trace: TraceResource;
}

export function TracePanel({ runId, traceRef, trace }: TracePanelProps) {
  const [filterAction, setFilterAction] = useState("all");
  const [selected, setSelected] = useState<TraceEvent | null>(null);

  const summary = summarizeTrace(trace.events);
  const actionCounts = new Map<string, number>();
  for (const event of trace.events) {
    const key = event.action || "other";
    actionCounts.set(key, (actionCounts.get(key) ?? 0) + 1);
  }
  const actionOptions = [...actionCounts.entries()].sort((left, right) => right[1] - left[1]);
  const filtered =
    filterAction === "all"
      ? trace.events
      : trace.events.filter((event) => (event.action || "other") === filterAction);

  return (
    <div className="border-t border-border pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          <ListTree className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <MicroLabel>审计轨迹 trace</MicroLabel>
          <span className="metric-value truncate text-tiny text-muted-foreground" title={runId ?? undefined}>
            {runId || "—"}
          </span>
        </div>
        {trace.events.length ? (
          <Select
            value={filterAction}
            onValueChange={(value) => {
              setFilterAction(value);
              setSelected(null);
            }}
          >
            <SelectTrigger className="w-[132px]" aria-label="按动作类型过滤审计轨迹">
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
        <div className="mt-2 space-y-1.5" aria-busy="true" aria-label="审计轨迹加载中">
          <div className="grid grid-cols-2 gap-2">
            {Array.from({ length: 4 }).map((_, index) => (
              <Skeleton key={index} className="h-11" />
            ))}
          </div>
          <Skeleton className="h-[220px] rounded-lg" />
        </div>
      ) : trace.error ? (
        <ErrorState
          className="mt-2"
          title="审计轨迹读取失败"
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
          title="本次运行未获取到审计轨迹"
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

          <ScrollArea className="terminal mt-2 h-[300px]">
            <div className="p-2">
              <ul className="space-y-0.5">
                {filtered.map((event, index) => {
                  const key = `${event.ts}-${event.step ?? ""}-${index}`;
                  const active = selected === event;
                  return (
                    <li key={key}>
                      <button
                        type="button"
                        onClick={() => setSelected(active ? null : event)}
                        aria-pressed={active}
                        className={cn(
                          "flex w-full items-center gap-2 rounded px-1.5 py-0.5 text-left font-mono text-caption transition-colors duration-150 hover:bg-terminal-fg/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-terminal-fg/60",
                          active && "bg-terminal-fg/10",
                        )}
                      >
                        <span className="terminal-muted w-[52px] shrink-0">
                          {fmtClock(event.ts)}
                        </span>
                        <span className="terminal-muted w-[26px] shrink-0 truncate">
                          {event.step || "—"}
                        </span>
                        <span className="terminal-muted w-[26px] shrink-0 truncate">
                          {roleShort(event.role)}
                        </span>
                        <span className="flex w-[78px] shrink-0 items-center gap-1.5 truncate text-terminal-fg/85">
                          <span
                            className={cn("size-1.5 shrink-0 rounded-full", actionDotClass(event.action))}
                            aria-hidden="true"
                          />
                          <span className="truncate">{actionLabel(event.action)}</span>
                        </span>
                        <span className="terminal-muted min-w-0 flex-1 truncate">
                          {event.tool || ""}
                        </span>
                        <span className="terminal-muted shrink-0 text-right">
                          {event.latency_ms ? `${event.latency_ms}ms` : ""}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
              {filtered.length === 0 ? (
                <p className="terminal-muted p-2 text-caption">当前动作过滤下没有事件。</p>
              ) : null}
            </div>
          </ScrollArea>

          {selected ? (
            <div className="mt-2 rounded-lg border border-border bg-surface-2 p-2.5">
              <div className="flex items-center justify-between gap-2">
                <MicroLabel>事件详情</MicroLabel>
                <button
                  type="button"
                  onClick={() => setSelected(null)}
                  className="text-caption text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  关闭
                </button>
              </div>
              <dl className="mt-1">
                <DetailRow label="动作" mono>
                  {actionLabel(selected.action)}
                </DetailRow>
                <DetailRow label="步骤 / 角色" mono>
                  {selected.step || "—"} · {roleMeta(selected.role).label}
                </DetailRow>
                <DetailRow label="工具" mono>
                  {selected.tool || "—"}
                </DetailRow>
                <DetailRow label="args_hash" mono>
                  {selected.args_hash || "—"}
                </DetailRow>
                <DetailRow label="result_hash" mono>
                  {selected.result_hash || "—"}
                </DetailRow>
                <DetailRow label="耗时 / tokens" mono>
                  {selected.latency_ms ?? 0} ms · {selected.tokens ?? 0}
                </DetailRow>
              </dl>
              {selected.detail && Object.keys(selected.detail).length ? (
                <pre className="scrollbar-thin terminal mt-1.5 max-h-48 overflow-auto p-2 font-mono text-caption leading-relaxed">
                  {JSON.stringify(selected.detail, null, 2)}
                </pre>
              ) : null}
            </div>
          ) : (
            <p className="mt-1.5 text-caption text-muted-foreground">
              点击任一日志行查看 args_hash / result_hash / detail。
            </p>
          )}
        </>
      )}
    </div>
  );
}
