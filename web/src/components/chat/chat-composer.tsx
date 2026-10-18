import { useEffect, useRef, useState } from "react";
import { Send, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ChatComposerProps {
  sending: boolean;
  prefill?: { value: string; nonce: number } | null;
  onSend: (text: string) => void;
  onStop: () => void;
}

export function ChatComposer({ sending, prefill, onSend, onStop }: ChatComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 112)}px`;
  }, [value]);

  useEffect(() => {
    if (!prefill) return;
    setValue(prefill.value);
    const element = textareaRef.current;
    if (!element) return;
    const end = prefill.value.length;
    window.requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(end, end);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [prefill?.nonce]);

  const submit = () => {
    const text = value.trim();
    if (!text || sending) return;
    onSend(text);
    setValue("");
    window.requestAnimationFrame(() => textareaRef.current?.focus());
  };

  return (
    <div className="rounded-xl border border-border bg-surface-1 p-2 transition-colors duration-150 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring">
      <label htmlFor="chat-input" className="sr-only">
        对话输入
      </label>
      <textarea
        id="chat-input"
        ref={textareaRef}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
          event.preventDefault();
          submit();
        }}
        rows={1}
        placeholder="输入你的问题，例如：2024-08-05 前后跨境资金流出压力如何？"
        className={cn(
          "block max-h-28 min-h-11 w-full resize-none border-0 bg-transparent px-1.5 py-2 text-body text-foreground",
          "placeholder:text-muted-foreground focus:outline-none",
        )}
      />
      <div className="flex flex-wrap items-center justify-between gap-2 px-1">
        <span className="text-tiny text-muted-foreground">
          Enter 发送 · Shift+Enter 换行 · 会话 ID 保持不变
        </span>
        <div className="flex items-center gap-1.5">
          {sending ? (
            <Button variant="outline" size="sm" onClick={onStop}>
              <Square aria-hidden="true" />
              停止
            </Button>
          ) : null}
          <Button size="sm" onClick={submit} disabled={sending || !value.trim()}>
            <Send aria-hidden="true" />
            发送
          </Button>
        </div>
      </div>
    </div>
  );
}
