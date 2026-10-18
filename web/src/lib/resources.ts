import { useEffect, useState } from "react";

import { loadDataCards, loadTrace } from "@/lib/api";
import type { DataCard, TraceEvent } from "@/lib/types";

export interface TraceResource {
  events: TraceEvent[];
  loading: boolean;
  error: unknown;
  reload: () => void;
}

/** 审计轨迹：按 run_id 缓存，切换页签/返回页面不重复请求。 */
export function useTraceResource(runId: string | null): TraceResource {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [loading, setLoading] = useState(Boolean(runId));
  const [error, setError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!runId) {
      setEvents([]);
      setLoading(false);
      setError(null);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    void loadTrace(runId, nonce > 0)
      .then((data) => {
        if (!active) return;
        setEvents(data);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setEvents([]);
        setError(reason);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [runId, nonce]);

  return {
    events,
    loading,
    error,
    reload: () => setNonce((value) => value + 1),
  };
}

export interface DataCardsResource {
  cards: DataCard[];
  loading: boolean;
  error: unknown;
  reload: () => void;
}

/** 数据卡：无决策卡前不请求；成功后缓存。 */
export function useDataCardsResource(enabled: boolean): DataCardsResource {
  const [cards, setCards] = useState<DataCard[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(null);
    void loadDataCards(nonce > 0)
      .then((data) => {
        if (!active) return;
        setCards(data);
        setLoading(false);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setCards([]);
        setError(reason);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [enabled, nonce]);

  return {
    cards,
    loading,
    error,
    reload: () => setNonce((value) => value + 1),
  };
}
