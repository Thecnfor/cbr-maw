/// 冲突接入决策损失（ADR-010 §1、docs/02 F5、docs/20 §3）。
///
/// 未解决的冲突本身就是风险：两方结论不一致时，无论采信哪一方，
/// 都存在「采错」的代价。把它折进损失函数，才能让「协同没谈拢」
/// 反映在代价上，而不是只在界面上挂个红点。
///
/// 口径（与 `decisionLossBreakdown` 一致，均为**预期损失**而非金额）：
/// - `fact`：事实分歧，最贵——数值口径都没对齐，采信任一方都可能错；
/// - `directional`：方向分歧，中等——趋势判断相反；
/// - `preference`：偏好差异，**不计入**（docs/20：偏好差异不算错误）。
///
/// 已解决冲突按 `resolvedBy` 打折：工具重算 > 证据等级 > HITL。
library;

import '../models/domain.dart';

/// 各类冲突的基准代价（无单位的相对权重）。
const Map<ConflictType, double> _baseCost = <ConflictType, double>{
  ConflictType.fact: 1.0,
  ConflictType.directional: 0.4,
  ConflictType.preference: 0.0,
};

/// 按仲裁方式打折：工具重算最可信，HITL 次之，未解决不打折。
const Map<ResolvedBy, double> _resolvedFactor = <ResolvedBy, double>{
  ResolvedBy.tool: 0.1,
  ResolvedBy.authority: 0.3,
  ResolvedBy.consensus: 0.2,
  ResolvedBy.human: 0.5,
  ResolvedBy.unresolved: 1.0,
};

/// 计算冲突损失分解。
///
/// 返回：
/// - `conflict_total`：总预期损失；
/// - `conflict_escalated`：升级人工的部分（未决代价）；
/// - `conflict_by_type_<type>`：按类型分解。
Map<String, double> conflictLossBreakdown({
  required List<Conflict> conflicts,
  List<String> escalated = const [],
}) {
  var total = 0.0;
  var escalatedCost = 0.0;
  final byType = <ConflictType, double>{};

  for (final conflict in conflicts) {
    final base = _baseCost[conflict.type] ?? 0.0;
    if (base == 0) {
      continue;
    }
    // 严重度加权：high 全价，medium 打七折，low 打四折。
    final severity = switch (conflict.severity) {
      Severity.high => 1.0,
      Severity.medium => 0.7,
      Severity.low => 0.4,
    };
    // 已仲裁的按仲裁方式打折；未解决的全价计入。
    final factor = conflict.resolved
        ? (_resolvedFactor[conflict.resolvedBy] ?? 0.5)
        : 1.0;
    final cost = _round(base * severity * factor);
    total += cost;
    byType[conflict.type] = (byType[conflict.type] ?? 0) + cost;
    if (escalated.contains(conflict.conflictId)) {
      escalatedCost += cost;
    }
  }

  return {
    'conflict_total': _round(total),
    'conflict_escalated': _round(escalatedCost),
    for (final entry in byType.entries)
      'conflict_by_type_${entry.key.wire}': _round(entry.value),
  };
}

double _round(double v) => double.parse(v.toStringAsFixed(6));
