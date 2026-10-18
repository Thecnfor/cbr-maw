import { AlertTriangle, Scale } from "lucide-react";

import { Callout } from "@/components/common/callout";
import { MicroLabel } from "@/components/common/detail-row";
import { Stat } from "@/components/common/stat";
import { Badge } from "@/components/ui/badge";
import {
  conflictTypeLabel,
  resolvedByLabel,
  roleMeta,
  severityLabel,
} from "@/lib/labels";
import type { Conflict } from "@/lib/types";
import { cn } from "@/lib/utils";

function severityWeight(severity: string | undefined): number {
  if (severity === "high") return 3;
  if (severity === "medium") return 2;
  return 1;
}

function typeVariant(type: string): "destructive" | "warning" | "info" {
  if (type === "fact") return "destructive";
  if (type === "directional") return "warning";
  return "info";
}

function severityVariant(severity: string | undefined): "destructive" | "warning" | "muted" {
  if (severity === "high") return "destructive";
  if (severity === "medium") return "warning";
  return "muted";
}

export function ConflictsPanel({ conflicts }: { conflicts: Conflict[] }) {
  const resolved = conflicts.filter((conflict) => conflict.resolved);
  const unresolved = conflicts.length - resolved.length;

  const ordered = [...conflicts].sort((left, right) => {
    const byResolved = Number(Boolean(left.resolved)) - Number(Boolean(right.resolved));
    if (byResolved !== 0) return byResolved;
    return severityWeight(right.severity) - severityWeight(left.severity);
  });

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat label="冲突总数" value={conflicts.length} valueClassName="text-desc" />
        </div>
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat
            label="已解决"
            value={resolved.length}
            valueClassName="text-desc text-success-ink"
          />
        </div>
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat
            label="未解决"
            value={unresolved}
            valueClassName={cn("text-desc", unresolved ? "text-destructive-ink" : "text-foreground")}
          />
        </div>
      </div>

      {conflicts.length === 0 ? (
        <Callout tone="success" title="本轮未检测到智能体间冲突">
          三类主体的结论与证据保持一致，无需协调；偏好差异也会在此面板如实保留，不判为错误。
        </Callout>
      ) : (
        <ul className="space-y-2.5">
          {ordered.map((conflict) => (
            <li
              key={conflict.conflict_id}
              className="rounded-lg border border-border bg-surface-2 p-3"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex min-w-0 items-start gap-1.5">
                  <Scale
                    className="mt-0.5 size-3.5 shrink-0 text-muted-foreground"
                    aria-hidden="true"
                  />
                  <div className="min-w-0">
                    <h3 className="truncate text-body font-semibold text-foreground">
                      {conflict.subject || "未命名冲突"}
                    </h3>
                    <div className="metric-value text-tiny text-muted-foreground">
                      {conflict.conflict_id}
                    </div>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1">
                  <Badge variant={typeVariant(conflict.type)}>
                    {conflictTypeLabel(conflict.type)}
                  </Badge>
                  <Badge variant={severityVariant(conflict.severity)}>
                    严重度 {severityLabel(conflict.severity)}
                  </Badge>
                  <Badge variant={conflict.resolved ? "success" : "critical"}>
                    {conflict.resolved ? "已解决" : "未解决"}
                  </Badge>
                </div>
              </div>

              <p className="mt-1.5 text-caption leading-relaxed text-foreground/80">
                {conflict.description || "—"}
              </p>

              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-tiny text-muted-foreground">
                <span>
                  涉及主体：
                  {(conflict.roles ?? []).map((role) => roleMeta(role).label).join("、") || "—"}
                </span>
                <span>关联主张 {conflict.claim_ids?.length ?? 0}</span>
                <span>引用证据 {conflict.evidence_ids?.length ?? 0}</span>
              </div>

              {conflict.resolved ? (
                <div className="mt-2 rounded-md border border-border bg-surface-1 p-2">
                  <MicroLabel>
                    协调结果（{resolvedByLabel(conflict.resolved_by)}）
                  </MicroLabel>
                  <p className="mt-0.5 text-caption leading-relaxed text-foreground/85">
                    {conflict.resolution || "—"}
                  </p>
                </div>
              ) : (
                <Callout
                  tone="warning"
                  title="尚未收敛"
                  icon={<AlertTriangle className="size-3.5" />}
                  className="mt-2 px-2 py-1.5"
                >
                  该冲突可能升级至人工介入（HITL）；在人工裁定前不应作为已确认结论使用。
                </Callout>
              )}
            </li>
          ))}
        </ul>
      )}

    </div>
  );
}
