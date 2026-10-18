import { useId, useState } from "react";
import {
  ChevronDown,
  FileText,
  Landmark,
  ShieldCheck,
  TrendingUp,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { EmptyState } from "@/components/common/empty-state";
import { MicroLabel } from "@/components/common/detail-row";
import { Meter } from "@/components/common/meter";
import { Panel } from "@/components/common/panel";
import { RiskBadge } from "@/components/common/risk-badge";
import { Badge } from "@/components/ui/badge";
import {
  fmtDuration,
  fmtMetricValue,
  fmtPct,
  fmtTokens,
  truncateMiddle,
} from "@/lib/format";
import {
  averageConfidence,
  claimStatusLabel,
  claimTypeLabel,
  roleMeta,
  ROLE_ORDER,
} from "@/lib/labels";
import type { Claim, DecisionCard, RiskCard } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROLE_ICONS: Record<string, LucideIcon> = {
  regulator: ShieldCheck,
  investor: TrendingUp,
  financing: Landmark,
};

function claimStatusVariant(
  status: string,
): "success" | "destructive" | "info" | "muted" | "warning" {
  if (status === "verified") return "success";
  if (status === "conflicted" || status === "rejected") return "destructive";
  if (status === "preference") return "info";
  if (status === "unverified") return "warning";
  return "muted";
}

function ClaimRow({
  claim,
  onOpenEvidence,
}: {
  claim: Claim;
  onOpenEvidence: (id: string) => void;
}) {
  const evidenceIds = claim.evidence_ids ?? [];
  return (
    <li className="py-2 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline" className="px-1.5 py-0 text-tiny">
          {claimTypeLabel(claim.claim_type)}
        </Badge>
        <span className="min-w-0 flex-1 truncate text-caption font-medium text-foreground">
          {claim.subject || "—"}
        </span>
        <Badge variant={claimStatusVariant(claim.status)} className="text-tiny">
          {claimStatusLabel(claim.status)}
        </Badge>
      </div>
      <p className="mt-1 text-caption leading-relaxed text-foreground/80">{claim.text}</p>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        {evidenceIds.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onOpenEvidence(id)}
            title={`查看证据 ${id}`}
            className="inline-flex max-w-full items-center gap-1 rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-tiny text-muted-foreground transition-colors duration-150 hover:border-foreground/30 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <FileText className="size-2.5 shrink-0" aria-hidden="true" />
            <span className="truncate">{truncateMiddle(id, 14, 6)}</span>
          </button>
        ))}
        {typeof claim.confidence === "number" ? (
          <span className="metric-value text-tiny text-muted-foreground">
            置信度 {fmtPct(claim.confidence)}
          </span>
        ) : null}
      </div>
    </li>
  );
}

function AgentCardView({
  card,
  onOpenEvidence,
}: {
  card: RiskCard;
  onOpenEvidence: (id: string) => void;
}) {
  const meta = roleMeta(card.role);
  const Icon = ROLE_ICONS[card.role] ?? Users;
  const claims = card.claims ?? [];
  const metrics = (card.key_metrics ?? []).slice(0, 4);
  const limitations = (card.limitations ?? []).filter(Boolean);
  const confidence = averageConfidence(claims);
  const evidenceIds = new Set<string>();
  for (const id of card.evidence_ids ?? []) evidenceIds.add(id);
  for (const claim of claims) {
    for (const id of claim.evidence_ids ?? []) evidenceIds.add(id);
  }

  const [expanded, setExpanded] = useState(false);
  const [fullRecommendation, setFullRecommendation] = useState(false);
  const panelId = useId();
  const recommendation = card.recommendation || "—";
  const canExpandRecommendation = recommendation.length > 96;

  return (
    <div className="rounded-lg border border-border bg-surface-2 p-3.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <span className="grid size-7 shrink-0 place-items-center rounded-md border border-border bg-surface-1 text-foreground">
            <Icon className="size-3.5" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-body font-semibold text-foreground">{meta.label}</span>
              <RiskBadge level={card.risk_level} />
            </div>
            {meta.focus ? (
              <p className="mt-0.5 text-tiny text-muted-foreground">{meta.focus}</p>
            ) : null}
          </div>
        </div>
        <Badge variant="outline" className="text-tiny">
          R{card.round ?? 0}
        </Badge>
      </div>

      <p className="mt-2.5 text-body font-medium leading-snug text-foreground">
        {card.headline || "未提供核心结论"}
      </p>

      {metrics.length ? (
        <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
          {metrics.map((metric) => (
            <div key={metric.name} className="min-w-0">
              <div
                className="truncate text-tiny text-muted-foreground"
                title={metric.label || metric.name}
              >
                {metric.label || metric.name}
              </div>
              <div className="metric-value truncate text-caption font-medium text-foreground">
                {fmtMetricValue(metric.value, metric.unit)}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      <div className="mt-2.5">
        <MicroLabel>建议</MicroLabel>
        <p
          className={cn(
            "mt-0.5 text-caption leading-relaxed text-foreground/80",
            !fullRecommendation && canExpandRecommendation && "line-clamp-3",
          )}
        >
          {recommendation}
        </p>
        {canExpandRecommendation ? (
          <button
            type="button"
            onClick={() => setFullRecommendation((value) => !value)}
            aria-expanded={fullRecommendation}
            className="mt-0.5 text-caption text-muted-foreground underline-offset-2 transition-colors duration-150 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {fullRecommendation ? "收起" : "展开建议"}
          </button>
        ) : null}
      </div>

      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-2 text-caption text-muted-foreground">
        <span className="min-w-0 truncate">
          工具 {card.tool_calls ?? 0} · {fmtTokens(card.tokens)} tokens ·{" "}
          {fmtDuration(card.latency_ms ?? 0)}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          <span>置信度</span>
          <Meter
            value={confidence === null ? null : confidence * 100}
            tone="neutral"
            label="主张平均置信度"
            className="w-14"
          />
          <span className="metric-value text-foreground">{fmtPct(confidence)}</span>
        </span>
      </div>

      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls={panelId}
        className="mt-1.5 inline-flex h-7 items-center gap-1 rounded-md px-1.5 text-caption text-muted-foreground transition-colors duration-150 hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ChevronDown
          className={cn("size-3.5 transition-transform duration-150", expanded && "rotate-180")}
          aria-hidden="true"
        />
        主张 {claims.length} · 证据 {evidenceIds.size}
      </button>

      {expanded ? (
        <div
          id={panelId}
          className="mt-1.5 rounded-lg border border-border bg-surface-1 p-2.5"
        >
          {claims.length ? (
            <ul className="divide-y divide-border">
              {claims.map((claim) => (
                <ClaimRow
                  key={claim.claim_id}
                  claim={claim}
                  onOpenEvidence={onOpenEvidence}
                />
              ))}
            </ul>
          ) : (
            <p className="text-caption text-muted-foreground">
              未提供结构化主张（claims 为空）。
            </p>
          )}

          {limitations.length ? (
            <div className="mt-2 border-t border-border pt-2">
              <MicroLabel>局限说明（{limitations.length}）</MicroLabel>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-caption leading-relaxed text-foreground/80 marker:text-muted-foreground">
                {limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function AgentCards({
  decision,
  onOpenEvidence,
}: {
  decision: DecisionCard;
  onOpenEvidence: (id: string) => void;
}) {
  const cards = decision.cards ?? {};
  const orderedRoles = [
    ...ROLE_ORDER.filter((role) => cards[role]),
    ...Object.keys(cards).filter((role) => !(ROLE_ORDER as readonly string[]).includes(role)),
  ];

  return (
    <Panel
      title="三智能体风险卡"
      icon={<Users />}
      meta={
        <span className="text-caption text-muted-foreground">
          监管 / 投资 / 融资 · {orderedRoles.length} 张
        </span>
      }
      bodyClassName="space-y-3 p-4"
    >
      {orderedRoles.length === 0 ? (
        <EmptyState
          title="决策卡未包含三智能体结果"
          description="cards 为空：可能处于单智能体模式，或编排层尚未产出三主体卡片。"
        />
      ) : (
        orderedRoles.map((role) => (
          <AgentCardView
            key={role}
            card={cards[role]}
            onOpenEvidence={onOpenEvidence}
          />
        ))
      )}
    </Panel>
  );
}
