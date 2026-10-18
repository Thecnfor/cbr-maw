import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  breadcrumb?: ReactNode;
  children?: ReactNode;
  className?: string;
}

/** 页头：mono 面包屑 + H1 26px + 13.5px 描述 + 右侧操作区。 */
export function PageHeader({
  title,
  description,
  actions,
  breadcrumb,
  children,
  className,
}: PageHeaderProps) {
  return (
    <div
      className={cn(
        "dash-pagehead flex flex-wrap items-end justify-between gap-x-6 gap-y-3",
        className,
      )}
    >
      <div className="min-w-0">
        {breadcrumb ? <div className="dash-crumbs">{breadcrumb}</div> : null}
        <h1>{title}</h1>
        {description ? <p className="dash-desc max-w-2xl">{description}</p> : null}
        {children}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
