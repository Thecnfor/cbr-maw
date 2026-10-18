import { useEffect, useState } from "react";
import { BookOpen, ChevronDown, Copy, Quote, RotateCcw, Sparkles } from "lucide-react";

import { DecisionSummary } from "@/components/chat/decision-summary";
import { IconButton } from "@/components/common/icon-button";
import { copyText } from "@/lib/clipboard";
import { fmtClock, truncateMiddle } from "@/lib/format";
import { RichText } from "@/lib/markdown";
import { usePrefersReducedMotion } from "@/lib/motion";
import type { FollowUp } from "@/lib/suggestions";
import { useToast } from "@/lib/toast";
import type { ChatTurn, SourceRef } from "@/lib/types";
import { cn } from "@/lib/utils";

interface ChatMessageProps {
  turn: ChatTurn;
  isLast?: boolean;
  animate?: boolean;
  suggestions?: FollowUp[];
  onOpenCitation: (citation: SourceRef) => void;
  onRetry?: () => void;
  onSuggestion?: (prompt: string) => void;
}

export function ChatMessage({
  turn,
  isLast = false,
  animate = false,
  suggestions = [],
  onOpenCitation,
  onRetry,
  onSuggestion,
}: ChatMessageProps) {
  const [expanded, setExpanded] = useState(false);
  const reduced = usePrefersReducedMotion();
  const { toast } = useToast();
  const [revealed, setRevealed] = useState(() =>
    turn.role === "assistant" && turn.status === "ok" && animate && !reduced
      ? 0
      : turn.content.length,
  );

  useEffect(() => {
    if (turn.role !== "assistant" || turn.status !== "ok" || !animate || reduced) {
      setRevealed(turn.content.length);
      return;
    }
    const total = turn.content.length;
    if (!total) {
      setRevealed(0);
      return;
    }
    setRevealed(0);
    const steps = Math.min(64, Math.max(24, Math.ceil(total / 22)));
    const interval = Math.max(12, Math.round(1000 / steps));
    let step = 0;
    const timer = window.setInterval(() => {
      step += 1;
      setRevealed(Math.min(total, Math.ceil((total * step) / steps)));
      if (step >= steps) window.clearInterval(timer);
    }, interval);
    return () => window.clearInterval(timer);
  }, [animate, reduced, turn.content, turn.role, turn.status]);

  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] min-w-0">
          <div className="whitespace-pre-wrap rounded-xl border border-border bg-surface-2 px-3.5 py-2.5 text-body leading-relaxed text-foreground">
            {turn.content}
          </div>
          <div className="mt-1 text-right text-tiny text-muted-foreground">
            你 · {fmtClock(turn.createdAt)}
            {turn.asOf ? ` · as_of ${turn.asOf}` : ""}
          </div>
        </div>
      </div>
    );
  }

  const isError = turn.status === "error";
  const isStopped = turn.status === "stopped";
  const citations = turn.citations ?? [];
  const typing =
    turn.status === "ok" && animate && !reduced && revealed < turn.content.length;
  const collapsible = turn.status === "ok" && !typing && turn.content.length > 900;
  const visibleContent = typing ? turn.content.slice(0, revealed) : turn.content;

  const copyReply = async () => {
    const ok = await copyText(turn.content);
    toast(
      ok
        ? { title: "已复制回复", description: `${turn.content.length} 字`, tone: "success" }
        : { title: "复制失败", description: "当前环境不允许访问剪贴板。", tone: "error" },
    );
  };

  const copyCitations = async () => {
    const text = citations
      .map((citation, index) => {
        const parts = [`[${index + 1}] ${citation.name || "来源"}`];
        if (citation.doc_id) parts.push(`doc ${citation.doc_id}`);
        if (citation.chunk_id) parts.push(`chunk ${citation.chunk_id}`);
        if (citation.url) parts.push(citation.url);
        return parts.join(" · ");
      })
      .join("\n");
    const ok = await copyText(text);
    toast(
      ok
        ? { title: "已复制引用", description: `${citations.length} 条来源`, tone: "success" }
        : { title: "复制失败", description: "当前环境不允许访问剪贴板。", tone: "error" },
    );
  };

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
          {turn.asOf ? <span>as_of {turn.asOf}</span> : null}
          {turn.traceId ? (
            <span
              className="hidden max-w-[220px] truncate font-mono sm:inline"
              title={turn.traceId}
            >
              trace {truncateMiddle(turn.traceId, 12, 6)}
            </span>
          ) : null}
          {isStopped ? <span className="text-warning-ink">已停止</span> : null}
          {typing ? (
            <span className="typewriter-caret text-caption text-muted-foreground" aria-hidden="true" />
          ) : null}
        </div>

        <div
          className={cn(
            "mt-1 rounded-xl border px-3.5 py-3",
            animate && !reduced && "animate-fade",
            isError
              ? "border-destructive/30 bg-destructive/10"
              : isStopped
                ? "border-border bg-surface-2"
                : "border-border bg-surface-1",
          )}
        >
          <div
            className={cn(collapsible && !expanded && "max-h-80 overflow-hidden")}
            aria-busy={typing}
          >
            {turn.status === "ok" ? (
              <RichText text={visibleContent} />
            ) : (
              <p className="whitespace-pre-wrap text-body leading-relaxed text-foreground">
                {visibleContent}
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
            <div className="mt-1.5 border-t border-destructive/20 pt-1.5">
              <p className="text-caption leading-relaxed text-muted-foreground">
                可稍后重试；若持续失败，请到驾驶台确认 /api/health 的核心模块状态与 503
                中文说明。
              </p>
              {onRetry ? (
                <button
                  type="button"
                  onClick={onRetry}
                  className="mt-1 inline-flex items-center gap-1 text-caption font-medium text-foreground underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <RotateCcw className="size-3" aria-hidden="true" />
                  重试这个问题
                </button>
              ) : null}
            </div>
          ) : null}

          {isStopped ? (
            <div className="mt-1.5 border-t border-border pt-1.5">
              <p className="text-caption leading-relaxed text-muted-foreground">
                本次生成已中止；保留已产生的上下文，可重新发送同一问题。
              </p>
              {onRetry ? (
                <button
                  type="button"
                  onClick={onRetry}
                  className="mt-1 inline-flex items-center gap-1 text-caption font-medium text-foreground underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <RotateCcw className="size-3" aria-hidden="true" />
                  重试这个问题
                </button>
              ) : null}
            </div>
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

          {turn.status === "ok" ? (
            <div className="mt-2 flex flex-wrap items-center gap-1 border-t border-border pt-1.5">
              <IconButton
                label="复制回复"
                size="icon-sm"
                className="size-6 [&_svg]:size-3"
                onClick={() => {
                  void copyReply();
                }}
              >
                <Copy aria-hidden="true" />
              </IconButton>
              {citations.length ? (
                <IconButton
                  label="复制引用来源"
                  size="icon-sm"
                  className="size-6 [&_svg]:size-3"
                  onClick={() => {
                    void copyCitations();
                  }}
                >
                  <Quote aria-hidden="true" />
                </IconButton>
              ) : null}
            </div>
          ) : null}

          {isLast && suggestions.length && onSuggestion ? (
            <div className="mt-2 border-t border-border pt-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="inline-flex items-center gap-1 text-tiny text-muted-foreground">
                  <Sparkles className="size-3" aria-hidden="true" />
                  追问建议
                </span>
                {suggestions.map((suggestion) => (
                  <button
                    key={suggestion.id}
                    type="button"
                    onClick={() => onSuggestion(suggestion.prompt)}
                    title="填入输入框，可编辑后发送"
                    className="max-w-full truncate rounded-full border border-border bg-surface-1 px-2 py-0.5 text-tiny text-muted-foreground transition-colors duration-150 hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    {suggestion.label}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {turn.decision ? <DecisionSummary decision={turn.decision} /> : null}
        </div>
      </div>
    </div>
  );
}
