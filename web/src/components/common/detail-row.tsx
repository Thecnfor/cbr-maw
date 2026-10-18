import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** 区块内的小标签（关键指标 / 建议 / 协调结果等）。 */
export function MicroLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("text-caption font-medium text-muted-foreground", className)}>
      {children}
    </div>
  );
}

interface DetailRowProps {
  label: ReactNode;
  children: ReactNode;
  mono?: boolean;
}

/** 详情行：证据 Dialog / 来源 Dialog 的键值结构。 */
export function DetailRow({ label, children, mono = false }: DetailRowProps) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-2 border-b border-border/60 py-1.5 last:border-b-0">
      <dt className="text-caption text-muted-foreground">{label}</dt>
      <dd
        className={cn(
          "min-w-0 break-all text-caption text-foreground",
          mono && "font-mono tabular-nums",
        )}
      >
        {children}
      </dd>
    </div>
  );
}
