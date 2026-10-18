import type { ReactNode } from "react";
import { Inbox } from "lucide-react";

import { cn } from "@/lib/utils";

interface EmptyStateProps {
  title: ReactNode;
  description?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ title, description, icon, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-border bg-surface-2/60 px-4 py-8 text-center",
        className,
      )}
    >
      <span className="text-muted-foreground" aria-hidden="true">
        {icon ?? <Inbox className="size-5" />}
      </span>
      <div className="text-body font-medium text-foreground">{title}</div>
      {description ? (
        <p className="max-w-md text-caption leading-relaxed text-muted-foreground">
          {description}
        </p>
      ) : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
