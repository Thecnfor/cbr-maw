import { useCallback, useEffect, useState } from "react";

import { getDecision, isAbortError, type DecisionParams } from "@/lib/api";
import type { DecisionCard } from "@/lib/types";

interface CacheEntry {
  decision: DecisionCard;
  fetchedAt: number;
}

/** 决策缓存键 = (as_of, mode, scenario)，与后端缓存口径一致。 */
export function decisionKey(params: DecisionParams): string {
  return `${params.asOf}|${params.mode}|${params.scenario}`;
}

const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<DecisionCard>>();

export function getCachedDecision(key: string): CacheEntry | undefined {
  return cache.get(key);
}

/**
 * 以 (as_of, mode, scenario) 为键做内存缓存 + 并发去重。
 * 同一组合重复进入页面时立即出结果；手动刷新走 refresh=true 绕过服务端缓存。
 */
function requestDecision(
  key: string,
  params: DecisionParams,
  force: boolean,
): Promise<DecisionCard> {
  if (!force) {
    const cached = cache.get(key);
    if (cached) return Promise.resolve(cached.decision);
  }
  const pending = inflight.get(key);
  if (pending) return pending;

  const promise = getDecision(params, { refresh: force })
    .then((decision) => {
      cache.set(key, { decision, fetchedAt: Date.now() });
      return decision;
    })
    .finally(() => {
      if (inflight.get(key) === promise) inflight.delete(key);
    });
  inflight.set(key, promise);
  return promise;
}

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
}

/**
 * 决策请求 hook。
 * - `enabled=false` 时等待场景加载完成，避免首屏用错误默认时点发请求；
 * - 切换条件时若有缓存立即渲染，否则骨架屏；
 * - 手动刷新保留旧数据，仅显示进度条，不闪屏。
 */
export function useDecision(
  params: DecisionParams,
  enabled = true,
): DecisionState {
  const key = decisionKey(params);
  const [data, setData] = useState<DataState | null>(() => {
    const cached = cache.get(key);
    return cached ? { key, decision: cached.decision, fetchedAt: cached.fetchedAt } : null;
  });
  const [errorState, setErrorState] = useState<{ key: string; error: unknown } | null>(null);
  const [pending, setPending] = useState<{ key: string; startedAt: number } | null>(null);
  const [refreshState, setRefreshState] = useState<{ key: string; nonce: number } | null>(null);

  const force =
    refreshState !== null && refreshState.key === key && refreshState.nonce > 0;

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    const cached = cache.get(key);
    if (cached && !force) {
      setData({ key, decision: cached.decision, fetchedAt: cached.fetchedAt });
      setErrorState(null);
      setPending((current) => (current?.key === key ? null : current));
      return;
    }

    setPending({ key, startedAt: Date.now() });
    setErrorState(null);

    void requestDecision(key, params, force)
      .then((decision) => {
        if (!active) return;
        setData({ key, decision, fetchedAt: Date.now() });
        setPending((current) => (current?.key === key ? null : current));
      })
      .catch((error: unknown) => {
        if (!active || isAbortError(error)) return;
        setErrorState({ key, error });
        setPending((current) => (current?.key === key ? null : current));
      });

    return () => {
      active = false;
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

  const currentData = data?.key === key ? data : null;
  const currentCache = cache.get(key);
  const decision = currentData?.decision ?? currentCache?.decision ?? null;
  const error = errorState?.key === key ? errorState.error : null;
  const isPending = pending?.key === key;
  const loading = Boolean(enabled && (isPending || (!decision && !error)));

  return {
    decision,
    error,
    loading,
    refreshing: loading && Boolean(decision),
    fetchedAt: currentData?.fetchedAt ?? currentCache?.fetchedAt ?? null,
    fromCache: !currentData && Boolean(currentCache),
    startedAt: isPending ? (pending?.startedAt ?? null) : null,
    refresh,
  };
}
