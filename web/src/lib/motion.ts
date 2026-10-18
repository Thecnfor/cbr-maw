import { useEffect, useState } from "react";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function matchesReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

/**
 * 读取 `prefers-reduced-motion` 并订阅变化。
 * CSS 侧已在 tokens.css 全局降级；JS 驱动的动效（打字机 / KPI count-up）必须读这个 hook，
 * 否则无法真正“直接落位”。
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState<boolean>(matchesReducedMotion);

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia(REDUCED_MOTION_QUERY);
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    setReduced(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}

/** 真实已用时（秒），仅在 active 时每秒刷新；不做任何伪造的进度推进。 */
export function useElapsedSeconds(startedAt: number | null, active = true): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active || !startedAt) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active, startedAt]);

  if (!startedAt) return 0;
  return Math.max(0, Math.round((now - startedAt) / 1000));
}

/** 秒 → `12s` / `1m 05s`，用于运行中与完成 toast。 */
export function fmtElapsed(seconds: number): string {
  const safe = Math.max(0, Math.round(seconds));
  if (safe < 60) return `${safe}s`;
  const minutes = Math.floor(safe / 60);
  const rest = safe % 60;
  return `${minutes}m ${String(rest).padStart(2, "0")}s`;
}
