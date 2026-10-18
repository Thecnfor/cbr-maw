import { ChevronDown } from "lucide-react";

import { describeTraceEvent, traceToneClass } from "@/lib/coordination";
import type { TraceEvent } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ActivityItemProps {
  event: TraceEvent;
  variant?: "compact" | "row";
  expanded?: boolean;
  onToggle?: () => void;
}

/**
 * 活动流单行：运行中 RunProgress 与「协同过程」时间线共用。
 * compact 只读；row 可展开原始事件 JSON。
 */
export function ActivityItem({
  event,
  variant = "compact",
  expanded = false,
  onToggle,
}: ActivityItemProps) {
  const info = describeTraceEvent(event);
  const dot = (
    <span
      className={cn("size-1.5 shrink-0 rounded-full", traceToneClass(event.action))}
      aria-hidden="true"
    />
  );

  if (variant === "compact") {
    return (
      <li className="flex items-start gap-2 py-1">
        <span className="mt-1.5">{dot}</span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-caption text-foreground" title={info.title}>
            {info.title}
          </span>
          {info.detail ? (
            <span
              className="block truncate text-tiny text-muted-foreground"
              title={info.detail}
            >
              {info.detail}
            </span>
          ) : null}
        </span>
        <span className="metric-value mt-0.5 shrink-0 text-tiny text-muted-foreground">
          {info.clock}
        </span>
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className={cn(
          "flex w-full items-center gap-2 rounded px-1.5 py-1 text-left transition-colors duration-150 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
          expanded && "bg-accent",
        )}
      >
        <span className="metric-value w-[52px] shrink-0 text-tiny text-muted-foreground">
          {info.clock}
        </span>
        {dot}
        <span className="min-w-0 flex-1">
          <span className="block truncate text-caption text-foreground" title={info.title}>
            {info.title}
          </span>
          {info.detail ? (
            <span className="block truncate text-tiny text-muted-foreground" title={info.detail}>
              {info.detail}
            </span>
          ) : null}
        </span>
        {typeof event.latency_ms === "number" && event.latency_ms > 0 ? (
          <span className="metric-value shrink-0 text-tiny text-muted-foreground">
            {Math.round(event.latency_ms)}ms
          </span>
        ) : null}
        <ChevronDown
          className={cn(
            "size-3.5 shrink-0 text-muted-foreground transition-transform duration-150",
            expanded && "rotate-180",
          )}
          aria-hidden="true"
        />
      </button>
      {expanded ? (
        <pre className="scrollbar-thin terminal mt-1 max-h-52 overflow-auto p-2 font-mono text-caption leading-relaxed">
          {JSON.stringify(event, null, 2)}
        </pre>
      ) : null}
    </li>
  );
}
