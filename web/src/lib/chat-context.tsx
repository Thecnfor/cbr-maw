import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { errorMessage, isAbortError, postChat } from "@/lib/api";
import { useRun } from "@/lib/run-context";
import type { ChatTurn } from "@/lib/types";

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

interface ChatContextValue {
  sessionId: string;
  turns: ChatTurn[];
  sending: boolean;
  send: (text: string) => void;
  stop: () => void;
  clear: () => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

/**
 * 对话会话上下文（挂在 App 根部，切换页面不丢消息）。
 * session_id 写入 sessionStorage；清空对话会生成新的 session_id。
 */
export function ChatProvider({ children }: { children: ReactNode }) {
  const { asOf, mode } = useRun();
  const [sessionId, setSessionId] = useState<string>(readSessionId);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const sessionRef = useRef(sessionId);

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || sendingRef.current) return;

      sendingRef.current = true;
      setSending(true);
      const requestSession = sessionRef.current;
      setTurns((previous) => [
        ...previous,
        {
          id: nextTurnId("user"),
          role: "user",
          content: message,
          citations: [],
          decision: null,
          traceId: null,
          asOf,
          status: "ok",
          createdAt: Date.now(),
        },
      ]);

      const controller = new AbortController();
      abortRef.current = controller;

      void postChat(
        {
          message,
          as_of: asOf || null,
          session_id: sessionId,
          mode,
        },
        controller.signal,
      )
        .then((response) => {
          if (sessionRef.current !== requestSession) return;
          setTurns((previous) => [
            ...previous,
            {
              id: nextTurnId("assistant"),
              role: "assistant",
              content: response.reply || "（服务未返回回复文本）",
              citations: response.citations ?? [],
              decision: response.decision ?? null,
              traceId: response.trace_id ?? null,
              asOf: response.as_of ?? asOf,
              status: "ok",
              createdAt: Date.now(),
            },
          ]);
        })
        .catch((error: unknown) => {
          if (sessionRef.current !== requestSession) return;
          const aborted = isAbortError(error);
          setTurns((previous) => [
            ...previous,
            {
              id: nextTurnId("assistant"),
              role: "assistant",
              content: aborted
                ? "已停止本次协同推理。"
                : `对话失败：${errorMessage(error)}`,
              citations: [],
              decision: null,
              traceId: null,
              asOf,
              status: aborted ? "stopped" : "error",
              createdAt: Date.now(),
            },
          ]);
        })
        .finally(() => {
          if (sessionRef.current !== requestSession) return;
          sendingRef.current = false;
          setSending(false);
          abortRef.current = null;
        });
    },
    [asOf, mode, sessionId],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const clear = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    sendingRef.current = false;
    setSending(false);
    const next = newSessionId();
    sessionRef.current = next;
    writeSessionId(next);
    setSessionId(next);
    setTurns([]);
  }, []);

  const value = useMemo<ChatContextValue>(
    () => ({ sessionId, turns, sending, send, stop, clear }),
    [sessionId, turns, sending, send, stop, clear],
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

export function useChat(): ChatContextValue {
  const context = useContext(ChatContext);
  if (!context) throw new Error("useChat 必须在 ChatProvider 内使用");
  return context;
}
