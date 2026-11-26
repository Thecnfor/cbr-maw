import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../ui.dart';
import '../theme/theme.dart';
import '../theme/tokens.dart';

/// 六维固定顺序与中文名（docs/22 屏 5、docs/20）。
///
/// 顺序固定，缺席维度占位显示，不隐藏也不填 0。
const sixDimensions = <({String key, String label})>[
  (key: 'dim_equity', label: '股票'),
  (key: 'dim_bond', label: '债券'),
  (key: 'dim_credit', label: '信用'),
  (key: 'dim_fx', label: '汇率'),
  (key: 'dim_crossborder', label: '跨境资金'),
  (key: 'dim_global', label: '全球'),
];

/// 缺席维度的原因（由来源五态推导）。
///
/// 规则：需授权 / 需登录 → 需授权；反爬受限 / 不可达 → 不可达；其余 → 数据不足。
String absenceReason(SourceState? state) => switch (state) {
  SourceState.needAuth || SourceState.needLogin => '未计入（需授权）',
  SourceState.restricted || SourceState.unreachable => '未计入（不可达）',
  _ => '未计入（数据不足）',
};

/// 六维与序列前缀的对应（用于把来源五态归到维度）。
const dimensionSeriesPrefix = <String, List<String>>{
  'dim_equity': ['market.cn_equity'],
  'dim_bond': ['market.cn_bond'],
  'dim_credit': ['rates.credit'],
  'dim_fx': ['market.fx'],
  'dim_crossborder': ['crossborder'],
  'dim_global': ['market.global'],
};

/// 六维分解（docs/22 屏 5）。
///
/// 缺失维度写「未计入（需授权 / 不可达）」而不是 0；「缺失」与「0」在
/// 图标 + 文案 + 颜色上三重可区分。
final class DimensionBreakdown extends StatelessWidget {
  /// 创建六维分解。
  const DimensionBreakdown({
    required this.dims,
    required this.missingDims,
    this.absenceReasons = const {},
    super.key,
  });

  /// 维度明细（键为 `dim_*`，值可以是数值或 `{"value": ...}` 结构）。
  final Map<String, Object?> dims;

  /// 缺席维度键。
  final List<String> missingDims;

  /// 每个缺席维度的原因文案（缺省按「数据不足」）。
  final Map<String, String> absenceReasons;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = SemanticColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (final dim in sixDimensions)
          Padding(
            padding: const EdgeInsets.only(bottom: Tokens.space2),
            child: _DimensionRow(
              label: dim.label,
              value: _numeric(dims[dim.key]),
              absence:
                  missingDims.contains(dim.key) ||
                      _numeric(dims[dim.key]) == null
                  ? (absenceReasons[dim.key] ?? absenceReason(null))
                  : null,
            ),
          ),
        const SizedBox(height: Tokens.space1),
        Text(
          '缺席维度不参与计算，未用 0 或均值填充。',
          style: TextStyle(
            fontSize: 12,
            color: theme.colorScheme.onSurfaceVariant,
          ),
        ),
        if (missingDims.isNotEmpty) ...[
          const SizedBox(height: Tokens.space1),
          Text(
            '相关非因果：维度贡献表示同期压力来源结构，不代表因果方向。',
            style: TextStyle(fontSize: 12, color: colors.idleInk),
          ),
        ],
      ],
    );
  }

  /// 从 `{"value": x}` 或裸数值取数；非有限值一律视为缺失。
  static double? _numeric(Object? raw) {
    if (raw is num) {
      final v = raw.toDouble();
      return v.isFinite ? v : null;
    }
    if (raw is Map) {
      return _numeric(raw['value']);
    }
    return null;
  }
}

final class _DimensionRow extends StatelessWidget {
  const _DimensionRow({
    required this.label,
    required this.value,
    required this.absence,
  });

  final String label;
  final double? value;
  final String? absence;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = SemanticColors.of(context);
    final missing = absence != null;
    final clamped = (value ?? 0).clamp(0.0, 1.0);
    return Row(
      children: [
        SizedBox(
          width: 72,
          child: Text(label, style: const TextStyle(fontSize: 13)),
        ),
        Expanded(
          child: missing
              // 缺失：虚线轨道 + 明确文案，绝不显示 0。
              ? Container(
                  height: 8,
                  decoration: BoxDecoration(
                    color: colors.warnTint,
                    borderRadius: BorderRadius.circular(4),
                    border: Border.all(
                      color: colors.warnInk.withValues(alpha: 0.4),
                    ),
                  ),
                )
              : ClipRRect(
                  borderRadius: BorderRadius.circular(4),
                  child: LinearProgressIndicator(
                    value: clamped,
                    minHeight: 8,
                    backgroundColor: theme.colorScheme.surfaceContainerHighest,
                  ),
                ),
        ),
        const SizedBox(width: Tokens.space2),
        SizedBox(
          width: 168,
          child: missing
              ? Row(
                  children: [
                    Icon(
                      Icons.remove_circle_outline,
                      size: 13,
                      color: colors.warnInk,
                    ),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        absence!,
                        style: TextStyle(fontSize: 12, color: colors.warnInk),
                      ),
                    ),
                  ],
                )
              : Text(
                  value!.toStringAsFixed(3),
                  style: TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12,
                    color: theme.colorScheme.onSurface,
                  ),
                ),
        ),
      ],
    );
  }
}
