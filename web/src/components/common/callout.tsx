import type { ReactNode } from "react";

import {
  AlertTriangle,
  CheckCircle2,
  Info,
  XCircle,
} from "lucide-react";

import { cn } from "@/lib/utils";

type Tone = "neutral" | "success" | "warning" | "danger" | "info";

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "border-border bg-surface-2",
  success: "border-success/30 bg-success/10",
  warning: "border-warning/30 bg-warning/10",
  danger: "border-destructive/30 bg-destructive/10",
  info: "border-info/30 bg-info/10",
};

const TITLE_CLASSES: Record<Tone, string> = {
  neutral: "text-foreground",
  success: "text-success-ink",
  warning: "text-warning-ink",
  danger: "text-destructive-ink",
  info: "text-info-ink",
};

const ICON_CLASSES: Record<Tone, string> = {
  neutral: "text-muted-foreground",
  success: "text-success-ink",
  warning: "text-warning-ink",
  danger: "text-destructive-ink",
  info: "text-info-ink",
};

function DefaultIcon({ tone }: { tone: Tone }) {
  if (tone === "success") return <CheckCircle2 className="size-4" aria-hidden="true" />;
  if (tone === "danger") return <XCircle className="size-4" aria-hidden="true" />;
  if (tone === "warning") return <AlertTriangle className="size-4" aria-hidden="true" />;
  if (tone === "info") return <Info className="size-4" aria-hidden="true" />;
  return null;
}

interface CalloutProps {
  tone?: Tone;
  title?: ReactNode;
  icon?: ReactNode;
  children?: ReactNode;
  className?: string;
  actions?: ReactNode;
}

/** 语义提示块：只表达状态，不承载装饰。 */
export function Callout({
  tone = "neutral",
  title,
  icon,
  children,
  className,
  actions,
}: CalloutProps) {
  return (
    <div
      className={cn(
        "flex gap-2.5 rounded-lg border px-3 py-2.5 text-body",
        TONE_CLASSES[tone],
        className,
      )}
    >
      <span className={cn("mt-0.5 shrink-0", ICON_CLASSES[tone])}>
        {icon ?? <DefaultIcon tone={tone} />}
      </span>
      <div className="min-w-0 flex-1">
        {title ? (
          <div className={cn("text-body font-semibold", TITLE_CLASSES[tone])}>{title}</div>
        ) : null}
        {children ? (
          <div className={cn("text-caption leading-relaxed text-foreground/80", title && "mt-1")}>
            {children}
          </div>
        ) : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
    </div>
  );
}
