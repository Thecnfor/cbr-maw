import { sortedDrivers } from "@/lib/decision-utils";
import { riskMeta, ROLE_ORDER, roleMeta } from "@/lib/labels";
import type { DecisionCard } from "@/lib/types";

export interface FollowUp {
  id: string;
  label: string;
  prompt: string;
}

/**
 * 由当前 DecisionCard **确定性**生成追问建议：只使用已有字段（驱动因子、冲突、证据、
 * 三主体等级），不引入任何模型编造的问题或数值。无决策卡时返回空数组。
 */
export function buildFollowUps(decision: DecisionCard | null | undefined): FollowUp[] {
  if (!decision) return [];
  const suggestions: FollowUp[] = [];

  const driver = sortedDrivers(decision.signal, 1)[0];
  if (driver) {
    const direction = driver.direction === "down" ? "缓解" : "推高";
    suggestions.push({
      id: "driver",
      label: `驱动因子：${driver.factor}`,
      prompt: `请解释驱动因子「${driver.factor}」为什么${direction}当前风险，它的时点可得性如何，并列出支撑它的关键证据。`,
    });
  }

  const unresolved = (decision.conflicts ?? []).find((conflict) => !conflict.resolved);
  const anyConflict = unresolved ?? (decision.conflicts ?? [])[0];
  if (anyConflict) {
    suggestions.push({
      id: "conflict",
      label: unresolved
        ? `未解决分歧：${anyConflict.subject || anyConflict.conflict_id}`
        : `协调结果：${anyConflict.subject || anyConflict.conflict_id}`,
      prompt: `请协调者复核分歧「${anyConflict.subject || anyConflict.conflict_id}」（${anyConflict.conflict_id}）：双方主张分别是什么、当前解决状态如何、还需要哪些证据才能收敛？`,
    });
  }

  const evidences = decision.evidence ?? [];
  if (evidences.length) {
    const titles = evidences
      .slice(0, 3)
      .map((item) => `「${item.title || item.evidence_id}」`)
      .join("、");
    suggestions.push({
      id: "evidence",
      label: `关键证据（${evidences.length} 条）`,
      prompt: `本次判断最关键的证据有哪些？请优先解释 ${titles} 的含义、来源可靠性与它们对结论的影响。`,
    });
  }

  const roles = ROLE_ORDER.filter((role) => decision.cards?.[role]);
  const levels = new Set(roles.map((role) => decision.cards[role]?.risk_level));
  if (levels.size > 1) {
    const summary = roles
      .map((role) => `${roleMeta(role).label}「${riskMeta(decision.cards[role]?.risk_level).label}」`)
      .join("、");
    suggestions.push({
      id: "divergence",
      label: "为什么三主体判断不同",
      prompt: `三主体本次判断为 ${summary}。请解释差异来源（数据口径、工具、偏好还是时点），以及协调者最终如何取舍。`,
    });
  } else if (decision.scenario) {
    suggestions.push({
      id: "scenario",
      label: "情景冲击",
      prompt: `在「${decision.scenario}」情景下，如果压力在未来 5 日延续，最需要关注的传导路径与缓解因素是什么？`,
    });
  }

  return suggestions.slice(0, 4);
}
