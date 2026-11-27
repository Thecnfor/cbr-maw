import '../ui.dart';
import '../theme/theme.dart';
import '../theme/tokens.dart';
import 'states.dart';

/// 页头（标题 + 副标题 + 尾部动作）。
final class PageHeader extends StatelessWidget {
  /// 创建页头。
  const PageHeader({
    required this.title,
    this.subtitle,
    this.actions = const [],
    super.key,
  });

  /// 标题。
  final String title;

  /// 副标题。
  final String? subtitle;

  /// 尾部动作。
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        Tokens.space5,
        Tokens.space5,
        Tokens.space5,
        Tokens.space3,
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.headlineSmall),
                if (subtitle != null) ...[
                  const SizedBox(height: Tokens.space1),
                  Text(
                    subtitle!,
                    // 必须从主题派生：裸 TextStyle 会继承 ambient
                    // DefaultTextStyle 的 decoration（Material 之外的文本会带上
                    // 调试用的黄色下划线），主题样式则显式带 TextDecoration.none。
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ],
            ),
          ),
          ...actions,
        ],
      ),
    );
  }
}

/// 带标题的区块卡。
final class SectionCard extends StatelessWidget {
  /// 创建区块卡。
  const SectionCard({
    required this.title,
    required this.child,
    this.trailing,
    this.padding = const EdgeInsets.all(Tokens.space4),
    super.key,
  });

  /// 标题。
  final String title;

  /// 内容。
  final Widget child;

  /// 右上角动作。
  final Widget? trailing;

  /// 内边距。
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: padding,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    title,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
                ?trailing,
              ],
            ),
            const SizedBox(height: Tokens.space3),
            child,
          ],
        ),
      ),
    );
  }
}

/// 键值行。
final class KeyValueRow extends StatelessWidget {
  /// 创建键值行。
  const KeyValueRow({
    required this.label,
    required this.value,
    this.valueColor,
    super.key,
  });

  /// 键。
  final String label;

  /// 值。
  final String value;

  /// 值颜色（语义 ink）。
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 132,
            child: Text(
              label,
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
          ),
          Expanded(
            child: Text(value, style: TextStyle(color: valueColor)),
          ),
        ],
      ),
    );
  }
}

/// 可点进的列表项。
final class ListRow extends StatelessWidget {
  /// 创建列表项。
  const ListRow({
    required this.title,
    this.subtitle,
    this.leading,
    this.trailing,
    this.onTap,
    super.key,
  });

  /// 标题。
  final String title;

  /// 副标题。
  final String? subtitle;

  /// 前置。
  final Widget? leading;

  /// 尾部。
  final Widget? trailing;

  /// 点击。
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final content = Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: Tokens.space4,
        vertical: Tokens.space3,
      ),
      child: Row(
        children: [
          if (leading != null) ...[
            leading!,
            const SizedBox(width: Tokens.space3),
          ],
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: Theme.of(context).textTheme.bodyMedium),
                if (subtitle != null) ...[
                  const SizedBox(height: 2),
                  Text(
                    subtitle!,
                    style: TextStyle(
                      fontSize: 12,
                      color: Theme.of(context).colorScheme.onSurfaceVariant,
                    ),
                  ),
                ],
              ],
            ),
          ),
          ?trailing,
        ],
      ),
    );
    return InkWell(onTap: onTap, child: content);
  }
}

/// 横向指标条（KPI 行）。
final class MetricStrip extends StatelessWidget {
  /// 创建指标条。
  const MetricStrip({required this.metrics, super.key});

  /// 指标列表。
  final List<Widget> metrics;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: Tokens.space3,
      runSpacing: Tokens.space3,
      children: metrics,
    );
  }
}

/// 单指标卡。
final class MetricTile extends StatelessWidget {
  /// 创建指标卡。
  const MetricTile({
    required this.label,
    required this.value,
    this.hint,
    this.tone,
    super.key,
  });

  /// 指标名。
  final String label;

  /// 值（拿不到时传状态文案，不传占位数字）。
  final String value;

  /// 补充说明。
  final String? hint;

  /// 语气（null = 中性）。
  final BannerTone? tone;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final ink = switch (tone) {
      BannerTone.warn => SemanticColors.of(context).warnInk,
      BannerTone.error => SemanticColors.of(context).dangerInk,
      BannerTone.ok => SemanticColors.of(context).okInk,
      BannerTone.info => SemanticColors.of(context).infoInk,
      null => theme.colorScheme.onSurface,
    };
    return Container(
      width: 196,
      padding: const EdgeInsets.all(Tokens.space3),
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(Tokens.radiusCard),
        border: Border.all(
          color: theme.dividerTheme.color ?? theme.colorScheme.outline,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label,
            style: TextStyle(
              fontSize: 12,
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: Tokens.space1),
          Text(value, style: theme.textTheme.titleMedium?.copyWith(color: ink)),
          if (hint != null) ...[
            const SizedBox(height: 2),
            Text(
              hint!,
              style: TextStyle(
                fontSize: 12,
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
