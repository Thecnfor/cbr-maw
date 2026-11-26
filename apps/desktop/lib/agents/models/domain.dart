/// 多智能体编排的领域模型（对齐 docs/03 §1.5–§1.8 与旧版 `cbr/schemas.py`）。
///
/// 这些类型是编排层内部契约；对应用外壳只暴露 [RunEvent] / [RunSummary]。
library;

/// 业务主体身份。
enum RoleId {
  regulator('regulator'),
  investor('investor'),
  financing('financing'),
  crossValidator('crossValidator');

  const RoleId(this.wire);

  /// JSON / 配置字面量。
  final String wire;

  /// 是否产出风险卡（交叉验证角色只复核，不出等级）。
  bool get producesCard => this != RoleId.crossValidator;

  /// 从字面量解析。
  static RoleId parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ArgumentError('未知角色：$raw');
  }
}

/// 风险等级（确定性判定，见 docs/03 §1.8）。
enum RiskLevel {
  low('low', 0),
  medium('medium', 1),
  high('high', 2),
  critical('critical', 3);

  const RiskLevel(this.wire, this.order);

  /// JSON 字面量。
  final String wire;

  /// 强度序（越大越强）。
  final int order;

  /// 取更强等级。
  static RiskLevel strongest(Iterable<RiskLevel> levels) => levels.isEmpty
      ? RiskLevel.low
      : levels.reduce((a, b) => a.order >= b.order ? a : b);

  /// 上调一级（封顶 critical）。
  RiskLevel escalate() => order >= RiskLevel.critical.order
      ? RiskLevel.critical
      : values[order + 1];

  /// 中文标签。
  String get label => switch (this) {
    RiskLevel.low => '低',
    RiskLevel.medium => '中',
    RiskLevel.high => '高',
    RiskLevel.critical => '极高',
  };

  /// 从字面量解析。
  static RiskLevel parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ArgumentError('未知风险等级：$raw');
  }
}

/// 证据种类。
enum EvidenceKind {
  signal('signal', 1),
  tool('tool', 3),
  kb('kb', 2),
  market('market', 1),
  policy('policy', 2);

  const EvidenceKind(this.wire, this.grade);

  /// JSON 字面量。
  final String wire;

  /// 证据权威等级（tool 3 > kb/policy 2 > signal/market 1）。
  final int grade;

  /// 从字面量解析。
  static EvidenceKind parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ArgumentError('未知证据种类：$raw');
  }
}

/// 主张类型。
enum ClaimType {
  numeric('numeric'),
  text('text'),
  directional('directional');

  const ClaimType(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从字面量解析。
  static ClaimType parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ArgumentError('未知主张类型：$raw');
  }
}

/// 主张状态。
enum ClaimStatus {
  unverified('unverified'),
  verified('verified'),
  conflicted('conflicted'),
  rejected('rejected'),
  preference('preference');

  const ClaimStatus(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 方向。
enum Direction {
  up('up'),
  down('down'),
  flat('flat'),
  none('none');

  const Direction(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从字面量解析；未知值回落 none。
  static Direction parseOrNone(Object? raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    return Direction.none;
  }
}

/// 冲突类型（偏好差异不是错误，见 docs/03 §1.3）。
enum ConflictType {
  fact('fact'),
  directional('directional'),
  preference('preference');

  const ConflictType(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 冲突严重度。
enum Severity {
  low('low'),
  medium('medium'),
  high('high');

  const Severity(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 仲裁结果来源（优先级：tool > authority > human > consensus > unresolved）。
enum ResolvedBy {
  tool('tool'),
  authority('authority'),
  human('human'),
  consensus('consensus'),
  unresolved('unresolved');

  const ResolvedBy(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 可回溯的来源定位符（不是「来源名」）。
final class SourceRef {
  /// 创建来源引用。
  const SourceRef({
    required this.name,
    this.url,
    this.docId,
    this.chunkId,
    this.releaseTime,
    this.extra = const {},
  });

  /// 来源名称。
  final String name;

  /// 链接。
  final String? url;

  /// 文档 ID。
  final String? docId;

  /// 分块 ID（KB 证据必填）。
  final String? chunkId;

  /// 发布时间（PIT 判定字段）。
  final DateTime? releaseTime;

  /// 扩展字段。
  final Map<String, Object?> extra;

  /// 回写 JSON。
  Map<String, Object?> toJson() => {
    'name': name,
    'url': url,
    'doc_id': docId,
    'chunk_id': chunkId,
    'release_time': releaseTime?.toIso8601String(),
    'extra': extra,
  };
}

/// 工具引用：版本化 → 可重算。
final class ToolRef {
  /// 创建工具引用。
  const ToolRef({
    required this.name,
    required this.version,
    this.inputsHash,
    this.elapsedMs = 0,
  });

  /// 工具名。
  final String name;

  /// 工具版本。
  final String version;

  /// 入参哈希。
  final String? inputsHash;

  /// 耗时。
  final int elapsedMs;

  /// 回写 JSON。
  Map<String, Object?> toJson() => {
    'name': name,
    'version': version,
    'inputs_hash': inputsHash,
    'elapsed_ms': elapsedMs,
  };
}

/// 黑板原子单位。
final class Evidence {
  /// 创建证据。
  const Evidence({
    required this.evidenceId,
    required this.kind,
    required this.asOf,
    required this.title,
    this.summary = '',
    this.payload = const {},
    this.unit,
    this.value,
    this.source = const SourceRef(name: 'unknown'),
    this.tool,
    this.producedBy = 'system',
    this.citations = const [],
    this.verified,
    required this.createdAt,
    required this.hash,
  });

  /// 证据 ID。
  final String evidenceId;

  /// 种类。
  final EvidenceKind kind;

  /// 证据时点（只取日期）。
  final DateTime asOf;

  /// 标题。
  final String title;

  /// 摘要。
  final String summary;

  /// 结构化载荷。
  final Map<String, Object?> payload;

  /// 单位。
  final String? unit;

  /// 主数值。
  final double? value;

  /// 来源。
  final SourceRef source;

  /// 工具引用（kind==tool 时非空）。
  final ToolRef? tool;

  /// 产出者（工具名 / 角色 id / coordinator）。
  final String producedBy;

  /// 原文片段回指。
  final List<SourceRef> citations;

  /// 是否已核验。
  final bool? verified;

  /// 创建时间。
  final DateTime createdAt;

  /// 载荷哈希。
  final String hash;

  /// 证据权威等级。
  int get grade => kind.grade;

  /// 复制并替换核验状态。
  Evidence withVerified(bool verified) => Evidence(
    evidenceId: evidenceId,
    kind: kind,
    asOf: asOf,
    title: title,
    summary: summary,
    payload: payload,
    unit: unit,
    value: value,
    source: source,
    tool: tool,
    producedBy: producedBy,
    citations: citations,
    verified: verified,
    createdAt: createdAt,
    hash: hash,
  );
}

/// 共享多模态风险信号（P1 融合输出）。
final class RiskSignal {
  /// 创建信号。
  const RiskSignal({
    required this.asOf,
    required this.modelVersion,
    this.horizons = const {},
    this.percentile,
    this.level = RiskLevel.low,
    this.drivers = const [],
    this.evidenceId,
  });

  /// 时点。
  final DateTime asOf;

  /// 模型版本。
  final String modelVersion;

  /// 各窗口压力概率。
  final Map<int, double> horizons;

  /// 历史分位。
  final double? percentile;

  /// 信号等级。
  final RiskLevel level;

  /// 驱动因子。
  final List<RiskDriver> drivers;

  /// 信号证据 id。
  final String? evidenceId;
}

/// 信号驱动因子。
final class RiskDriver {
  /// 创建驱动。
  const RiskDriver({
    required this.factor,
    required this.contribution,
    this.direction = Direction.up,
    this.description = '',
  });

  /// 因子名。
  final String factor;

  /// 贡献。
  final double contribution;

  /// 方向。
  final Direction direction;

  /// 说明。
  final String description;
}

/// 关键测度条目。
final class MetricItem {
  /// 创建测度。
  const MetricItem({
    required this.name,
    this.label = '',
    this.value,
    this.unit,
    this.evidenceId,
    this.description = '',
  });

  /// 指标名。
  final String name;

  /// 展示标签。
  final String label;

  /// 值（数值或文本）。
  final Object? value;

  /// 单位。
  final String? unit;

  /// 绑定证据。
  final String? evidenceId;

  /// 说明。
  final String description;
}

/// 主张（结论最小单位）。
final class Claim {
  /// 创建主张。
  const Claim({
    required this.claimId,
    required this.role,
    required this.claimType,
    required this.subject,
    required this.text,
    this.value,
    this.unit,
    this.direction,
    this.evidenceIds = const [],
    this.confidence,
    this.status = ClaimStatus.unverified,
  });

  /// 主张 ID。
  final String claimId;

  /// 所属角色。
  final RoleId role;

  /// 类型。
  final ClaimType claimType;

  /// 主题（未归一化）。
  final String subject;

  /// 文本。
  final String text;

  /// 数值（numeric）。
  final double? value;

  /// 单位。
  final String? unit;

  /// 方向（directional）。
  final Direction? direction;

  /// 绑定证据 ID（非空）。
  final List<String> evidenceIds;

  /// 置信度。
  final double? confidence;

  /// 状态。
  final ClaimStatus status;

  /// 复制并替换状态/证据。
  Claim copyWith({
    ClaimStatus? status,
    List<String>? evidenceIds,
    double? value,
    String? unit,
    String? text,
  }) => Claim(
    claimId: claimId,
    role: role,
    claimType: claimType,
    subject: subject,
    text: text ?? this.text,
    value: value ?? this.value,
    unit: unit ?? this.unit,
    direction: direction,
    evidenceIds: evidenceIds ?? this.evidenceIds,
    confidence: confidence,
    status: status ?? this.status,
  );
}

/// 单角色风险卡。
final class RiskCard {
  /// 创建风险卡。
  const RiskCard({
    required this.role,
    required this.asOf,
    required this.riskLevel,
    required this.headline,
    this.baseSignalRef,
    this.keyMetrics = const [],
    this.claims = const [],
    this.escalationEvidenceIds = const [],
    this.recommendation = '',
    this.decisionLoss = const {},
    this.limitations = const [],
    this.evidenceIds = const [],
    this.toolCalls = 0,
    this.tokens = 0,
    this.latencyMs = 0,
    this.round = 0,
  });

  /// 角色。
  final RoleId role;

  /// 时点。
  final DateTime asOf;

  /// 确定性风险等级。
  final RiskLevel riskLevel;

  /// 一句话标题。
  final String headline;

  /// 共享信号证据 ID。
  final String? baseSignalRef;

  /// 关键测度（≤8）。
  final List<MetricItem> keyMetrics;

  /// 主张（3–6）。
  final List<Claim> claims;

  /// 触发等级上调的证据 ID。
  final List<String> escalationEvidenceIds;

  /// 建议（与事实严格分离）。
  final String recommendation;

  /// 归一化期望损失分解（非金额）。
  final Map<String, double> decisionLoss;

  /// 局限（≤8，系统自动追加）。
  final List<String> limitations;

  /// 证据 ID。
  final List<String> evidenceIds;

  /// 工具调用次数。
  final int toolCalls;

  /// token 数。
  final int tokens;

  /// 延迟。
  final int latencyMs;

  /// 轮次。
  final int round;

  /// 复制并替换等级/主张。
  RiskCard copyWith({
    RiskLevel? riskLevel,
    List<Claim>? claims,
    List<String>? limitations,
    List<String>? escalationEvidenceIds,
  }) => RiskCard(
    role: role,
    asOf: asOf,
    riskLevel: riskLevel ?? this.riskLevel,
    headline: headline,
    baseSignalRef: baseSignalRef,
    keyMetrics: keyMetrics,
    claims: claims ?? this.claims,
    escalationEvidenceIds: escalationEvidenceIds ?? this.escalationEvidenceIds,
    recommendation: recommendation,
    decisionLoss: decisionLoss,
    limitations: limitations ?? this.limitations,
    evidenceIds: evidenceIds,
    toolCalls: toolCalls,
    tokens: tokens,
    latencyMs: latencyMs,
    round: round,
  );
}

/// 角色智能体运行状态。
enum AgentStatus {
  ok('ok'),
  failed('failed'),
  timeout('timeout'),
  budgetExceeded('budgetExceeded'),
  skipped('skipped');

  const AgentStatus(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 失败码。
enum FailureCode {
  llmTimeout('llmTimeout'),
  llmAuth('llmAuth'),
  llmInvalidOutput('llmInvalidOutput'),
  toolFailure('toolFailure'),
  contextOverflow('contextOverflow'),
  permissionDenied('permissionDenied'),
  budgetExceeded('budgetExceeded'),
  internal('internal');

  const FailureCode(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 角色失败描述。
final class AgentFailure {
  /// 创建失败描述。
  const AgentFailure({
    required this.code,
    required this.message,
    this.retryable = false,
    this.attempt = 1,
  });

  /// 失败码。
  final FailureCode code;

  /// 面向用户的中文说明。
  final String message;

  /// 是否可重试。
  final bool retryable;

  /// 尝试次数。
  final int attempt;
}

/// token 用量。
final class TokenUsage {
  /// 创建用量。
  const TokenUsage({this.prompt = 0, this.completion = 0, this.total = 0});

  /// prompt token。
  final int prompt;

  /// completion token。
  final int completion;

  /// 总 token。
  final int total;
}

/// 角色智能体输出。
final class AgentOutput {
  /// 创建输出。
  const AgentOutput({
    required this.role,
    required this.status,
    this.card,
    this.evidence = const [],
    this.toolCalls = 0,
    this.tokens = const TokenUsage(),
    this.latencyMs = 0,
    this.failure,
  });

  /// 角色。
  final RoleId role;

  /// 状态。
  final AgentStatus status;

  /// 风险卡（status==ok 时非空；失败时不产出规则模板卡片）。
  final RiskCard? card;

  /// 本角色新增证据。
  final List<Evidence> evidence;

  /// 工具调用次数。
  final int toolCalls;

  /// token 用量。
  final TokenUsage tokens;

  /// 延迟。
  final int latencyMs;

  /// 失败描述。
  final AgentFailure? failure;
}

/// 冲突。
final class Conflict {
  /// 创建冲突。
  const Conflict({
    required this.conflictId,
    required this.subject,
    required this.claimIds,
    required this.roles,
    required this.type,
    required this.description,
    this.severity = Severity.medium,
    this.evidenceIds = const [],
    this.resolved = false,
    this.resolution = '',
    this.resolvedBy,
  });

  /// 冲突 ID。
  final String conflictId;

  /// 归一化 subject。
  final String subject;

  /// 涉及主张。
  final List<String> claimIds;

  /// 涉及角色。
  final List<RoleId> roles;

  /// 类型。
  final ConflictType type;

  /// 描述。
  final String description;

  /// 严重度。
  final Severity severity;

  /// 涉及证据。
  final List<String> evidenceIds;

  /// 是否已解决。
  final bool resolved;

  /// 解决说明。
  final String resolution;

  /// 解决来源。
  final ResolvedBy? resolvedBy;

  /// 复制并替换仲裁结果。
  Conflict copyWith({
    bool? resolved,
    String? resolution,
    ResolvedBy? resolvedBy,
    Severity? severity,
  }) => Conflict(
    conflictId: conflictId,
    subject: subject,
    claimIds: claimIds,
    roles: roles,
    type: type,
    description: description,
    severity: severity ?? this.severity,
    evidenceIds: evidenceIds,
    resolved: resolved ?? this.resolved,
    resolution: resolution ?? this.resolution,
    resolvedBy: resolvedBy ?? this.resolvedBy,
  );
}

/// 核验问题。
final class VerificationIssue {
  /// 创建问题。
  const VerificationIssue({
    required this.issueType,
    required this.detail,
    this.role,
    this.claimId,
    this.severity = 'warning',
  });

  /// 问题类型：numeric|citation|leakage|permission|schema|unsupported|semantic。
  final String issueType;

  /// 详情。
  final String detail;

  /// 角色。
  final RoleId? role;

  /// 主张 ID。
  final String? claimId;

  /// 严重度：info|warning|error。
  final String severity;
}

/// 六类核验报告。
final class VerificationReport {
  /// 创建报告。
  const VerificationReport({
    required this.runId,
    this.numericChecksTotal = 0,
    this.numericChecksPassed = 0,
    this.citationChecksTotal = 0,
    this.citationChecksPassed = 0,
    this.semanticChecksTotal = 0,
    this.semanticChecksPassed = 0,
    this.semanticUnverified = 0,
    this.unsupportedClaims = 0,
    this.permissionViolations = 0,
    this.leakageEvents = 0,
    this.schemaErrors = 0,
    this.issues = const [],
    this.passed = false,
  });

  /// run id。
  final String runId;

  /// 数值检查数。
  final int numericChecksTotal;

  /// 数值通过数。
  final int numericChecksPassed;

  /// 引文检查数。
  final int citationChecksTotal;

  /// 引文通过数。
  final int citationChecksPassed;

  /// 语义检查数。
  final int semanticChecksTotal;

  /// 语义通过数。
  final int semanticChecksPassed;

  /// 语义未判定数。
  final int semanticUnverified;

  /// 无依据主张数。
  final int unsupportedClaims;

  /// 越权次数。
  final int permissionViolations;

  /// 时点泄漏次数（>0 → 核验不通过）。
  final int leakageEvents;

  /// schema 错误数。
  final int schemaErrors;

  /// 问题清单。
  final List<VerificationIssue> issues;

  /// 是否通过。
  final bool passed;

  /// 数值错误率（分母为 0 时为 0）。
  double get numericErrorRate {
    if (numericChecksTotal == 0) {
      return 0;
    }
    return (numericChecksTotal - numericChecksPassed) / numericChecksTotal;
  }
}

/// 协调统计。
final class CoordinationStats {
  /// 创建统计。
  const CoordinationStats({
    this.toolCalls = 0,
    this.tokens = 0,
    this.latencyMs = 0,
    this.evidenceShared = 0,
    this.duplicateEvidence = 0,
    this.conflictsDetected = 0,
    this.conflictsResolved = 0,
    this.conflictsEscalated = 0,
    this.jointCost = 0,
    this.truncated = false,
  });

  /// 工具调用。
  final int toolCalls;

  /// token。
  final int tokens;

  /// 延迟。
  final int latencyMs;

  /// 共享证据数。
  final int evidenceShared;

  /// 去重命中数。
  final int duplicateEvidence;

  /// 检出冲突。
  final int conflictsDetected;

  /// 已解决冲突。
  final int conflictsResolved;

  /// 升级冲突。
  final int conflictsEscalated;

  /// J = L + μ·C。
  final double jointCost;

  /// 是否发生预算截断。
  final bool truncated;
}

/// 最终决策卡。
final class DecisionCard {
  /// 创建决策卡。
  const DecisionCard({
    required this.runId,
    required this.asOf,
    required this.mode,
    required this.cards,
    required this.evidence,
    required this.conflicts,
    required this.verification,
    required this.coordination,
    required this.finalLevel,
    required this.finalAdvice,
    required this.limitations,
    required this.degradedRoles,
    required this.createdAt,
    this.partial = false,
    this.humanOverrides = const [],
  });

  /// run id。
  final String runId;

  /// 时点。
  final DateTime asOf;

  /// 模式。
  final String mode;

  /// 三张子卡（降级角色缺席）。
  final List<RiskCard> cards;

  /// 证据快照。
  final List<Evidence> evidence;

  /// 冲突。
  final List<Conflict> conflicts;

  /// 核验报告。
  final VerificationReport verification;

  /// 协调统计。
  final CoordinationStats coordination;

  /// 最终等级（取更强；降级角色不参与）。
  final RiskLevel finalLevel;

  /// 最终建议。
  final String finalAdvice;

  /// 局限（≤8，系统追加）。
  final List<String> limitations;

  /// 降级角色。
  final List<RoleId> degradedRoles;

  /// 创建时间。
  final DateTime createdAt;

  /// 是否为部分结论（预算/时间不足）。
  final bool partial;

  /// 人工覆盖（不进 evidenceIds）。
  final List<String> humanOverrides;
}
