import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface StatProps {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  className?: string;
  valueClassName?: string;
}

/** 紧凑指标块：caption 标签 + metric-value 数值 + 可选说明。 */
export function Stat({ label, value, hint, className, valueClassName }: StatProps) {
  return (
    <div className={cn("min-w-0", className)}>
      <div className="truncate text-caption text-muted-foreground">{label}</div>
      <div
        className={cn(
          "metric-value mt-0.5 truncate text-panel font-semibold leading-tight text-foreground",
          valueClassName,
        )}
      >
        {value}
      </div>
      {hint ? (
        <div className="mt-0.5 truncate text-caption text-muted-foreground">{hint}</div>
      ) : null}
    </div>
  );
}
