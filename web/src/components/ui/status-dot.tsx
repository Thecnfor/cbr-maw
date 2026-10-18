import { cn } from "@/lib/utils";

const sizeMap = {
  sm: "size-1.5",
  md: "size-2",
  lg: "size-2.5",
} as const;

const toneMap = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  info: "bg-info",
  idle: "bg-muted-foreground/40",
} as const;

export type StatusTone = keyof typeof toneMap;

export interface StatusDotProps {
  status: StatusTone;
  size?: keyof typeof sizeMap;
  pulse?: boolean;
  className?: string;
  label?: string;
}

/** 状态点：只表达状态；默认装饰性（aria-hidden），需要语义时传 label。 */
export function StatusDot({ status, size = "md", pulse = false, className, label }: StatusDotProps) {
  return (
    <span
      className={cn(
        "inline-block shrink-0 rounded-full",
        sizeMap[size],
        toneMap[status],
        pulse && "animate-pulse",
        className,
      )}
      aria-hidden={label ? undefined : "true"}
      role={label ? "img" : undefined}
      aria-label={label}
    />
  );
}
