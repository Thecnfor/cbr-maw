import '../ui.dart';
import '../layout/breakpoints.dart';
import '../routes.dart';
import '../theme/theme.dart';
import '../theme/tokens.dart';

/// 顶栏（面包屑、全局状态、时钟、命令面板入口）。
final class AppTopBar extends StatelessWidget {
  /// 创建顶栏。
  const AppTopBar({
    required this.location,
    required this.kernelStateLabel,
    required this.kernelReady,
    required this.onOpenPalette,
    required this.compact,
    this.clock,
    super.key,
  });

  /// 当前路由。
  final String location;

  /// 内核状态文案。
  final String kernelStateLabel;

  /// 内核是否就绪（状态点语气）。
  final bool kernelReady;

  /// 打开命令面板。
  final VoidCallback onOpenPalette;

  /// 是否精简（窄屏）。
  final bool compact;

  /// 时钟文案（窄屏隐藏）。
  final String? clock;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final item = navItemFor(location);
    final title = item?.label ?? '未知页面';
    final colors = SemanticColors.of(context);
    return Container(
      height: compact
          ? NavMetrics.compactTopBarHeight
          : NavMetrics.topBarHeight,
      padding: const EdgeInsets.symmetric(horizontal: Tokens.space4),
      decoration: BoxDecoration(
        color: theme.brightness == Brightness.dark ? Tokens.n2d : Tokens.n0,
        border: Border(
          bottom: BorderSide(
            color: theme.dividerTheme.color ?? theme.colorScheme.outline,
          ),
        ),
      ),
      child: Row(
        children: [
          if (!compact && item != null && item.group != '工作台')
            Text(
              '${item.group} / ',
              style: TextStyle(color: theme.colorScheme.onSurfaceVariant),
            ),
          Text(title, style: theme.textTheme.titleSmall),
          const Spacer(),
          if (clock != null && !compact) ...[
            Text(
              clock!,
              style: TextStyle(
                fontSize: 12,
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(width: Tokens.space4),
          ],
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Container(
                width: 8,
                height: 8,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: kernelReady ? colors.okInk : colors.warnInk,
                ),
              ),
              const SizedBox(width: 6),
              Text(
                kernelStateLabel,
                style: TextStyle(
                  fontSize: 12,
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
          const SizedBox(width: Tokens.space3),
          OutlinedButton.icon(
            onPressed: onOpenPalette,
            icon: const Icon(Icons.search, size: 16),
            label: Text(compact ? '' : '搜索  Ctrl+K'),
          ),
        ],
      ),
    );
  }
}
