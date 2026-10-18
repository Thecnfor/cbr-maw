import type { DecisionCard, Evidence, RiskDriver, RiskSignal, TraceEvent } from "@/lib/types";
import { evidenceKindMeta } from "@/lib/labels";
import { toNumber } from "@/lib/format";

export function decisionEvidence(decision: DecisionCard): Evidence[] {
  return decision.evidence ?? [];
}

/** 决策卡引用但黑板未暴露的 evidence_id（Streamlit 会单独提示，不视为界面错误）。 */
export function collectMissingEvidenceIds(decision: DecisionCard): string[] {
  const known = new Set(decisionEvidence(decision).map((item) => item.evidence_id));
  const referenced = new Set<string>();

  const add = (ids: string[] | undefined) => {
    for (const id of ids ?? []) {
      if (id) referenced.add(id);
    }
  };

  if (decision.signal?.evidence_id) referenced.add(decision.signal.evidence_id);
  for (const card of Object.values(decision.cards ?? {})) {
    add(card.evidence_ids);
    for (const claim of card.claims ?? []) add(claim.evidence_ids);
    for (const metric of card.key_metrics ?? []) {
      if (metric.evidence_id) referenced.add(metric.evidence_id);
    }
  }
  for (const conflict of decision.conflicts ?? []) add(conflict.evidence_ids);

  return [...referenced].filter((id) => !known.has(id));
}

export function sortedDrivers(signal: RiskSignal | null | undefined, limit = 8): RiskDriver[] {
  const drivers = [...(signal?.drivers ?? [])].filter(
    (driver) => toNumber(driver.contribution) !== null,
  );
  drivers.sort(
    (left, right) =>
      Math.abs(toNumber(right.contribution) ?? 0) - Math.abs(toNumber(left.contribution) ?? 0),
  );
  return drivers.slice(0, limit);
}

export interface EvidenceKindCount {
  kind: string;
  label: string;
  count: number;
}

export function evidenceKindCounts(evidences: Evidence[]): EvidenceKindCount[] {
  const counts = new Map<string, number>();
  for (const item of evidences) {
    const key = item.kind || "unknown";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return [...counts.entries()]
    .map(([kind, count]) => ({ kind, label: evidenceKindMeta(kind).label, count }))
    .sort((left, right) => right.count - left.count);
}

export interface TraceSummary {
  events: number;
  toolCalls: number;
  latencyMs: number;
  tokens: number;
}

export function summarizeTrace(events: TraceEvent[]): TraceSummary {
  let toolCalls = 0;
  let latencyMs = 0;
  let tokens = 0;
  for (const event of events) {
    if (event.action === "tool_call") toolCalls += 1;
    latencyMs += toNumber(event.latency_ms) ?? 0;
    tokens += toNumber(event.tokens) ?? 0;
  }
  return { events: events.length, toolCalls, latencyMs, tokens };
}
