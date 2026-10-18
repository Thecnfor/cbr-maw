import { useId, type ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface PanelProps {
  title: ReactNode;
  icon?: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  flush?: boolean;
}

/** 统一面板：标题栏 hairline + 内容区，卡片圆角 20px，内部元素圆角更小。 */
export function Panel({
  title,
  icon,
  meta,
  children,
  className,
  bodyClassName,
  flush = false,
}: PanelProps) {
  const titleId = useId();
  return (
    <Card asChild className={cn("flex min-w-0 flex-col overflow-hidden", className)}>
      <section aria-labelledby={titleId}>
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border px-4 py-2.5">
          <h2
            id={titleId}
            className="flex min-w-0 items-center gap-2 text-desc font-semibold tracking-tight text-foreground [&_svg]:size-4 [&_svg]:shrink-0 [&_svg]:text-muted-foreground"
          >
            {icon}
            <span className="truncate">{title}</span>
          </h2>
          {meta ? <div className="flex shrink-0 items-center gap-2">{meta}</div> : null}
        </div>
        <div className={cn("min-w-0 flex-1", flush ? "p-0" : "p-4", bodyClassName)}>
          {children}
        </div>
      </section>
    </Card>
  );
}
