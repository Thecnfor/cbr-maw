/// 角色与编排配置（唯一真源 = [roles.json]，由 docs/legacy-configs/roles.yaml 迁移）。
library;

import 'dart:convert';

import 'asset_source.dart';
import '../models/domain.dart';

/// 单个角色的规范。
final class RoleSpec {
  /// 创建角色规范。
  const RoleSpec({
    required this.role,
    required this.displayName,
    required this.horizonDays,
    required this.objective,
    required this.focus,
    required this.infoPermissions,
    required this.toolPermissions,
    required this.thresholds,
    required this.decisionLossWeights,
    required this.escalationKeywords,
    required this.escalationThresholdKey,
    required this.forbiddenActions,
    required this.outputStyle,
  });

  /// 从 JSON 解析（解析即校验）。
  factory RoleSpec.parse(RoleId role, Object? json) {
    if (json is! Map<String, Object?>) {
      throw FormatException('角色 ${role.wire} 配置必须是对象');
    }
    List<String> strings(String key) =>
        (json[key] as List<Object?>? ?? const []).cast<String>().toList();
    Map<String, double> numbers(String key) => {
      for (final entry
          in (json[key] as Map<String, Object?>? ?? const {}).entries)
        entry.key: (entry.value as num).toDouble(),
    };
    return RoleSpec(
      role: role,
      displayName: json['display_name'] as String,
      horizonDays: (json['horizon_days'] as num).toInt(),
      objective: json['objective'] as String,
      focus: strings('focus'),
      infoPermissions: strings('info_permissions'),
      toolPermissions: strings('tool_permissions'),
      thresholds: numbers('thresholds'),
      decisionLossWeights: numbers('decision_loss_weights'),
      escalationKeywords: strings('escalation_keywords'),
      escalationThresholdKey: json['escalation_threshold_key'] as String?,
      forbiddenActions: strings('forbidden_actions'),
      outputStyle: json['output_style'] as String,
    );
  }

  /// 角色。
  final RoleId role;

  /// 中文名。
  final String displayName;

  /// 判定窗口（交易日）。
  final int horizonDays;

  /// 目标函数。
  final String objective;

  /// 关注重点。
  final List<String> focus;

  /// 信息域白名单。
  final List<String> infoPermissions;

  /// 可直接调用的工具白名单（知识库检索由编排层统一执行）。
  final List<String> toolPermissions;

  /// 预警阈值。
  final Map<String, double> thresholds;

  /// 决策损失权重。
  final Map<String, double> decisionLossWeights;

  /// 升级关键词。
  final List<String> escalationKeywords;

  /// 升级阈值键。
  final String? escalationThresholdKey;

  /// 禁止行为。
  final List<String> forbiddenActions;

  /// 输出风格。
  final String outputStyle;

  /// 主阈值（缺省 0.5）。
  double get highStressProb => thresholds['high_stress_prob'] ?? 0.5;

  /// 极高阈值（缺省 min(0.95, high+0.2)）。
  double get criticalStressProb =>
      thresholds['critical_stress_prob'] ??
      (highStressProb + 0.2).clamp(0, 0.95);

  /// 是否允许调用某工具。
  bool allowsTool(String tool) => toolPermissions.contains(tool);

  /// 是否允许引用某信息域。
  bool allowsDomain(String domain) =>
      infoPermissions.any((p) => domain == p || domain.startsWith('$p.'));

  /// 渲染用字段（阈值与权重按旧 YAML 行文）。
  Map<String, String> get renderFields => {
    'display_name': displayName,
    'objective': objective,
    'focus': focus.map((f) => '- $f').join('\n'),
    'info_permissions': infoPermissions.map((p) => '- $p').join('\n'),
    'tool_permissions': toolPermissions.map((p) => '- $p').join('\n'),
    'thresholds': thresholds.entries
        .map((e) => '- ${e.key}: ${e.value}')
        .join('\n'),
    'decision_loss_weights': decisionLossWeights.entries
        .map((e) => '- ${e.key}: ${e.value}')
        .join('\n'),
    'forbidden_actions': forbiddenActions.map((f) => '- $f').join('\n'),
    'output_style': outputStyle,
  };
}

/// 编排配置。
final class OrchestrationSettings {
  /// 创建配置。
  const OrchestrationSettings({
    required this.modes,
    required this.maxToolCallsPerAgent,
    required this.maxTokensPerAgent,
    required this.maxLatencyMsPerAgent,
    required this.maxWallClockMs,
    required this.maxDelegations,
    required this.numericToleranceAbs,
    required this.numericToleranceRel,
    required this.costPerToolCall,
    required this.costPer1kTokens,
    required this.costPerLatencyMs,
    required this.coordinationWeightMu,
    required this.maxLimitations,
  });

  /// 从 JSON 解析。
  factory OrchestrationSettings.parse(Object? json) {
    if (json is! Map<String, Object?>) {
      throw const FormatException('orchestration 配置必须是对象');
    }
    double d(String key) => (json[key] as num).toDouble();
    int i(String key) => (json[key] as num).toInt();
    return OrchestrationSettings(
      modes: (json['modes'] as List<Object?>? ?? const ['collaborative'])
          .cast<String>()
          .toList(),
      maxToolCallsPerAgent: i('max_tool_calls_per_agent'),
      maxTokensPerAgent: i('max_tokens_per_agent'),
      maxLatencyMsPerAgent: i('max_latency_ms_per_agent'),
      maxWallClockMs: i('max_wall_clock_ms'),
      maxDelegations: i('max_delegations'),
      numericToleranceAbs: d('numeric_tolerance_abs'),
      numericToleranceRel: d('numeric_tolerance_rel'),
      costPerToolCall: d('cost_per_tool_call'),
      costPer1kTokens: d('cost_per_1k_tokens'),
      costPerLatencyMs: d('cost_per_latency_ms'),
      coordinationWeightMu: d('coordination_weight_mu'),
      maxLimitations: i('max_limitations'),
    );
  }

  /// 启用的模式。
  final List<String> modes;

  /// 每角色工具调用上限。
  final int maxToolCallsPerAgent;

  /// 每角色 token 上限。
  final int maxTokensPerAgent;

  /// 每角色延迟上限。
  final int maxLatencyMsPerAgent;

  /// 整轮墙钟上限。
  final int maxWallClockMs;

  /// 委派上限。
  final int maxDelegations;

  /// 数值绝对容差。
  final double numericToleranceAbs;

  /// 数值相对容差。
  final double numericToleranceRel;

  /// 每次工具调用成本。
  final double costPerToolCall;

  /// 每千 token 成本。
  final double costPer1kTokens;

  /// 每毫秒延迟成本。
  final double costPerLatencyMs;

  /// 协同成本权重 μ。
  final double coordinationWeightMu;

  /// 局限条数上限。
  final int maxLimitations;

  /// 模式是否启用。
  bool modeEnabled(String mode) => modes.isEmpty || modes.contains(mode);
}

/// 角色配置集合。
final class RoleCatalog {
  /// 创建目录。
  const RoleCatalog(this.specs, this.orchestration);

  /// 从 JSON 文本解析。
  factory RoleCatalog.parse(String jsonText) {
    final decoded = jsonDecode(jsonText);
    if (decoded is! Map<String, Object?>) {
      throw const FormatException('roles.json 根节点必须是对象');
    }
    final roles = decoded['roles'] as Map<String, Object?>? ?? const {};
    return RoleCatalog({
      for (final role in RoleId.values)
        if (roles.containsKey(role.wire))
          role: RoleSpec.parse(role, roles[role.wire]),
    }, OrchestrationSettings.parse(decoded['orchestration']));
  }

  /// 从资源源加载。
  static Future<RoleCatalog> load(AssetSource source) async =>
      RoleCatalog.parse(await source.read('lib/agents/roles/roles.json'));

  /// 角色规范（只含出卡的三主体）。
  final Map<RoleId, RoleSpec> specs;

  /// 编排配置。
  final OrchestrationSettings orchestration;

  /// 出卡角色（监管 / 投资 / 融资）。
  List<RoleId> get analyticalRoles => RoleId.values
      .where((r) => r.producesCard && specs.containsKey(r))
      .toList();

  /// 取角色规范。
  RoleSpec spec(RoleId role) {
    final spec = specs[role];
    if (spec == null) {
      throw StateError('角色 ${role.wire} 未在配置中定义');
    }
    return spec;
  }
}
