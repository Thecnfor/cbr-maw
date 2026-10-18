import { Badge } from "@/components/ui/badge";
import { riskMeta } from "@/lib/labels";
import { cn } from "@/lib/utils";

const VARIANT_BY_TONE = {
  success: "success",
  warning: "warning",
  danger: "destructive",
  critical: "critical",
  idle: "muted",
} as const;

export function RiskBadge({
  level,
  className,
}: {
  level: string | null | undefined;
  className?: string;
}) {
  const meta = riskMeta(level);
  return (
    <Badge variant={VARIANT_BY_TONE[meta.tone]} className={className}>
      <span className="size-1.5 rounded-full bg-current" aria-hidden="true" />
      {meta.label}
    </Badge>
  );
}

export function RiskDot({ level, className }: { level: string | null | undefined; className?: string }) {
  const meta = riskMeta(level);
  const color =
    meta.tone === "success"
      ? "bg-success"
      : meta.tone === "warning"
        ? "bg-warning"
        : meta.tone === "critical" || meta.tone === "danger"
          ? "bg-destructive"
          : "bg-muted-foreground/40";
  return <span className={cn("inline-block size-2 shrink-0 rounded-full", color, className)} aria-hidden="true" />;
}

export function LevelText({ level, className }: { level: string | null | undefined; className?: string }) {
  const meta = riskMeta(level);
  const color =
    meta.tone === "success"
      ? "text-success-ink"
      : meta.tone === "warning"
        ? "text-warning-ink"
        : meta.tone === "critical" || meta.tone === "danger"
          ? "text-destructive-ink"
          : "text-muted-foreground";
  return <span className={cn("font-semibold", color, className)}>{meta.label}</span>;
}
