/**
 * 顶栏「重新生成」与驾驶台决策状态之间的极简事件总线。
 *
 * 顶栏是全局壳层、决策状态属于驾驶台页面；用订阅总线避免把昂贵的决策请求
 * 提升到 App 根（否则对话页也会触发请求），也避免顶栏反向依赖页面组件。
 */
type Listener = () => void;

const listeners = new Set<Listener>();

export function subscribeRefreshRequest(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function requestRefresh(): void {
  for (const listener of [...listeners]) listener();
}
