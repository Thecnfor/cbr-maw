import '../ui.dart';
import '../theme/theme.dart';
import '../theme/tokens.dart';

/// SYNTHETIC 标记（docs/22 屏 2 红线）。
///
/// 选「先看示例」后，任何页面与导出物都必须携带标记：顶部条 + 图表/卡片角标。
/// 标记文字自足，不依赖颜色。
final class SyntheticBadge extends StatelessWidget {
  /// 创建角标。
  const SyntheticBadge({this.compact = false, super.key});

  /// 紧凑形态（只显示 `SYNTHETIC`）。
  final bool compact;

  /// 角标文案（导出与图表复用同一句）。
  static const marker = 'SYNTHETIC';

  /// 完整说明。
  static const disclaimer = '仿真数据，仅供演示，不可用于投资或监管决策';

  @override
  Widget build(BuildContext context) {
    final colors = SemanticColors.of(context);
    return Semantics(
      label: '$marker 仿真数据',
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: colors.warnTint,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: colors.warnInk.withValues(alpha: 0.4)),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.science_outlined, size: 13, color: colors.warnInk),
            const SizedBox(width: 4),
            Text(
              compact ? marker : '$marker · $disclaimer',
              style: TextStyle(
                fontSize: 12,
                height: 1.4,
                color: colors.warnInk,
                fontWeight: FontWeight.w600,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 全局 SYNTHETIC 顶部条（挂在外壳上，任何页面可见）。
final class SyntheticTopBar extends StatelessWidget {
  /// 创建顶部条。
  const SyntheticTopBar({super.key});

  @override
  Widget build(BuildContext context) {
    final colors = SemanticColors.of(context);
    return Container(
      width: double.infinity,
      color: colors.warnTint,
      padding: const EdgeInsets.symmetric(
        horizontal: Tokens.space4,
        vertical: 6,
      ),
      child: Row(
        children: [
          Icon(Icons.science_outlined, size: 14, color: colors.warnInk),
          const SizedBox(width: 6),
          Expanded(
            child: Text(
              '${SyntheticBadge.marker} · ${SyntheticBadge.disclaimer}',
              style: TextStyle(fontSize: 12, color: colors.warnInk),
            ),
          ),
        ],
      ),
    );
  }
}
