/// 确定性风险等级判定与决策损失分解（docs/03 §1.8）。
///
/// LLM 的判断只作参考；等级由「压力概率 + 工具证据越阈」复算。
library;

import '../models/domain.dart';
import '../roles/role_config.dart';

/// 判定结果。
final class LevelDecision {
  /// 创建结果。
  const LevelDecision({
    required this.level,
    required this.probability,
    required this.escalationEvidenceIds,
    required this.limitations,
  });

  /// 最终等级。
  final RiskLevel level;

  /// 使用的压力概率（null 表示无可用信号）。
  final double? probability;

  /// 触发上调的证据 id。
  final List<String> escalationEvidenceIds;

  /// 判定过程中的系统局限。
  final List<String> limitations;
}

/// 取某角色窗口的压力概率（缺窗口取最近，再缺用 percentile）。
double? probabilityForWindow(RiskSignal? signal, int horizonDays) {
  if (signal == null) {
    return null;
  }
  final horizons = signal.horizons;
  if (horizons.isEmpty) {
    return signal.percentile;
  }
  if (horizons.containsKey(horizonDays)) {
    return horizons[horizonDays];
  }
  final keys = horizons.keys.toList()..sort((a, b) => a.compareTo(b));
  final nearest = keys.reduce(
    (a, b) => (a - horizonDays).abs() <= (b - horizonDays).abs() ? a : b,
  );
  return horizons[nearest];
}

/// 由概率定基准等级。
RiskLevel baseLevelFor(double? probability, RoleSpec spec) {
  if (probability == null) {
    return RiskLevel.low;
  }
  final high = spec.highStressProb;
  final critical = spec.criticalStressProb;
  if (probability >= critical) {
    return RiskLevel.critical;
  }
  if (probability >= high) {
    return RiskLevel.high;
  }
  if (probability >= high * 0.5) {
    return RiskLevel.medium;
  }
  return RiskLevel.low;
}

/// 判定某角色风险等级（两步：概率基准 → 工具越阈 +1）。
LevelDecision decideLevel({
  required RoleSpec spec,
  required RiskSignal? signal,
  required Iterable<Evidence> evidence,
}) {
  final probability = probabilityForWindow(signal, spec.horizonDays);
  var level = baseLevelFor(probability, spec);
  final limitations = <String>[];

  if (probability == null) {
    limitations.add('共享风险信号不可用，风险等级按最低档处理（非结论，仅占位）。');
  }

  final thresholdKey = spec.escalationThresholdKey;
  final threshold = thresholdKey == null ? null : spec.thresholds[thresholdKey];
  final escalations = <String>[];
  if (threshold != null) {
    for (final item in evidence) {
      final value = item.value;
      if (item.kind != EvidenceKind.tool || value == null) {
        continue;
      }
      final haystack =
          '${item.title} ${item.summary} ${item.payload['metric'] ?? ''}'
              .toLowerCase();
      final hit = spec.escalationKeywords.any(
        (keyword) => haystack.contains(keyword.toLowerCase()),
      );
      if (hit && value.abs() >= threshold) {
        escalations.add(item.evidenceId);
      }
    }
  }
  if (escalations.isNotEmpty) {
    level = level.escalate();
  }

  return LevelDecision(
    level: level,
    probability: probability,
    escalationEvidenceIds: escalations,
    limitations: limitations,
  );
}

/// 决策损失分解（预期损失而非金额）。
Map<String, double> decisionLossBreakdown({
  required RoleSpec spec,
  required double? probability,
}) {
  final p = probability ?? 0;
  const silentKeys = {
    'miss',
    'missed_exit',
    'tail_loss',
    'cost_overrun',
    'liquidity_shortfall',
    'delay',
  };
  var ifWarn = 0.0;
  var ifSilent = 0.0;
  final components = <String, double>{};
  for (final entry in spec.decisionLossWeights.entries) {
    final silent = silentKeys.contains(entry.key);
    final factor = silent ? p : 1 - p;
    final expected = _round(entry.value * factor, 6);
    components['expected_${entry.key}'] = expected;
    if (silent) {
      ifSilent += entry.value;
    } else {
      ifWarn += entry.value;
    }
  }
  components['if_warn_total'] = _round(ifWarn, 6);
  components['if_silent_total'] = _round(ifSilent, 6);
  components['signal_probability'] = _round(p, 6);
  return components;
}

/// 系统级自动追加的 limitations（≤8，去重保序）。
List<String> systemLimitations({
  required int max,
  required bool signalMissing,
  required bool kbUnavailable,
  required bool toolsFailed,
  required List<RoleId> degradedRoles,
  required bool budgetTruncated,
  required bool partial,
  required String mode,
  bool llmRuleFallback = false,
}) => _dedupe([
  '风险等级由确定性阈值判定，模型自评仅作参考。',
  'claim 中的数值已按工具证据回填，非模型自报数值。',
  '决策损失为归一化预期损失，不是金额。',
  if (signalMissing) '共享风险信号不可用，压力概率缺失（缺失不等于零值）。',
  if (kbUnavailable) '知识库不可用，文本类结论缺失依据。',
  if (toolsFailed) '部分确定性工具失败，相关数值未产出。',
  if (degradedRoles.isNotEmpty)
    '降级角色：${degradedRoles.map((r) => r.wire).join('、')}（未产出结论，不参与等级合成）。',
  if (budgetTruncated) '本次研判因预算/时间限制提前收敛，结论为部分结论。',
  if (partial) '部分结论：存在未完成阶段，建议人工复核。',
  if (llmRuleFallback) '模型判断不可用，已回退规则门卫（未使用模型判断）。',
  if (mode == 'single') '单智能体基线：三个主体任务由同一 agent 依次完成。',
]).take(max).toList();

List<String> _dedupe(List<String> items) => <String>[
  ...{for (final item in items) item},
];

double _round(double value, int digits) {
  final factor = _pow10(digits);
  return (value * factor).roundToDouble() / factor;
}

double _pow10(int digits) {
  var result = 1.0;
  for (var i = 0; i < digits; i++) {
    result *= 10;
  }
  return result;
}
