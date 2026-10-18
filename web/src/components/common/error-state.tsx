import { AlertTriangle, RefreshCw } from "lucide-react";

import { Callout } from "@/components/common/callout";
import { Button } from "@/components/ui/button";

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retrying?: boolean;
  details?: string | null;
  hint?: string;
  className?: string;
}

/** 请求失败的中文说明 + 重试；503 的 detail 原样展示，便于定位核心模块状态。 */
export function ErrorState({
  title = "本次请求失败",
  message,
  onRetry,
  retrying = false,
  details,
  hint,
  className,
}: ErrorStateProps) {
  return (
    <Callout
      tone="danger"
      title={title}
      icon={<AlertTriangle className="size-4" />}
      className={className}
      actions={
        onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}>
            <RefreshCw className={retrying ? "animate-spin" : undefined} aria-hidden="true" />
            {retrying ? "重试中" : "重试"}
          </Button>
        ) : null
      }
    >
      <p className="whitespace-pre-wrap break-words">{message}</p>
      {hint ? <p className="mt-1 text-muted-foreground">{hint}</p> : null}
      {details ? (
        <details className="mt-2">
          <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
            查看技术详情
          </summary>
          <pre className="scrollbar-thin mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-md border border-border bg-surface-1 p-2 font-mono text-caption">
            {details}
          </pre>
        </details>
      ) : null}
    </Callout>
  );
}
