import type {
  Claim,
  ConflictSeverity,
  ConflictType,
  EvidenceKind,
  ExperimentMode,
  RiskLevel,
} from "@/lib/types";

export interface RiskMeta {
  label: string;
  tone: "success" | "warning" | "danger" | "critical" | "idle";
}

export const RISK_META: Record<RiskLevel, RiskMeta> = {
  low: { label: "低", tone: "success" },
  medium: { label: "中", tone: "warning" },
  high: { label: "高", tone: "danger" },
  critical: { label: "极高", tone: "critical" },
};

export const RISK_ORDER: RiskLevel[] = ["low", "medium", "high", "critical"];

export function riskMeta(level: string | null | undefined): RiskMeta {
  const key = String(level ?? "").toLowerCase() as RiskLevel;
  return RISK_META[key] ?? { label: level ? String(level) : "未知", tone: "idle" };
}

export interface RoleMeta {
  label: string;
  focus: string;
}

export const ROLE_META: Record<string, RoleMeta> = {
  regulator: { label: "监管主体", focus: "系统性风险 / 跨市场外溢" },
  investor: { label: "投资主体", focus: "组合尾部损失 / 对冲" },
  financing: { label: "融资主体", focus: "融资成本 / 现金流" },
  coordinator: { label: "协调者", focus: "冲突仲裁 / 决策卡" },
  verifier: { label: "核验者", focus: "数值 / 引文 / 时点核验" },
};

export const ROLE_ORDER = ["regulator", "investor", "financing"] as const;

export function roleMeta(role: string | null | undefined): RoleMeta {
  return ROLE_META[String(role ?? "")] ?? { label: role ? String(role) : "未知主体", focus: "" };
}

export const MODE_META: Record<ExperimentMode, { label: string; short: string }> = {
  collaborative: { label: "协同模式", short: "协同" },
  independent: { label: "独立模式", short: "独立" },
  single: { label: "单智能体模式", short: "单智能体" },
};

export const MODE_OPTIONS: ExperimentMode[] = ["collaborative", "independent", "single"];

export function modeMeta(mode: string | null | undefined): { label: string; short: string } {
  const key = String(mode ?? "") as ExperimentMode;
  return MODE_META[key] ?? { label: mode ? String(mode) : "—", short: mode ? String(mode) : "—" };
}

export const EVIDENCE_KIND_META: Record<
  EvidenceKind | "unknown",
  { label: string; short: string }
> = {
  signal: { label: "风险信号", short: "信号" },
  tool: { label: "工具输出", short: "工具" },
  kb: { label: "知识库", short: "知识库" },
  market: { label: "行情快照", short: "行情" },
  policy: { label: "政策文本", short: "政策" },
  unknown: { label: "其他证据", short: "其他" },
};

export function evidenceKindMeta(kind: string | null | undefined): { label: string; short: string } {
  const key = String(kind ?? "unknown") as EvidenceKind | "unknown";
  return EVIDENCE_KIND_META[key] ?? EVIDENCE_KIND_META.unknown;
}

export const CLAIM_STATUS_META: Record<string, string> = {
  unverified: "待核验",
  verified: "已核验",
  conflicted: "有冲突",
  rejected: "已驳回",
  preference: "偏好保留",
};

export function claimStatusLabel(status: string | null | undefined): string {
  return CLAIM_STATUS_META[String(status ?? "")] ?? String(status ?? "—");
}

export const CLAIM_TYPE_META: Record<string, string> = {
  numeric: "数值",
  text: "文本",
  directional: "方向",
};

export function claimTypeLabel(type: string | null | undefined): string {
  return CLAIM_TYPE_META[String(type ?? "")] ?? String(type ?? "—");
}

export const CONFLICT_TYPE_META: Record<ConflictType, string> = {
  fact: "事实冲突",
  directional: "方向冲突",
  preference: "偏好差异",
};

export function conflictTypeLabel(type: string | null | undefined): string {
  return (
    CONFLICT_TYPE_META[String(type ?? "") as ConflictType] ?? String(type ?? "未知冲突")
  );
}

export const SEVERITY_META: Record<ConflictSeverity | "info" | "warning" | "error", string> = {
  low: "低",
  medium: "中",
  high: "高",
  info: "提示",
  warning: "警告",
  error: "错误",
};

export function severityLabel(severity: string | null | undefined): string {
  const key = String(severity ?? "");
  return SEVERITY_META[key as keyof typeof SEVERITY_META] ?? key ?? "—";
}

export const RESOLVED_BY_META: Record<string, string> = {
  tool: "工具复核",
  authority: "权威裁定",
  human: "人工介入",
  consensus: "共识收敛",
  unresolved: "未解决",
};

export function resolvedByLabel(value: string | null | undefined): string {
  return RESOLVED_BY_META[String(value ?? "")] ?? String(value ?? "—");
}

export const ISSUE_TYPE_META: Record<string, string> = {
  numeric: "数值核验",
  citation: "引文核验",
  leakage: "时点泄漏",
  permission: "越权调用",
  schema: "Schema 校验",
  unsupported: "无依据断言",
};

export function issueTypeLabel(type: string | null | undefined): string {
  return ISSUE_TYPE_META[String(type ?? "")] ?? String(type ?? "—");
}

export const ACTION_META: Record<string, string> = {
  run_start: "运行开始",
  analysis_start: "开始分析",
  analysis_done: "分析完成",
  signal: "读取信号",
  tool_call: "工具调用",
  llm_call: "LLM 调用",
  kb_search: "知识库检索",
  claim: "形成主张",
  conflict: "冲突检测",
  conflict_detection: "分歧识别",
  conflict_resolved: "冲突已解决",
  conflict_resolution: "冲突协调",
  coordination_round: "协调轮次",
  evidence_share: "证据共享",
  evidence_share_summary: "证据共享完成",
  evidence_dedup: "证据去重",
  cross_check: "交叉验证",
  cross_check_summary: "交叉验证完成",
  cross_validate: "交叉验证",
  verify: "核验",
  hitl: "人工介入",
  finalize: "决策卡定稿",
  agent_error: "智能体异常",
  budget_exceeded: "预算超限",
};

export function actionLabel(action: string | null | undefined): string {
  return ACTION_META[String(action ?? "")] ?? String(action ?? "—");
}

export const PIT_META: Record<string, string> = {
  strict: "严格可得",
  approximate: "近似可得",
  unavailable: "不可得",
};

export function pitLabel(grade: string | null | undefined): string {
  return PIT_META[String(grade ?? "")] ?? String(grade ?? "—");
}

export const FREQUENCY_META: Record<string, string> = {
  daily: "日频",
  weekly: "周频",
  monthly: "月频",
  event: "事件",
  text: "文本",
};

export function frequencyLabel(value: string | null | undefined): string {
  return FREQUENCY_META[String(value ?? "")] ?? String(value ?? "—");
}

export function averageConfidence(claims: Claim[] | undefined): number | null {
  const values = (claims ?? [])
    .map((claim) => claim.confidence)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (!values.length) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}
