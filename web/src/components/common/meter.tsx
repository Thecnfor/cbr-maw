import { cn } from "@/lib/utils";

const TONE_MAP = {
  neutral: "bg-foreground/70",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  info: "bg-info",
  viz: "bg-viz-1",
  viz2: "bg-viz-2",
} as const;

interface MeterProps {
  /** 0-100 */
  value: number | null;
  tone?: keyof typeof TONE_MAP;
  label: string;
  className?: string;
}

/** 细进度条：宽度由数据驱动，不做宽度补间动画。 */
export function Meter({ value, tone = "neutral", label, className }: MeterProps) {
  const safe = value === null || Number.isNaN(value) ? 0 : Math.min(100, Math.max(0, value));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(safe)}
      className={cn("h-1.5 w-full overflow-hidden rounded-full bg-surface-2", className)}
    >
      <div
        className={cn("h-full rounded-full transition-colors duration-150", TONE_MAP[tone])}
        style={{ width: `${safe}%` }}
      />
    </div>
  );
}
