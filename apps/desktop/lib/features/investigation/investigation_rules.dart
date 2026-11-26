import '../../agents/run_events.dart';
import '../../app/widgets/chips.dart';

/// 对话研判的纯规则（供界面与测试共用）。
///
/// - 缺证据的 claim 不显示（红线：结论必须可溯源）；
/// - 数值结论必须标「以工具重算为准」；
/// - 降级必须显式列出降级角色与「部分结论」。
abstract final class InvestigationRules {
  /// claim 是否可见（必须绑定至少一条证据）。
  static bool isVisible(List<String> evidenceIds) => evidenceIds.isNotEmpty;

  /// 数值结论是否需要「以工具重算为准」标记。
  static bool needsRecomputeNote(String kind) => kind == 'numeric';

  /// 研判结束摘要（含部分结论与降级角色）。
  static String summaryText(RunSummary summary, {int hiddenClaims = 0}) {
    final parts = [
      '研判结束。风险等级：'
          '${RiskLevelBadge.labelOf(riskLevelFromWire(summary.riskLevel))}；'
          '结论 ${summary.claimIds.length} 条，证据 ${summary.evidenceIds.length} 条，'
          '冲突 ${summary.conflictIds.length} 个。',
      if (summary.partial) '部分结论：预算或角色降级导致覆盖不全。',
      if (summary.degradedRoles.isNotEmpty)
        '降级角色：${summary.degradedRoles.map(roleLabel).join('、')}。',
      if (summary.limitations.isNotEmpty)
        '局限：${summary.limitations.take(3).join('；')}'
            '${summary.limitations.length > 3 ? ' 等' : ''}。',
      if (hiddenClaims > 0) '另有 $hiddenClaims 条无证据结论已丢弃，不显示。',
    ];
    return parts.join();
  }
}
