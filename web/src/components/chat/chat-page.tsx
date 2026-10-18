import { useEffect, useMemo, useRef, useState } from "react";
import { CornerDownRight, RotateCcw, Trash2, X } from "lucide-react";

import { Callout } from "@/components/common/callout";
import { PageHeader } from "@/components/common/page-header";
import { TopProgress } from "@/components/common/top-progress";
import { ChatComposer } from "@/components/chat/chat-composer";
import { ChatEmpty } from "@/components/chat/chat-empty";
import { ChatMessage } from "@/components/chat/chat-message";
import { ChatRunProgress } from "@/components/chat/chat-run-progress";
import { SourceDialog } from "@/components/chat/source-dialog";
import { EvidenceDialog } from "@/components/dashboard/evidence-dialog";
import { RunControls } from "@/components/layout/run-controls";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { consumePrompt, queuePrompt, subscribePrompt } from "@/lib/ai-actions";
import { useChat } from "@/lib/chat-context";
import { modeMeta } from "@/lib/labels";
import { useRun } from "@/lib/run-context";
import { buildFollowUps } from "@/lib/suggestions";
import { useToast } from "@/lib/toast";
import type { Evidence, SourceRef } from "@/lib/types";

export function ChatPage() {
  const run = useRun();
  const {
    sessionId,
    turns,
    sending,
    run: chatRun,
    lastCompletedTurnId,
    contextCleared,
    send,
    stop,
    clear,
    retryLast,
    clearContext,
    restoreContext,
  } = useChat();
  const { toast } = useToast();
  const [citation, setCitation] = useState<SourceRef | null>(null);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [prefill, setPrefill] = useState<{ value: string; nonce: number } | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const prefillNonceRef = useRef(0);

  const evidenceList = useMemo(() => {
    const map = new Map<string, Evidence>();
    for (const turn of turns) {
      for (const item of turn.decision?.evidence ?? []) {
        map.set(item.evidence_id, item);
      }
    }
    return [...map.values()];
  }, [turns]);

  useEffect(() => {
    document.title = "智能对话 · CBR-MAW";
  }, []);

  useEffect(() => {
    const consume = () => {
      const item = consumePrompt();
      if (item) setPrefill({ value: item.prompt, nonce: item.nonce });
    };
    consume();
    return subscribePrompt(consume);
  }, []);

  useEffect(() => {
    if (!stickRef.current) return;
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [turns.length, sending]);

  // 打字机逐字展开时持续贴底，避免长回复在展开过程中把结尾与追问 chips 推出视口。
  useEffect(() => {
    if (!lastCompletedTurnId) return;
    const tick = () => {
      if (!stickRef.current) return;
      const element = scrollRef.current;
      if (element) element.scrollTop = element.scrollHeight;
    };
    tick();
    const interval = window.setInterval(tick, 120);
    const timeout = window.setTimeout(() => window.clearInterval(interval), 1800);
    return () => {
      window.clearInterval(interval);
      window.clearTimeout(timeout);
    };
  }, [lastCompletedTurnId]);

  const lastTurn = turns.length ? turns[turns.length - 1] : null;
  const suggestions = useMemo(
    () =>
      lastTurn?.role === "assistant" && lastTurn.status === "ok"
        ? buildFollowUps(lastTurn.decision)
        : [],
    [lastTurn],
  );

  const handleSend = (text: string) => {
    stickRef.current = true;
    send(text);
  };

  const handlePrefill = (prompt: string) => {
    prefillNonceRef.current = Math.max(prefillNonceRef.current + 1, Date.now());
    setPrefill({ value: prompt, nonce: prefillNonceRef.current });
  };

  const handleClear = () => {
    clear();
    setCitation(null);
    setEvidenceId(null);
    setPrefill(null);
  };

  const handleClearContext = () => {
    clearContext();
    toast({
      title: "已清除上下文",
      description: "后续提问不再绑定 as_of 与场景，仅使用会话历史。",
      tone: "default",
    });
  };

  const retryAvailable =
    lastTurn?.role === "assistant" && lastTurn.status !== "ok" ? retryLast : undefined;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <TopProgress active={sending} label="协同对话进行中" />
      <div
        ref={scrollRef}
        onScroll={(event) => {
          const element = event.currentTarget;
          stickRef.current =
            element.scrollHeight - element.scrollTop - element.clientHeight < 120;
        }}
        className="scrollbar-thin min-h-0 flex-1 overflow-y-auto"
      >
        <div className="mx-auto w-full max-w-4xl px-4 pb-8 pt-6 sm:px-6">
          <PageHeader
            title="智能对话"
            description="用自然语言追问共享信号、三主体分歧与核验细节。回复附带引用来源；关联决策卡可直接跳转驾驶台或下载简报。会话上下文在本次浏览会话内保持。"
          />

          <div className="mt-4 xl:hidden">
            <Card className="p-4">
              <RunControls variant="page" />
            </Card>
          </div>

          <div className="mt-4 rounded-lg border border-border bg-surface-1 px-3 py-2 text-caption text-muted-foreground">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                <span className="min-w-0 truncate">
                  会话{" "}
                  <span className="font-mono text-foreground" title={sessionId}>
                    {sessionId}
                  </span>
                </span>
                <span>消息 {turns.length}</span>
                {sending ? <span className="text-warning-ink">生成中…</span> : null}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={handleClear}
                disabled={!turns.length && !sending}
              >
                <Trash2 aria-hidden="true" />
                清空对话
              </Button>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-border pt-2">
              <span className="text-tiny text-muted-foreground">上下文</span>
              {contextCleared ? (
                <>
                  <Badge variant="muted" className="text-tiny">
                    已清除 · 仅使用会话历史
                  </Badge>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto h-6 px-1.5 text-tiny"
                    onClick={restoreContext}
                  >
                    <RotateCcw aria-hidden="true" />
                    恢复上下文
                  </Button>
                </>
              ) : (
                <>
                  <Badge variant="outline" className="max-w-full text-tiny">
                    <span className="truncate">场景：{run.scenario?.name ?? "—"}</span>
                  </Badge>
                  <Badge variant="outline" className="text-tiny">
                    as_of <span className="metric-value">{run.asOf}</span>
                  </Badge>
                  <Badge variant="outline" className="text-tiny">
                    {modeMeta(run.mode).label}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto h-6 px-1.5 text-tiny"
                    onClick={handleClearContext}
                  >
                    <X aria-hidden="true" />
                    清除上下文
                  </Button>
                </>
              )}
            </div>
          </div>

          {run.health && run.health.service_ready === false ? (
            <Callout tone="warning" className="mt-3" title="核心服务尚未就绪">
              对话请求可能返回 503 中文说明。可在侧栏查看待就绪模块，或先使用 Streamlit
              回退界面；待核心模块装配完成后重试即可。
            </Callout>
          ) : null}

          <div className="mt-5 space-y-5">
            {turns.length === 0 ? (
              <ChatEmpty onPick={handleSend} />
            ) : (
              turns.map((turn, index) => {
                const isLast = index === turns.length - 1;
                return (
                  <ChatMessage
                    key={turn.id}
                    turn={turn}
                    isLast={isLast}
                    animate={turn.id === lastCompletedTurnId}
                    suggestions={isLast ? suggestions : []}
                    onOpenCitation={setCitation}
                    onRetry={isLast ? retryAvailable : undefined}
                    onSuggestion={handlePrefill}
                  />
                );
              })
            )}
            {sending ? (
              <ChatRunProgress
                startedAt={chatRun.startedAt}
                active={sending}
                stageEvents={chatRun.stageEvents}
                activities={chatRun.activities}
                usedFallback={chatRun.usedFallback}
                onStop={stop}
              />
            ) : null}
          </div>

          {!turns.length && !sending && prefill ? (
            <p className="mt-3 flex items-center gap-1.5 text-caption text-muted-foreground">
              <CornerDownRight className="size-3.5" aria-hidden="true" />
              已把你的追问填入下方输入框，可编辑后按 Enter 发送。
            </p>
          ) : null}
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-surface-1 px-4 py-3 sm:px-6">
        <div className="mx-auto w-full max-w-4xl">
          <ChatComposer
            sending={sending}
            prefill={prefill}
            onSend={handleSend}
            onStop={stop}
          />
        </div>
      </div>

      <SourceDialog
        citation={citation}
        evidenceList={evidenceList}
        onOpenChange={(open) => {
          if (!open) setCitation(null);
        }}
        onOpenEvidence={(id) => {
          setCitation(null);
          setEvidenceId(id);
        }}
      />

      <EvidenceDialog
        evidenceId={evidenceId}
        evidenceList={evidenceList}
        onOpenChange={(open) => {
          if (!open) setEvidenceId(null);
        }}
        onAskAI={(prompt) => queuePrompt(prompt, "chat-evidence")}
      />
    </div>
  );
}
