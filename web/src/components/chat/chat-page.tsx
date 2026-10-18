import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Sparkles, Trash2 } from "lucide-react";

import { Callout } from "@/components/common/callout";
import { PageHeader } from "@/components/common/page-header";
import { ChatComposer } from "@/components/chat/chat-composer";
import { ChatEmpty } from "@/components/chat/chat-empty";
import { ChatMessage } from "@/components/chat/chat-message";
import { SourceDialog } from "@/components/chat/source-dialog";
import { EvidenceDialog } from "@/components/dashboard/evidence-dialog";
import { RunControls } from "@/components/layout/run-controls";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useChat } from "@/lib/chat-context";
import { modeMeta } from "@/lib/labels";
import { useRun } from "@/lib/run-context";
import type { Evidence, SourceRef } from "@/lib/types";

const CHAT_STEPS = [
  "解析问题与时点约束",
  "检索共享信号与知识库",
  "监管 / 投资 / 融资协同推理",
  "证据核验与引用绑定",
  "生成可复核回复",
];

function ChatPending() {
  const [startedAt] = useState(() => Date.now());
  const [now, setNow] = useState(startedAt);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const elapsed = Math.max(0, Math.floor((now - startedAt) / 1000));
  const stepIndex = Math.min(Math.floor(elapsed / 2.5), CHAT_STEPS.length - 1);

  return (
    <div className="flex gap-2.5" role="status" aria-live="polite">
      <span
        className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface-1 text-foreground"
        aria-hidden="true"
      >
        <Sparkles className="size-3.5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-caption text-muted-foreground">
          协同助手 · 推理中{" "}
          <span className="metric-value text-foreground">{elapsed}s</span>
        </div>
        <div className="mt-1 rounded-xl border border-border bg-surface-1 px-3.5 py-3">
          <div className="flex items-center gap-2 text-body text-foreground">
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            协同编排推理中（共享信号 → 工具 → 证据核验）
          </div>
          <p className="mt-1 text-caption text-muted-foreground">{CHAT_STEPS[stepIndex]}</p>
          <p className="mt-2 border-t border-border pt-2 text-caption leading-relaxed text-muted-foreground">
            真实 LLM 约 12 秒；此处仅展示推理阶段与已用时，不轮询、不伪造中间结论。
            可点击输入框旁的「停止」中止本次请求。
          </p>
        </div>
      </div>
    </div>
  );
}

export function ChatPage() {
  const run = useRun();
  const { sessionId, turns, sending, send, stop, clear } = useChat();
  const [citation, setCitation] = useState<SourceRef | null>(null);
  const [evidenceId, setEvidenceId] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

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
    if (!stickRef.current) return;
    const element = scrollRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [turns.length, sending]);

  const handleSend = (text: string) => {
    stickRef.current = true;
    send(text);
  };

  const handleClear = () => {
    clear();
    setCitation(null);
    setEvidenceId(null);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
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

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface-1 px-3 py-2 text-caption text-muted-foreground">
            <span className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
              <span className="min-w-0 truncate">
                会话{" "}
                <span className="font-mono text-foreground" title={sessionId}>
                  {sessionId}
                </span>
              </span>
              <span>
                as_of <span className="metric-value text-foreground">{run.asOf}</span>
              </span>
              <span>
                模式 <span className="text-foreground">{modeMeta(run.mode).label}</span>
              </span>
              <span>消息 {turns.length}</span>
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

          {run.health && run.health.service_ready === false ? (
            <Callout
              tone="warning"
              className="mt-3"
              title="核心服务尚未就绪"
            >
              对话请求可能返回 503 中文说明。可在侧栏查看待就绪模块，或先使用 Streamlit
              回退界面；待核心模块装配完成后重试即可。
            </Callout>
          ) : null}

          <div className="mt-5 space-y-5">
            {turns.length === 0 ? (
              <ChatEmpty onPick={handleSend} />
            ) : (
              turns.map((turn) => (
                <ChatMessage
                  key={turn.id}
                  turn={turn}
                  onOpenCitation={setCitation}
                />
              ))
            )}
            {sending ? <ChatPending /> : null}
          </div>
        </div>
      </div>

      <div className="shrink-0 border-t border-border bg-surface-1 px-4 py-3 sm:px-6">
        <div className="mx-auto w-full max-w-4xl">
          <ChatComposer sending={sending} onSend={handleSend} onStop={stop} />
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
      />
    </div>
  );
}
