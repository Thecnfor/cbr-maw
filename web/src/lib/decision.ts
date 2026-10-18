import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

import {
  errorMessage,
  getDecision,
  isAbortError,
  primeTraceCache,
  type DecisionParams,
} from "@/lib/api";
import { streamDecision, StreamUnavailableError } from "@/lib/stream";
import type { DecisionCard, StageEvent, TraceEvent } from "@/lib/types";

interface CacheEntry {
  decision: DecisionCard;
  fetchedAt: number;
}

/** 决策缓存键 = (as_of, mode, scenario)，与后端缓存口径一致。 */
export function decisionKey(params: DecisionParams): string {
  return `${params.asOf}|${params.mode}|${params.scenario}`;
}

const cache = new Map<string, CacheEntry>();
let cacheVersion = 0;
const cacheListeners = new Set<() => void>();

function emitCacheChange(): void {
  cacheVersion += 1;
  for (const listener of [...cacheListeners]) listener();
}

function subscribeDecisionCache(listener: () => void): () => void {
  cacheListeners.add(listener);
  return () => {
    cacheListeners.delete(listener);
  };
}

function getDecisionCacheVersion(): number {
  return cacheVersion;
}

export function getCachedDecision(key: string): CacheEntry | undefined {
  return cache.get(key);
}

/**
 * 订阅决策缓存：命令面板等全局组件在决策完成后需要重新渲染
 * （例如把「为什么监管判定为未知？」替换成真实风险等级）。
 */
export function useCachedDecision(params: DecisionParams): DecisionCard | null {
  useSyncExternalStore(
    subscribeDecisionCache,
    getDecisionCacheVersion,
    getDecisionCacheVersion,
  );
  return cache.get(decisionKey(params))?.decision ?? null;
}

export type DecisionTransport = "stream" | "sync";

export interface DecisionRunState {
  active: boolean;
  transport: DecisionTransport;
  usedFallback: boolean;
  runId: string | null;
  stageEvents: StageEvent[];
  activities: TraceEvent[];
  startedAt: number | null;
  finishedAt: number | null;
}

export interface DecisionCompletion {
  at: number;
  runId: string;
  elapsedMs: number;
  transport: DecisionTransport;
  usedFallback: boolean;
}

export interface DecisionFailure {
  at: number;
  message: string;
}

interface RunSnapshot extends DecisionRunState {
  key: string;
}

interface CompletionSnapshot extends DecisionCompletion {
  key: string;
}

interface FailureSnapshot extends DecisionFailure {
  key: string;
}

const EMPTY_RUN: DecisionRunState = {
  active: false,
  transport: "stream",
  usedFallback: false,
  runId: null,
  stageEvents: [],
  activities: [],
  startedAt: null,
  finishedAt: null,
};

interface DataState {
  key: string;
  decision: DecisionCard;
  fetchedAt: number;
}

export interface DecisionState {
  decision: DecisionCard | null;
  error: unknown | null;
  loading: boolean;
  refreshing: boolean;
  fetchedAt: number | null;
  fromCache: boolean;
  startedAt: number | null;
  refresh: () => void;
  retry: () => void;
  cancel: () => void;
  cancelled: boolean;
  run: DecisionRunState;
  lastCompleted: DecisionCompletion | null;
  lastFailed: DecisionFailure | null;
}

/**
 * 决策请求 hook（AI-native 版）。
 *
 * - 首次加载（本地无缓存）与「重新生成」走 SSE `/api/decision/stream`；
 * - SSE 不可用（404 / 非 event-stream / 网络不可达）时自动回退同步 `/api/decision`，
 *   并通过 `run.usedFallback` 告诉 UI 当前阶段只是本地估算，不伪造真实事件；
 * - 运行中暴露 stageEvents / trace 活动流 / run_id / AbortController 取消能力；
 * - 完成后写入模块缓存，并把流式 trace 直接 prime 到 trace 缓存，供「协同过程」复用。
 */
export function useDecision(params: DecisionParams, enabled = true): DecisionState {
  const key = decisionKey(params);
  const [data, setData] = useState<DataState | null>(() => {
    const cached = cache.get(key);
    return cached ? { key, decision: cached.decision, fetchedAt: cached.fetchedAt } : null;
  });
  const [errorState, setErrorState] = useState<{ key: string; error: unknown } | null>(null);
  const [refreshState, setRefreshState] = useState<{ key: string; nonce: number } | null>(null);
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [completion, setCompletion] = useState<CompletionSnapshot | null>(null);
  const [failure, setFailure] = useState<FailureSnapshot | null>(null);
  const [cancelledKey, setCancelledKey] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const force = refreshState !== null && refreshState.key === key && refreshState.nonce > 0;

  useEffect(() => {
    if (!enabled) return;

    const cached = cache.get(key);
    if (cached && !force) {
      setData({ key, decision: cached.decision, fetchedAt: cached.fetchedAt });
      setErrorState(null);
      setCancelledKey(null);
      setRun((current) => (current?.key === key && current.active ? current : null));
      return;
    }

    let active = true;
    const controller = new AbortController();
    controllerRef.current = controller;
    const startedAt = Date.now();

    setRun({
      key,
      active: true,
      transport: "stream",
      usedFallback: false,
      runId: null,
      stageEvents: [],
      activities: [],
      startedAt,
      finishedAt: null,
    });
    setErrorState(null);
    setCancelledKey(null);

    const settleRun = (transport: DecisionTransport, runId: string | null) => {
      const finishedAt = Date.now();
      setRun((current) =>
        current && current.key === key
          ? {
              ...current,
              active: false,
              finishedAt,
              transport,
              usedFallback: transport === "sync",
              runId: runId ?? current.runId,
            }
          : current,
      );
      return finishedAt;
    };

    const succeed = (
      decision: DecisionCard,
      transport: DecisionTransport,
      traceEvents: TraceEvent[],
    ) => {
      if (!active) return;
      const fetchedAt = Date.now();
      cache.set(key, { decision, fetchedAt });
      emitCacheChange();
      primeTraceCache(decision.run_id, traceEvents);
      setData({ key, decision, fetchedAt });
      settleRun(transport, decision.run_id);
      setCompletion({
        key,
        at: Date.now(),
        runId: decision.run_id,
        elapsedMs: Math.max(0, Date.now() - startedAt),
        transport,
        usedFallback: transport === "sync",
      });
    };

    const fail = (error: unknown, transport: DecisionTransport = "stream") => {
      if (!active) return;
      setErrorState({ key, error });
      setFailure({ key, at: Date.now(), message: errorMessage(error) });
      settleRun(transport, null);
    };

    const abortLocally = () => {
      if (!active) return;
      setRun((current) =>
        current && current.key === key
          ? { ...current, active: false, finishedAt: Date.now() }
          : current,
      );
      setCancelledKey(key);
    };

    void (async () => {
      try {
        const result = await streamDecision(params, {
          refresh: force,
          signal: controller.signal,
          onRun: (runId) => {
            if (!active) return;
            setRun((current) =>
              current && current.key === key ? { ...current, runId } : current,
            );
          },
          onStage: (stage) => {
            if (!active) return;
            setRun((current) =>
              current && current.key === key
                ? { ...current, stageEvents: [...current.stageEvents, stage] }
                : current,
            );
          },
          onTrace: (event) => {
            if (!active) return;
            setRun((current) =>
              current && current.key === key
                ? { ...current, activities: [...current.activities, event].slice(-8) }
                : current,
            );
          },
        });
        succeed(result.decision, "stream", result.traceEvents);
      } catch (error) {
        if (!active || isAbortError(error)) {
          abortLocally();
          return;
        }

        if (error instanceof StreamUnavailableError) {
          if (!active) return;
          setRun((current) =>
            current && current.key === key
              ? { ...current, transport: "sync", usedFallback: true }
              : current,
          );
          try {
            const decision = await getDecision(params, {
              refresh: force,
              signal: controller.signal,
            });
            succeed(decision, "sync", []);
          } catch (syncError) {
            if (!active || isAbortError(syncError)) {
              abortLocally();
              return;
            }
            fail(syncError, "sync");
          }
          return;
        }

        fail(error);
      }
    })();

    return () => {
      active = false;
      controller.abort();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
    // params 由 asOf / scenario / mode 派生，key 已覆盖其变化
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, force, enabled]);

  const refresh = useCallback(() => {
    setRefreshState((current) => ({
      key,
      nonce: current?.key === key ? current.nonce + 1 : 1,
    }));
  }, [key]);

  // 手动刷新只对当前组合生效：切走再回来时不再重复强制刷新。
  useEffect(() => {
    setRefreshState((current) => (current && current.key !== key ? null : current));
  }, [key]);

  const cancel = useCallback(() => {
    const controller = controllerRef.current;
    if (!controller) return;
    setCancelledKey(key);
    controller.abort();
  }, [key]);

  const currentData = data?.key === key ? data : null;
  const currentCache = cache.get(key);
  const decision = currentData?.decision ?? currentCache?.decision ?? null;
  const error = errorState?.key === key ? errorState.error : null;
  const currentRun = run?.key === key ? run : null;
  const cancelled = cancelledKey === key;
  const loading = Boolean(
    enabled && (currentRun?.active || (!decision && !error && !cancelled)),
  );

  return {
    decision,
    error,
    loading,
    refreshing: loading && Boolean(decision),
    fetchedAt: currentData?.fetchedAt ?? currentCache?.fetchedAt ?? null,
    fromCache: !currentData && Boolean(currentCache),
    startedAt: currentRun?.startedAt ?? null,
    refresh,
    retry: refresh,
    cancel,
    cancelled,
    run: currentRun ?? EMPTY_RUN,
    lastCompleted: completion?.key === key ? completion : null,
    lastFailed: failure?.key === key ? failure : null,
  };
}
