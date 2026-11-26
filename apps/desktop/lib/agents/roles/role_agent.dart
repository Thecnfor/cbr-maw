/// 角色智能体（R0.2）：LLM 产出草稿 → 自检回填 → 确定性定级。
///
/// 零 Mock：LLM 失败 → 该角色 `status=failed`，**不产出规则模板卡片**。
library;

import 'dart:convert';

import '../claims/claim_materializer.dart';
import '../claims/risk_level.dart';
import '../llm/llm_channel.dart';
import '../models/domain.dart';
import '../roles/prompt_builder.dart';
import '../roles/role_config.dart';
import '../tools/tool_registry.dart';

/// 角色运行输入。
final class RoleRunInput {
  /// 创建输入。
  const RoleRunInput({
    required this.runId,
    required this.asOf,
    required this.role,
    required this.spec,
    required this.task,
    required this.evidence,
    required this.signal,
    required this.signalRef,
    this.peerFacts = const [],
    this.round = 0,
  });

  /// run id。
  final String runId;

  /// 时点。
  final DateTime asOf;

  /// 角色。
  final RoleId role;

  /// 角色规范。
  final RoleSpec spec;

  /// 任务描述。
  final String task;

  /// 本角色可见证据。
  final List<Evidence> evidence;

  /// 共享信号。
  final RiskSignal? signal;

  /// 信号证据 id。
  final String? signalRef;

  /// 交叉验证轮的 peer 证据。
  final List<Evidence> peerFacts;

  /// 轮次。
  final int round;
}

/// 角色智能体。
final class RoleAgent {
  /// 创建角色智能体。
  RoleAgent({
    required this.prompts,
    required this.registry,
    this.generator,
    this.judge,
  });

  /// 提示词构建器。
  final PromptBuilder prompts;

  /// 工具注册表。
  final ToolRegistry registry;

  /// 生成器（null 表示模型不可用 → 显式失败）。
  final TextGenerator? generator;

  /// 裁判（可选，用于语义核验）。
  final Judge? judge;

  /// 运行一个角色（R0.2 独立分析）。
  Future<AgentOutput> run(RoleRunInput input) async {
    final started = DateTime.now();
    final generator = this.generator;
    if (generator == null) {
      return AgentOutput(
        role: input.role,
        status: AgentStatus.failed,
        latencyMs: DateTime.now().difference(started).inMilliseconds,
        failure: const AgentFailure(
          code: FailureCode.llmAuth,
          message: '模型通道未配置。请到「设置 → 连接」填写 DeepSeek 密钥后重试。',
        ),
      );
    }

    final system = prompts.renderRoleWithSpec(input.spec);
    final user = buildEvidencePrompt(
      asOf: input.asOf,
      task: input.task,
      evidence: input.evidence,
      peerFacts: input.peerFacts,
    );

    final LlmResponse response;
    try {
      response = await generator.generateJson(
        system: system,
        user: user,
        purpose: 'role:${input.role.wire}',
      );
    } on LlmFailure catch (failure) {
      return AgentOutput(
        role: input.role,
        status: AgentStatus.failed,
        latencyMs: DateTime.now().difference(started).inMilliseconds,
        failure: AgentFailure(
          code: _failureCode(failure.code),
          message: failure.message,
          retryable: failure.retryable,
          attempt: failure.attempt,
        ),
      );
    }

    final drafts = _parseDrafts(response.json['claims']);
    final available = {
      for (final item in input.evidence) item.evidenceId: item,
    };
    final materialized = materializeClaims(
      drafts: drafts,
      evidence: available,
      role: input.role,
      signalRef: input.signalRef,
    );

    final decision = decideLevel(
      spec: input.spec,
      signal: input.signal,
      evidence: input.evidence,
    );

    final limitations = [
      ...systemLimitations(
        max: 8,
        signalMissing: input.signal == null,
        kbUnavailable: !input.evidence.any((e) => e.kind == EvidenceKind.kb),
        toolsFailed: input.evidence.isEmpty,
        degradedRoles: const [],
        budgetTruncated: false,
        partial: false,
        mode: 'collaborative',
      ),
      ...decision.limitations,
      ..._stringList(response.json['limitations']),
    ];

    final card = RiskCard(
      role: input.role,
      asOf: input.asOf,
      riskLevel: decision.level,
      headline: (response.json['headline'] as String? ?? '').trim(),
      baseSignalRef: input.signalRef,
      keyMetrics: _metrics(input.evidence),
      claims: materialized.claims,
      escalationEvidenceIds: decision.escalationEvidenceIds,
      recommendation: (response.json['recommendation'] as String? ?? '').trim(),
      decisionLoss: decisionLossBreakdown(
        spec: input.spec,
        probability: decision.probability,
      ),
      limitations: limitations.take(8).toList(),
      evidenceIds: {
        for (final claim in materialized.claims) ...claim.evidenceIds,
      }.toList(),
      toolCalls: 0,
      tokens: response.usage.total,
      latencyMs: response.latencyMs,
      round: input.round,
    );

    return AgentOutput(
      role: input.role,
      status: AgentStatus.ok,
      card: card,
      evidence: input.evidence,
      toolCalls: 0,
      tokens: TokenUsage(
        prompt: response.usage.prompt,
        completion: response.usage.completion,
        total: response.usage.total,
      ),
      latencyMs: response.latencyMs,
      numericMismatches: materialized.numericMismatches,
    );
  }

  List<DraftClaim> _parseDrafts(Object? raw) {
    if (raw is! List<Object?>) {
      return const [];
    }
    return [
      for (final item in raw.whereType<Map<String, Object?>>())
        DraftClaim(
          claimType: item['claim_type'] as String? ?? 'text',
          subject: item['subject'] as String? ?? '',
          text: item['text'] as String? ?? '',
          value: (item['value'] as num?)?.toDouble(),
          unit: item['unit'] as String?,
          direction: Direction.parseOrNone(item['direction']),
          evidenceIds: (item['evidence_ids'] as List<Object?>? ?? const [])
              .whereType<String>()
              .toList(),
          confidence: (item['confidence'] as num?)?.toDouble(),
        ),
    ];
  }

  List<MetricItem> _metrics(List<Evidence> evidence) => [
    for (final item in evidence.where((e) => e.value != null).take(8))
      MetricItem(
        name: item.tool?.name ?? item.title,
        label: item.title,
        value: item.value,
        unit: item.unit,
        evidenceId: item.evidenceId,
      ),
  ];

  List<String> _stringList(Object? raw) =>
      raw is List<Object?> ? raw.whereType<String>().toList() : const [];

  FailureCode _failureCode(LlmFailureCode code) => switch (code) {
    LlmFailureCode.missingKey ||
    LlmFailureCode.unauthorized => FailureCode.llmAuth,
    LlmFailureCode.timeout => FailureCode.llmTimeout,
    LlmFailureCode.invalidOutput ||
    LlmFailureCode.truncated => FailureCode.llmInvalidOutput,
    LlmFailureCode.rateLimited => FailureCode.llmTimeout,
    LlmFailureCode.unavailable => FailureCode.llmTimeout,
  };
}

/// 解析交叉验证 findings。
List<CrossValidationFinding> parseFindings(Object? raw) {
  if (raw is! List<Object?>) {
    return const [];
  }
  return [
    for (final item in raw.whereType<Map<String, Object?>>())
      CrossValidationFinding(
        evidenceId: item['evidence_id'] as String? ?? '',
        verdict: item['verdict'] as String? ?? 'uncertain',
        note: item['note'] as String? ?? '',
        recomputedValue: (item['recomputed_value'] as num?)?.toDouble(),
      ),
  ];
}

/// 交叉验证 finding。
final class CrossValidationFinding {
  /// 创建 finding。
  const CrossValidationFinding({
    required this.evidenceId,
    required this.verdict,
    required this.note,
    this.recomputedValue,
  });

  /// 被复核证据（必须来自 peerFacts）。
  final String evidenceId;

  /// confirmed | refuted | uncertain。
  final String verdict;

  /// ≤80 字。
  final String note;

  /// 只能抄录已出现数值。
  final double? recomputedValue;

  /// 序列化（供 trace）。
  Map<String, Object?> toJson() => {
    'evidence_id': evidenceId,
    'verdict': verdict,
    'note': note,
    'recomputed_value': recomputedValue,
  };
}

/// 把 JSON 对象编码为提示词中的证据包（导出给测试）。
String encodePacket(Map<String, Object?> packet) => jsonEncode(packet);
