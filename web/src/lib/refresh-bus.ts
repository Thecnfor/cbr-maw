/**
 * 顶栏「重新生成」/ 命令面板与驾驶台决策状态之间的极简事件总线。
 *
 * 顶栏与命令面板是全局壳层、决策状态属于驾驶台页面；用订阅总线避免把昂贵的决策请求
 * 提升到 App 根（否则对话页也会触发请求），也避免壳层反向依赖页面组件。
 *
 * 命令面板可能从其他页面触发「重新生成」：此时还没有订阅者，请求会暂存 5 秒，
 * 等驾驶台挂载后立即消费，避免「点了没反应」。
 */
type Listener = () => void;

const listeners = new Set<Listener>();
let pendingAt: number | null = null;
const PENDING_TTL_MS = 5000;

export function subscribeRefreshRequest(listener: Listener): () => void {
  listeners.add(listener);
  if (pendingAt !== null && Date.now() - pendingAt <= PENDING_TTL_MS) {
    pendingAt = null;
    queueMicrotask(listener);
  } else {
    pendingAt = null;
  }
  return () => {
    listeners.delete(listener);
  };
}

export function requestRefresh(): void {
  if (listeners.size) {
    for (const listener of [...listeners]) listener();
    return;
  }
  pendingAt = Date.now();
}
