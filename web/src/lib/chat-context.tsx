import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { errorMessage, isAbortError, postChat } from "@/lib/api";
import { useRun } from "@/lib/run-context";
import { streamChat, StreamUnavailableError } from "@/lib/stream";
import type {
  ChatRequest,
  ChatResponse,
  ChatTurn,
  ChatTurnStatus,
  StageEvent,
  TraceEvent,
} from "@/lib/types";

const SESSION_KEY = "cbr-chat-session";
let turnCounter = 0;

function newSessionId(): string {
  const random =
    typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
      ? crypto.randomUUID().replaceAll("-", "").slice(0, 12)
      : Math.random().toString(16).slice(2, 14);
  return `ui-${random}`;
}

function readSessionId(): string {
  try {
    const stored = window.sessionStorage.getItem(SESSION_KEY);
    if (stored && stored.startsWith("ui-")) return stored;
  } catch {
    // 隐私模式：仅内存会话
  }
  const created = newSessionId();
  try {
    window.sessionStorage.setItem(SESSION_KEY, created);
  } catch {
    // ignore
  }
  return created;
}

function writeSessionId(sessionId: string): void {
  try {
    window.sessionStorage.setItem(SESSION_KEY, sessionId);
  } catch {
    // ignore
  }
}

function nextTurnId(prefix: string): string {
  turnCounter += 1;
  return `${prefix}-${Date.now().toString(36)}-${turnCounter}`;
}

export type ChatTransport = "stream" | "sync";

export interface ChatRunState {
  startedAt: number | null;
  transport: ChatTransport;
  usedFallback: boolean;
  runId: string | null;
  stageEvents: StageEvent[];
  activities: TraceEvent[];
}

const EMPTY_RUN: ChatRunState = {
  startedAt: null,
  transport: "stream",
  usedFallback: false,
  runId: null,
  stageEvents: [],
  activities: [],
};

interface ChatContextValue {
  sessionId: string;
  turns: ChatTurn[];
  sending: boolean;
  run: ChatRunState;
  lastCompletedTurnId: string | null;
  contextCleared: boolean;
  send: (text: string) => void;
  stop: () => void;
  clear: () => void;
  retryLast: () => void;
  clearContext: () => void;
  restoreContext: () => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

/**
 * 对话会话上下文（挂在 App 根部，切换页面不丢消息）。
 *
 * - 发送走 POST `/api/chat/stream`，`stage` / `trace` 事件驱动「协同分析中」进度；
 * - SSE 不可用时自动回退同步 `POST /api/chat`，进度面板标注「同步回退」；
 * - 收到 `chat` 后由页面按 `lastCompletedTurnId` 做一次打字机/淡入；
 * - 支持停止、失败重试、上下文（as_of）清除与会话保留。
 */
export function ChatProvider({ children }: { children: ReactNode }) {
  const { asOf, mode } = useRun();
  const [sessionId, setSessionId] = useState<string>(readSessionId);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const [run, setRun] = useState<ChatRunState>(EMPTY_RUN);
  const [lastCompletedTurnId, setLastCompletedTurnId] = useState<string | null>(null);
  const [contextCleared, setContextCleared] = useState(false);

  const sendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const sessionRef = useRef(sessionId);
  const requestSeqRef = useRef(0);
  const completedTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (completedTimerRef.current !== null) {
        window.clearTimeout(completedTimerRef.current);
        completedTimerRef.current = null;
      }
    };
  }, []);

  const markCompleted = useCallback((turnId: string) => {
    setLastCompletedTurnId(turnId);
    if (completedTimerRef.current !== null) window.clearTimeout(completedTimerRef.current);
    completedTimerRef.current = window.setTimeout(() => {
      setLastCompletedTurnId(null);
      completedTimerRef.current = null;
    }, 2600);
  }, []);

  const appendAssistant = useCallback(
    (
      content: string,
      status: ChatTurnStatus,
      extras: {
        citations?: ChatTurn["citations"];
        decision?: ChatTurn["decision"];
        traceId?: string | null;
        asOf?: string | null;
      } = {},
    ): string => {
      const id = nextTurnId("assistant");
      setTurns((previous) => [
        ...previous,
        {
          id,
          role: "assistant",
          content,
          citations: extras.citations ?? [],
          decision: extras.decision ?? null,
          traceId: extras.traceId ?? null,
          asOf: extras.asOf ?? (contextCleared ? null : asOf),
          status,
          createdAt: Date.now(),
        },
      ]);
      return id;
    },
    [asOf, contextCleared],
  );

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || sendingRef.current) return;

      const requestSession = sessionRef.current;
      const seq = requestSeqRef.current + 1;
      requestSeqRef.current = seq;
      const startedAt = Date.now();

      sendingRef.current = true;
      setSending(true);
      setLastCompletedTurnId(null);
      setRun({
        startedAt,
        transport: "stream",
        usedFallback: false,
        runId: null,
        stageEvents: [],
        activities: [],
      });

      setTurns((previous) => [
        ...previous,
        {
          id: nextTurnId("user"),
          role: "user",
          content: message,
          citations: [],
          decision: null,
          traceId: null,
          asOf: contextCleared ? null : asOf,
          status: "ok",
          createdAt: Date.now(),
        },
      ]);

      const controller = new AbortController();
      abortRef.current = controller;
      const contextAsOf = contextCleared ? null : asOf || null;
      const body: ChatRequest = {
        message,
        as_of: contextAsOf,
        session_id: requestSession,
        mode,
      };

      const isCurrent = () =>
        requestSeqRef.current === seq && sessionRef.current === requestSession;

      const applyStage = (stage: StageEvent) => {
        if (!isCurrent()) return;
        setRun((current) => ({ ...current, stageEvents: [...current.stageEvents, stage] }));
      };

      const applyTrace = (event: TraceEvent) => {
        if (!isCurrent()) return;
        setRun((current) => ({
          ...current,
          activities: [...current.activities, event].slice(-8),
        }));
      };

      const finishSuccess = (response: ChatResponse, transport: ChatTransport) => {
        if (!isCurrent()) return;
        setRun((current) => ({
          ...current,
          transport,
          usedFallback: transport === "sync",
          runId: response.trace_id ?? current.runId,
        }));
        const turnId = appendAssistant(response.reply || "（服务未返回回复文本）", "ok", {
          citations: response.citations ?? [],
          decision: response.decision ?? null,
          traceId: response.trace_id ?? null,
          asOf: response.as_of ?? contextAsOf,
        });
        markCompleted(turnId);
      };

      const finishStopped = () => {
        if (!isCurrent()) return;
        appendAssistant("已停止本次协同推理。", "stopped", { asOf: contextAsOf });
      };

      const finishError = (error: unknown) => {
        if (!isCurrent()) return;
        appendAssistant(`对话失败：${errorMessage(error)}`, "error", { asOf: contextAsOf });
      };

      void (async () => {
        try {
          const result = await streamChat(body, {
            signal: controller.signal,
            onRun: (runId) => {
              if (!isCurrent()) return;
              setRun((current) => ({ ...current, runId }));
            },
            onStage: applyStage,
            onTrace: applyTrace,
          });
          finishSuccess(result.chat, "stream");
        } catch (error) {
          if (!isCurrent()) return;
          if (isAbortError(error)) {
            finishStopped();
            return;
          }
          if (error instanceof StreamUnavailableError) {
            if (!isCurrent()) return;
            setRun((current) => ({ ...current, transport: "sync", usedFallback: true }));
            try {
              const response = await postChat(body, controller.signal);
              finishSuccess(response, "sync");
            } catch (syncError) {
              if (!isCurrent()) return;
              if (isAbortError(syncError)) finishStopped();
              else finishError(syncError);
            }
            return;
          }
          finishError(error);
        } finally {
          if (isCurrent()) {
            sendingRef.current = false;
            setSending(false);
            abortRef.current = null;
          }
        }
      })();
    },
    [appendAssistant, asOf, contextCleared, markCompleted, mode],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const retryLast = useCallback(() => {
    if (sendingRef.current) return;
    const last = turns[turns.length - 1];
    if (!last || last.role !== "assistant" || last.status === "ok") return;
    const previousUser = [...turns].reverse().find((turn) => turn.role === "user");
    if (!previousUser) return;
    setTurns((previous) => {
      let next = previous;
      if (next.length && next[next.length - 1]?.id === last.id) next = next.slice(0, -1);
      if (
        next.length &&
        next[next.length - 1]?.role === "user" &&
        next[next.length - 1]?.id === previousUser.id
      ) {
        next = next.slice(0, -1);
      }
      return next;
    });
    send(previousUser.content);
  }, [send, turns]);

  const clear = useCallback(() => {
    requestSeqRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    sendingRef.current = false;
    setSending(false);
    setRun(EMPTY_RUN);
    setLastCompletedTurnId(null);
    if (completedTimerRef.current !== null) {
      window.clearTimeout(completedTimerRef.current);
      completedTimerRef.current = null;
    }
    const next = newSessionId();
    sessionRef.current = next;
    writeSessionId(next);
    setSessionId(next);
    setTurns([]);
  }, []);

  const clearContext = useCallback(() => setContextCleared(true), []);
  const restoreContext = useCallback(() => setContextCleared(false), []);

  const value = useMemo<ChatContextValue>(
    () => ({
      sessionId,
      turns,
      sending,
      run,
      lastCompletedTurnId,
      contextCleared,
      send,
      stop,
      clear,
      retryLast,
      clearContext,
      restoreContext,
    }),
    [
      sessionId,
      turns,
      sending,
      run,
      lastCompletedTurnId,
      contextCleared,
      send,
      stop,
      clear,
      retryLast,
      clearContext,
      restoreContext,
    ],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatContextValue {
  const context = useContext(ChatContext);
  if (!context) throw new Error("useChat 必须在 ChatProvider 内使用");
  return context;
}
