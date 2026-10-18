import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

import { Callout } from "@/components/common/callout";
import { MicroLabel } from "@/components/common/detail-row";
import { Meter } from "@/components/common/meter";
import { Stat } from "@/components/common/stat";
import { Badge } from "@/components/ui/badge";
import { TracePanel } from "@/components/dashboard/trace-panel";
import { fmtPct, toNumber } from "@/lib/format";
import { issueTypeLabel, roleMeta, severityLabel } from "@/lib/labels";
import type { TraceResource } from "@/lib/resources";
import type { DecisionCard } from "@/lib/types";
import { cn } from "@/lib/utils";

function rateClass(rate: number | null): string {
  if (rate === null) return "text-muted-foreground";
  if (rate >= 100) return "text-success-ink";
  if (rate >= 95) return "text-warning-ink";
  return "text-destructive-ink";
}

function countClass(count: number): string {
  return count > 0 ? "text-destructive-ink" : "text-foreground";
}

function severityVariant(severity: string | undefined): "info" | "warning" | "destructive" {
  if (severity === "error") return "destructive";
  if (severity === "info") return "info";
  return "warning";
}

export function VerificationPanel({
  decision,
  trace,
}: {
  decision: DecisionCard;
  trace: TraceResource;
}) {
  const report = decision.verification ?? {};
  const issues = report.issues ?? [];

  const numericTotal = toNumber(report.numeric_checks_total) ?? 0;
  const numericPassed = toNumber(report.numeric_checks_passed) ?? 0;
  const citationTotal = toNumber(report.citation_checks_total) ?? 0;
  const citationPassed = toNumber(report.citation_checks_passed) ?? 0;

  const numericRate = numericTotal > 0 ? (numericPassed / numericTotal) * 100 : null;
  const citationRate = citationTotal > 0 ? (citationPassed / citationTotal) * 100 : null;
  const evidenceAccuracy =
    report.evidence_accuracy === undefined ? null : (toNumber(report.evidence_accuracy) ?? 0) * 100;
  const unsupportedRate =
    report.unsupported_claim_rate === undefined
      ? null
      : (toNumber(report.unsupported_claim_rate) ?? 0) * 100;
  const permissionViolations = toNumber(report.permission_violations) ?? 0;
  const leakageEvents = toNumber(report.leakage_events) ?? 0;
  const schemaErrors = toNumber(report.schema_errors) ?? 0;

  return (
    <div className="space-y-3">
      {report.passed === true ? (
        <Callout
          tone="success"
          title="核验通过"
          icon={<CheckCircle2 className="size-4" />}
        >
          数值、引文、时点、权限与 Schema 检查均无异常；结论可作为本次运行的复核依据。
        </Callout>
      ) : report.passed === false ? (
        <Callout
          tone="danger"
          title="核验存在异常项"
          icon={<AlertTriangle className="size-4" />}
        >
          详见下方问题列表（数值 / 引文 / 时点 / 越权 / Schema），异常项不应被忽略。
        </Callout>
      ) : (
        <Callout tone="info" title="核验报告缺失" icon={<Info className="size-4" />}>
          VerificationReport 未提供，核验指标显示为「—」。
        </Callout>
      )}

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat
            label="数值核验通过率"
            value={numericRate === null ? "—" : fmtPct(numericRate / 100)}
            hint={`${numericPassed} / ${numericTotal} 通过`}
            valueClassName={rateClass(numericRate)}
          />
        </div>
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat
            label="证据准确率"
            value={evidenceAccuracy === null ? "—" : fmtPct(evidenceAccuracy / 100)}
            hint={`${citationPassed} / ${citationTotal} 引文通过`}
            valueClassName={rateClass(evidenceAccuracy)}
          />
        </div>
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat
            label="无依据断言率"
            value={unsupportedRate === null ? "—" : fmtPct(unsupportedRate / 100)}
            hint={`${report.unsupported_claims ?? 0} 条无依据断言`}
            valueClassName={cn(
              unsupportedRate !== null && unsupportedRate > 0
                ? "text-warning-ink"
                : "text-foreground",
            )}
          />
        </div>
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat
            label="越权拦截"
            value={permissionViolations}
            hint="权限矩阵阻断次数"
            valueClassName={countClass(permissionViolations)}
          />
        </div>
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat
            label="时点泄漏"
            value={leakageEvents}
            hint="as_of 之后信息"
            valueClassName={countClass(leakageEvents)}
          />
        </div>
        <div className="rounded-lg border border-border bg-surface-2 px-2.5 py-2">
          <Stat
            label="Schema 错误"
            value={schemaErrors}
            hint="契约校验失败"
            valueClassName={countClass(schemaErrors)}
          />
        </div>
      </div>

      <div className="space-y-2">
        <div>
          <div className="flex items-center justify-between text-caption">
            <span className="text-muted-foreground">数值核验</span>
            <span className="metric-value text-foreground">
              {numericPassed} / {numericTotal}
            </span>
          </div>
          <Meter
            value={numericRate}
            tone={numericRate === null ? "neutral" : numericRate >= 100 ? "success" : "warning"}
            label="数值核验通过率"
            className="mt-1"
          />
        </div>
        <div>
          <div className="flex items-center justify-between text-caption">
            <span className="text-muted-foreground">引文核验</span>
            <span className="metric-value text-foreground">
              {citationPassed} / {citationTotal}
            </span>
          </div>
          <Meter
            value={citationRate}
            tone={citationRate === null ? "neutral" : citationRate >= 100 ? "success" : "warning"}
            label="引文核验通过率"
            className="mt-1"
          />
        </div>
      </div>

      {issues.length ? (
        <div>
          <MicroLabel>核验问题（{issues.length}）</MicroLabel>
          <ul className="mt-1 divide-y divide-border rounded-lg border border-border bg-surface-2 px-2.5">
            {issues.map((issue, index) => (
              <li key={`${issue.detail}-${index}`} className="py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge variant="outline" className="text-tiny">
                    {issueTypeLabel(issue.issue_type)}
                  </Badge>
                  {issue.role ? (
                    <span className="text-tiny text-muted-foreground">
                      {roleMeta(issue.role).label}
                    </span>
                  ) : null}
                  <Badge variant={severityVariant(issue.severity)} className="ml-auto text-tiny">
                    {severityLabel(issue.severity)}
                  </Badge>
                </div>
                <p className="mt-1 text-caption leading-relaxed text-foreground/80">
                  {issue.detail}
                </p>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-caption text-muted-foreground">未报告核验问题（issues 为空）。</p>
      )}

      <TracePanel runId={decision.run_id} traceRef={decision.trace_ref} trace={trace} />
    </div>
  );
}
