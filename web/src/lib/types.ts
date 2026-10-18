/**
 * CBR-MAW 前端契约类型。
 *
 * 与 `src/cbr/schemas.py` 一一对应；字段可选性遵循后端 pydantic 默认值，
 * 组件在使用前仍需对空数组 / 空对象做降级处理。
 */

export type RiskLevel = "low" | "medium" | "high" | "critical";
export type ExperimentMode = "collaborative" | "independent" | "single";
export type EvidenceKind = "signal" | "tool" | "kb" | "market" | "policy";
export type ConflictType = "fact" | "directional" | "preference";
export type ConflictSeverity = "low" | "medium" | "high";
export type ClaimStatus =
  | "unverified"
  | "verified"
  | "conflicted"
  | "rejected"
  | "preference";

export interface Scenario {
  scenario_id: string;
  name: string;
  as_of: string;
  description?: string;
  tags?: string[];
}

export interface ReadinessModule {
  module?: string;
  factory?: string;
  ready?: boolean;
  detail?: string;
}

export interface HealthLlm {
  provider?: string | null;
  model?: string | null;
  mock?: boolean | null;
  client?: string | null;
}

export interface HealthDataSources {
  ready?: boolean;
  provider?: string | null;
  data_cards?: number | null;
  orchestrator?: string | null;
  error?: string | null;
}

export interface Health {
  status: string;
  app?: string;
  version?: string;
  service_ready?: boolean;
  service_error?: string | null;
  core_ready?: boolean;
  ready_modules?: string[];
  pending_modules?: string[];
  modules?: ReadinessModule[];
  llm?: HealthLlm;
  data_sources?: HealthDataSources;
  scenarios?: number;
  server?: Record<string, unknown>;
  timestamp?: string;
}

export interface RiskDriver {
  factor: string;
  contribution: number;
  direction?: "up" | "down";
  description?: string;
}

export interface RiskSignal {
  as_of: string;
  model_version: string;
  horizons: Record<string, number>;
  percentile?: number | null;
  level: RiskLevel;
  drivers?: RiskDriver[];
  modality_contrib?: Record<string, number>;
  label_version?: string;
  evidence_id?: string | null;
}

export interface SourceRef {
  name: string;
  url?: string | null;
  doc_id?: string | null;
  chunk_id?: string | null;
  release_time?: string | null;
  extra?: Record<string, unknown>;
}

export interface ToolRef {
  name: string;
  version: string;
  inputs_hash?: string | null;
  elapsed_ms?: number;
}

export interface Evidence {
  evidence_id: string;
  kind: EvidenceKind;
  as_of: string;
  title: string;
  summary?: string;
  payload?: Record<string, unknown>;
  unit?: string | null;
  value?: number | null;
  source?: SourceRef;
  tool?: ToolRef | null;
  produced_by?: string;
  citations?: SourceRef[];
  verified?: boolean | null;
  created_at?: string;
  hash?: string | null;
}

export interface MetricItem {
  name: string;
  label?: string;
  value?: number | string | null;
  unit?: string | null;
  evidence_id?: string | null;
  description?: string;
}

export interface Claim {
  claim_id: string;
  role: string;
  claim_type: "numeric" | "text" | "directional" | string;
  subject: string;
  text: string;
  value?: number | null;
  unit?: string | null;
  direction?: "up" | "down" | "flat" | "none" | null;
  evidence_ids?: string[];
  confidence?: number | null;
  status: ClaimStatus | string;
}

export interface RiskCard {
  role: string;
  as_of: string;
  risk_level: RiskLevel;
  headline: string;
  base_signal_ref?: string | null;
  key_metrics?: MetricItem[];
  claims?: Claim[];
  recommendation?: string;
  decision_loss?: Record<string, number>;
  limitations?: string[];
  evidence_ids?: string[];
  tool_calls?: number;
  tokens?: number;
  latency_ms?: number;
  round?: number;
}

export interface Conflict {
  conflict_id: string;
  subject: string;
  claim_ids?: string[];
  roles?: string[];
  type: ConflictType;
  description: string;
  severity?: ConflictSeverity;
  resolved?: boolean;
  resolution?: string;
  resolved_by?: "tool" | "authority" | "human" | "consensus" | "unresolved" | null;
  evidence_ids?: string[];
}

export interface VerificationIssue {
  issue_type:
    | "numeric"
    | "citation"
    | "leakage"
    | "permission"
    | "schema"
    | "unsupported"
    | string;
  role?: string | null;
  claim_id?: string | null;
  detail: string;
  severity?: "info" | "warning" | "error";
}

export interface VerificationReport {
  run_id?: string;
  numeric_checks_total?: number;
  numeric_checks_passed?: number;
  numeric_error_rate?: number;
  citation_checks_total?: number;
  citation_checks_passed?: number;
  evidence_accuracy?: number;
  unsupported_claims?: number;
  unsupported_claim_rate?: number;
  permission_violations?: number;
  leakage_events?: number;
  schema_errors?: number;
  issues?: VerificationIssue[];
  passed?: boolean;
}

export interface CoordinationStats {
  rounds?: number;
  evidence_shared?: number;
  duplicate_evidence?: number;
  conflicts_total?: number;
  conflicts_resolved?: number;
  conflicts_escalated?: number;
  tool_calls?: number;
  tokens?: number;
  latency_ms?: number;
  cost_usd?: number;
}

export interface DecisionCard {
  run_id: string;
  as_of: string;
  scenario?: string | null;
  mode: ExperimentMode;
  signal: RiskSignal;
  cards: Record<string, RiskCard>;
  evidence?: Evidence[];
  conflicts?: Conflict[];
  verification?: VerificationReport;
  coordination?: CoordinationStats;
  final_advice?: string;
  trace_ref?: string | null;
  created_at?: string;
}

export interface DataCard {
  series_id: string;
  name: string;
  source: string;
  frequency?: string;
  coverage_start?: string | null;
  coverage_end?: string | null;
  release_lag_days?: number;
  pit_grade?: "strict" | "approximate" | "unavailable" | string;
  unit?: string | null;
  notes?: string;
}

export interface TraceEvent {
  run_id: string;
  ts: string;
  step?: string;
  role?: string | null;
  action?: string;
  tool?: string | null;
  args_hash?: string | null;
  result_hash?: string | null;
  detail?: Record<string, unknown>;
  latency_ms?: number;
  tokens?: number;
}

export interface ChatRequest {
  message: string;
  as_of?: string | null;
  session_id?: string | null;
  mode?: ExperimentMode;
}

export interface ChatResponse {
  reply: string;
  as_of?: string | null;
  decision?: DecisionCard | null;
  citations?: SourceRef[];
  trace_id?: string | null;
}

export type ChatTurnStatus = "ok" | "error" | "stopped";

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: SourceRef[];
  decision: DecisionCard | null;
  traceId: string | null;
  asOf: string | null;
  status: ChatTurnStatus;
  createdAt: number;
}
