import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

const STEPS = [
  "监管智能体：检索时点可得证据",
  "投资智能体：组合尾部风险测算",
  "融资智能体：融资成本与现金流评估",
  "黑板证据共享与去重",
  "交叉验证与分歧识别",
  "协调仲裁与决策卡定稿",
] as const;

interface AnalysisProgressProps {
  active: boolean;
  startedAt: number | null;
  compact?: boolean;
  className?: string;
}

/**
 * 协同分析进度观感（仅文案轮播 + 真实已用时，不伪造数据、不轮询）。
 * 真实 LLM 约 12 秒，6 个阶段每 2 秒推进一次；结果返回后组件即卸载。
 */
export function AnalysisProgress({
  active,
  startedAt,
  compact = false,
  className,
}: AnalysisProgressProps) {
  const [now, setNow] = useState(() => Date.now());
  const [mountedAt] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [active]);

  useEffect(() => {
    setNow(Date.now());
  }, [startedAt, active]);

  if (!active) return null;

  const start = startedAt ?? mountedAt;
  const elapsed = Math.max(0, Math.round((now - start) / 1000));
  const stepIndex = Math.min(Math.floor(elapsed / 2), STEPS.length - 1);

  if (compact) {
    return (
      <div
        role="status"
        aria-live="polite"
        className={cn(
          "flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-border bg-surface-1 px-3 py-2 shadow-card",
          className,
        )}
      >
        <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-hidden="true" />
        <span className="text-body font-medium text-foreground">协同分析中</span>
        <span className="truncate text-caption text-muted-foreground">{STEPS[stepIndex]}</span>
        <span className="metric-value ml-auto text-caption text-muted-foreground">
          已用时 {elapsed}s
        </span>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "rounded-lg border border-border bg-surface-1 p-3 shadow-card",
        className,
      )}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Loader2 className="size-3.5 animate-spin text-muted-foreground" aria-hidden="true" />
        <span className="text-body font-medium text-foreground">
          协同分析中（监管 / 投资 / 融资）
        </span>
        <span className="metric-value ml-auto text-caption text-muted-foreground">
          已用时 {elapsed}s
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {STEPS.map((step, index) => (
          <span
            key={step}
            className={cn(
              "rounded-full border px-2 py-0.5 text-caption",
              index === stepIndex
                ? "border-foreground/30 bg-surface-2 text-foreground"
                : index < stepIndex
                  ? "border-border text-muted-foreground"
                  : "border-border/60 text-muted-foreground/60",
            )}
          >
            {step}
          </span>
        ))}
      </div>
      <p className="mt-2 text-caption text-muted-foreground">
        真实 LLM 推理约 12 秒；此处仅展示协同阶段与已用时，不伪造中间结果。
      </p>
    </div>
  );
}
