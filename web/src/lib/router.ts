import { useSyncExternalStore } from "react";

/**
 * 极简 hash 路由：`#/dashboard?as_of=2024-08-05&mode=collaborative&scenario=...`
 *
 * 选择 hash 的原因：
 * - FastAPI 以 `/ui/` 静态托管 dist，hash 路由不需要服务端 history fallback；
 * - 查询条件（场景 / 时点 / 模式 / 页签）可分享、可前进后退、刷新不丢。
 */

export interface Route {
  path: string;
  params: URLSearchParams;
}

function parseHash(): Route {
  const raw = window.location.hash.replace(/^#/, "");
  const [pathPart, queryPart] = raw.split("?");
  const path = pathPart?.startsWith("/") ? pathPart : `/${pathPart || "dashboard"}`;
  return { path: path || "/dashboard", params: new URLSearchParams(queryPart ?? "") };
}

function buildHash(path: string, params?: Record<string, string | null | undefined>): string {
  const query = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") query.set(key, value);
    }
  }
  const queryString = query.toString();
  return `#${path}${queryString ? `?${queryString}` : ""}`;
}

let current: Route = parseHash();
const listeners = new Set<() => void>();
let initialized = false;

function emit(): void {
  current = parseHash();
  for (const listener of listeners) listener();
}

function ensureInitialized(): void {
  if (initialized || typeof window === "undefined") return;
  initialized = true;
  if (!window.location.hash || !window.location.hash.startsWith("#/")) {
    window.history.replaceState(
      null,
      "",
      `${window.location.pathname}${window.location.search}${buildHash("/dashboard")}`,
    );
    current = parseHash();
  }
  window.addEventListener("hashchange", emit);
  window.addEventListener("popstate", emit);
}

ensureInitialized();

export function navigate(
  path: string,
  params?: Record<string, string | null | undefined>,
  options: { replace?: boolean } = {},
): void {
  const hash = buildHash(path, params);
  const url = `${window.location.pathname}${window.location.search}${hash}`;
  if (options.replace) {
    window.history.replaceState(null, "", url);
  } else {
    window.history.pushState(null, "", url);
  }
  emit();
}

export function paramsToRecord(params: URLSearchParams): Record<string, string> {
  const record: Record<string, string> = {};
  params.forEach((value, key) => {
    record[key] = value;
  });
  return record;
}

export function useRoute(): Route {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
    () => current,
  );
}
