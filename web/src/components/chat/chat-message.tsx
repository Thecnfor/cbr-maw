import { useState } from "react";
import { BookOpen, ChevronDown, Sparkles } from "lucide-react";

import { DecisionSummary } from "@/components/chat/decision-summary";
import { fmtClock, truncateMiddle } from "@/lib/format";
import { RichText } from "@/lib/markdown";
import type { ChatTurn, SourceRef } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatMessageProps {
  turn: ChatTurn;
  onOpenCitation: (citation: SourceRef) => void;
}

export function ChatMessage({ turn, onOpenCitation }: ChatMessageProps) {
  const [expanded, setExpanded] = useState(false);

  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] min-w-0">
          <div className="whitespace-pre-wrap rounded-xl border border-border bg-surface-2 px-3.5 py-2.5 text-body leading-relaxed text-foreground">
            {turn.content}
          </div>
          <div className="mt-1 text-right text-tiny text-muted-foreground">
            你 · {fmtClock(turn.createdAt)}
          </div>
        </div>
      </div>
    );
  }

  const isError = turn.status === "error";
  const isStopped = turn.status === "stopped";
  const citations = turn.citations ?? [];
  const collapsible = turn.status === "ok" && turn.content.length > 900;

  return (
    <div className="flex gap-2.5">
      <span
        className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface-1 text-foreground"
        aria-hidden="true"
      >
        <Sparkles className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-caption text-muted-foreground">
          <span className="font-medium text-foreground">协同助手</span>
          <span aria-hidden="true">·</span>
          <span>{fmtClock(turn.createdAt)}</span>
          {turn.traceId ? (
            <span
              className="hidden max-w-[220px] truncate font-mono sm:inline"
              title={turn.traceId}
            >
              trace {truncateMiddle(turn.traceId, 12, 6)}
            </span>
          ) : null}
          {isStopped ? <span className="text-warning-ink">已停止</span> : null}
        </div>

        <div
          className={cn(
            "mt-1 rounded-xl border px-3.5 py-3",
            isError
              ? "border-destructive/30 bg-destructive/10"
              : isStopped
                ? "border-border bg-surface-2"
                : "border-border bg-surface-1",
          )}
        >
          <div
            className={cn(
              collapsible && !expanded && "max-h-80 overflow-hidden",
            )}
          >
            {turn.status === "ok" ? (
              <RichText text={turn.content} />
            ) : (
              <p className="whitespace-pre-wrap text-body leading-relaxed text-foreground">
                {turn.content}
              </p>
            )}
          </div>

          {collapsible ? (
            <div className="mt-1.5 border-t border-border pt-1.5">
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                aria-expanded={expanded}
                className="inline-flex items-center gap-1 text-caption text-muted-foreground transition-colors duration-150 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <ChevronDown
                  className={cn(
                    "size-3.5 transition-transform duration-150",
                    expanded && "rotate-180",
                  )}
                  aria-hidden="true"
                />
                {expanded
                  ? "收起全文"
                  : `展开全文（约 ${Math.round(turn.content.length / 100) * 100} 字）`}
              </button>
            </div>
          ) : null}

          {isError ? (
            <p className="mt-1.5 border-t border-destructive/20 pt-1.5 text-caption leading-relaxed text-muted-foreground">
              可稍后重试；若持续失败，请到驾驶台确认 /api/health 的核心模块状态与 503
              中文说明。
            </p>
          ) : null}

          {citations.length ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-border pt-2">
              <span className="inline-flex items-center gap-1 text-tiny text-muted-foreground">
                <BookOpen className="size-3" aria-hidden="true" />
                引用 {citations.length}
              </span>
              {citations.map((citation, index) => (
                <button
                  key={`${citation.doc_id ?? citation.name}-${index}`}
                  type="button"
                  onClick={() => onOpenCitation(citation)}
                  title={[citation.doc_id, citation.chunk_id].filter(Boolean).join(" / ")}
                  className="inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-surface-1 px-2 py-0.5 text-tiny text-muted-foreground transition-colors duration-150 hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="metric-value text-foreground/70">[{index + 1}]</span>
                  <span className="max-w-[220px] truncate">
                    {citation.name || citation.doc_id || "来源"}
                  </span>
                </button>
              ))}
            </div>
          ) : null}

          {turn.decision ? <DecisionSummary decision={turn.decision} /> : null}
        </div>
      </div>
    </div>
  );
}
