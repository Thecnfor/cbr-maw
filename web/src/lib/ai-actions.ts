/**
 * 上下文 AI 动作的极简单次信箱。
 *
 * 驾驶台（智能体卡 / 证据 Dialog / 冲突行）与命令面板只负责「生成 prompt + 跳到对话」，
 * 对话页在挂载或收到通知时消费 prompt 并预填 Composer；会话状态仍在 ChatProvider 内，
 * 因此跳转不会清空已有对话。
 */
export interface PendingPrompt {
  prompt: string;
  nonce: number;
  source: string;
}

type Listener = () => void;

let pending: PendingPrompt | null = null;
let counter = 0;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of [...listeners]) listener();
}

/** 写入一条待预填 prompt（同时通知已挂载的对话页）。 */
export function queuePrompt(prompt: string, source = "context-action"): void {
  const text = prompt.trim();
  if (!text) return;
  counter += 1;
  pending = { prompt: text, nonce: counter, source };
  emit();
}

/** 取出并清空待预填 prompt；没有则返回 null。 */
export function consumePrompt(): PendingPrompt | null {
  const item = pending;
  pending = null;
  return item;
}

/** 订阅「有新 prompt」事件；对话页用于已挂载时立即预填。 */
export function subscribePrompt(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
