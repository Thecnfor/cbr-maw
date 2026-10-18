import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

import { cn } from "@/lib/utils";

export type ToastTone = "default" | "success" | "error";

export interface ToastInput {
  title: string;
  description?: string;
  tone?: ToastTone;
  /** 毫秒；默认 3200，错误 5000。 */
  duration?: number;
}

interface ToastItem extends Required<Omit<ToastInput, "description">> {
  id: number;
  description?: string;
}

interface ToastContextValue {
  toast: (input: ToastInput) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_META: Record<ToastTone, { icon: typeof Info; className: string }> = {
  default: { icon: Info, className: "text-muted-foreground" },
  success: { icon: CheckCircle2, className: "text-success-ink" },
  error: { icon: AlertTriangle, className: "text-destructive-ink" },
};

let toastCounter = 0;

function ToastRow({
  item,
  onDismiss,
}: {
  item: ToastItem;
  onDismiss: (id: number) => void;
}) {
  const meta = TONE_META[item.tone];
  const Icon = meta.icon;

  useEffect(() => {
    const timer = window.setTimeout(() => onDismiss(item.id), item.duration);
    return () => window.clearTimeout(timer);
  }, [item.id, item.duration, onDismiss]);

  return (
    <div
      role={item.tone === "error" ? "alert" : "status"}
      className="pointer-events-auto flex items-start gap-2.5 rounded-lg border border-border bg-surface-1 p-3 text-foreground shadow-raised animate-rise"
    >
      <span className={cn("mt-0.5 shrink-0", meta.className)} aria-hidden="true">
        <Icon className="size-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-body font-medium leading-snug text-foreground">{item.title}</p>
        {item.description ? (
          <p className="mt-0.5 break-words text-caption leading-relaxed text-muted-foreground">
            {item.description}
          </p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(item.id)}
        aria-label="关闭提示"
        title="关闭提示"
        className="grid size-6 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors duration-150 hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="size-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * 轻量 toast：不引入新的依赖（Radix Toast 不在现有依赖内），
 * 用 Portal + aria-live 实现；只动 opacity/transform，reduced-motion 由 CSS 全局降级。
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setItems((previous) => previous.filter((item) => item.id !== id));
  }, []);

  const toast = useCallback((input: ToastInput) => {
    toastCounter += 1;
    idRef.current = Math.max(idRef.current + 1, toastCounter);
    const item: ToastItem = {
      id: idRef.current,
      title: input.title,
      description: input.description,
      tone: input.tone ?? "default",
      duration: input.duration ?? (input.tone === "error" ? 5000 : 3200),
    };
    setItems((previous) => [...previous.slice(-2), item]);
  }, []);

  const value = useMemo<ToastContextValue>(() => ({ toast, dismiss }), [toast, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {typeof document === "undefined"
        ? null
        : createPortal(
            <div
              aria-label="通知"
              className="pointer-events-none fixed bottom-4 right-4 z-[70] flex w-[min(92vw,360px)] flex-col gap-2"
            >
              {items.map((item) => (
                <ToastRow key={item.id} item={item} onDismiss={dismiss} />
              ))}
            </div>,
            document.body,
          )}
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast 必须在 ToastProvider 内使用");
  return context;
}
