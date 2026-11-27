import '../ui.dart';
import '../layout/breakpoints.dart';
import '../routes.dart';
import '../theme/tokens.dart';

/// 侧栏（展开 248dp / 折叠 64dp，分组进入）。
final class AppSidebar extends StatelessWidget {
  /// 创建侧栏。
  const AppSidebar({
    required this.currentLocation,
    required this.collapsed,
    required this.onSelect,
    required this.onToggleCollapsed,
    this.footer,
    this.pendingInbox = 0,
    super.key,
  });

  /// 当前路由。
  final String currentLocation;

  /// 是否折叠。
  final bool collapsed;

  /// 选中导航。
  final void Function(String path) onSelect;

  /// 折叠切换。
  final VoidCallback onToggleCollapsed;

  /// 底部运行状态区。
  final Widget? footer;

  /// 投递箱待处理条目数（侧栏角标）。
  final int pendingInbox;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final width = collapsed
        ? NavMetrics.sidebarCollapsedWidth
        : NavMetrics.sidebarWidth;
    final groups = groupedNavItems();
    return Semantics(
      container: true,
      label: '主导航',
      child: AnimatedContainer(
        duration: Tokens.motionBase,
        width: width,
        decoration: BoxDecoration(
          color: theme.brightness == Brightness.dark ? Tokens.n1d : Tokens.n0,
          border: Border(
            right: BorderSide(
              color: theme.dividerTheme.color ?? theme.colorScheme.outline,
            ),
          ),
        ),
        child: Column(
          children: [
            SizedBox(
              height: NavMetrics.topBarHeight,
              child: Row(
                mainAxisAlignment: collapsed
                    ? MainAxisAlignment.center
                    : MainAxisAlignment.spaceBetween,
                children: [
                  if (!collapsed)
                    const Padding(
                      padding: EdgeInsets.only(left: Tokens.space4),
                      child: Text(
                        'CBR-MAW',
                        style: TextStyle(fontWeight: FontWeight.w700),
                      ),
                    ),
                  IconButton(
                    tooltip: collapsed ? '展开侧栏' : '折叠侧栏',
                    onPressed: onToggleCollapsed,
                    icon: Icon(
                      collapsed ? Icons.chevron_right : Icons.chevron_left,
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(vertical: Tokens.space2),
                children: [
                  for (final entry in groups.entries) ...[
                    if (!collapsed)
                      Padding(
                        padding: const EdgeInsets.fromLTRB(
                          Tokens.space4,
                          Tokens.space3,
                          Tokens.space4,
                          Tokens.space1,
                        ),
                        child: Text(
                          entry.key,
                          style: TextStyle(
                            fontSize: 11,
                            letterSpacing: 0.6,
                            color: theme.colorScheme.onSurfaceVariant,
                          ),
                        ),
                      ),
                    for (final item in entry.value)
                      _SidebarTile(
                        item: item,
                        selected:
                            navItemFor(currentLocation)?.path == item.path,
                        collapsed: collapsed,
                        badge: item.path == Routes.inbox && pendingInbox > 0
                            ? pendingInbox
                            : null,
                        onTap: () => onSelect(item.path),
                      ),
                  ],
                ],
              ),
            ),
            if (footer != null) ...[
              const Divider(height: 1),
              Padding(
                padding: const EdgeInsets.all(Tokens.space3),
                child: footer,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

final class _SidebarTile extends StatelessWidget {
  const _SidebarTile({
    required this.item,
    required this.selected,
    required this.collapsed,
    required this.onTap,
    this.badge,
  });

  final NavItem item;
  final bool selected;
  final bool collapsed;
  final VoidCallback onTap;

  /// 角标数字（null = 不显示）。
  final int? badge;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = selected
        ? theme.colorScheme.primary
        : theme.colorScheme.onSurfaceVariant;
    final tile = Semantics(
      selected: selected,
      button: true,
      child: InkWell(
        onTap: onTap,
        child: Container(
          height: 36,
          margin: const EdgeInsets.symmetric(
            horizontal: Tokens.space2,
            vertical: 1,
          ),
          padding: EdgeInsets.symmetric(
            horizontal: collapsed ? 0 : Tokens.space2,
          ),
          decoration: BoxDecoration(
            color: selected
                ? theme.colorScheme.primary.withValues(alpha: 0.10)
                : null,
            borderRadius: BorderRadius.circular(Tokens.radiusControl),
          ),
          child: Row(
            mainAxisAlignment: collapsed
                ? MainAxisAlignment.center
                : MainAxisAlignment.start,
            children: [
              Icon(item.icon, size: 18, color: color),
              if (!collapsed) ...[
                const SizedBox(width: Tokens.space2),
                Expanded(
                  child: Text(
                    item.label,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: color,
                      fontSize: 13,
                      fontWeight: selected ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ),
                if (badge != null)
                  Semantics(
                    label: '投递箱待处理 $badge 条',
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 6,
                        vertical: 1,
                      ),
                      decoration: BoxDecoration(
                        color: theme.colorScheme.primary,
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        '$badge',
                        style: TextStyle(
                          fontSize: 11,
                          color: theme.colorScheme.onPrimary,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ),
              ],
            ],
          ),
        ),
      ),
    );
    // 折叠态 tooltip 必须显示完整名称。
    return collapsed ? Tooltip(message: item.label, child: tile) : tile;
  }
}

/// 中档 Rail（72dp）。
final class AppRail extends StatelessWidget {
  /// 创建 Rail。
  const AppRail({
    required this.currentLocation,
    required this.onSelect,
    super.key,
  });

  /// 当前路由。
  final String currentLocation;

  /// 选中导航。
  final void Function(String path) onSelect;

  @override
  Widget build(BuildContext context) {
    final items = navItems;
    final selectedItem = navItemFor(currentLocation);
    final selectedIndex = selectedItem == null
        ? 0
        : items.indexWhere((item) => item.path == selectedItem.path);
    return Semantics(
      label: '主导航',
      container: true,
      // NavigationRail 在 640 高窗口下会溢出 136px（12 个目的地 × 标签）。
      // 包一层滚动：高度够时表现不变，不够时可滚动而不是报 RenderFlex 溢出。
      child: SingleChildScrollView(
        child: IntrinsicHeight(
          child: NavigationRail(
            extended: false,
            selectedIndex: selectedIndex < 0 ? 0 : selectedIndex,
            onDestinationSelected: (index) => onSelect(items[index].path),
            labelType: NavigationRailLabelType.all,
            destinations: [
              for (final item in items)
                NavigationRailDestination(
                  icon: Icon(item.icon),
                  label: Text(item.label),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 窄屏底部导航（4 项，文字标签必填）。
final class AppBottomNav extends StatelessWidget {
  /// 创建底部导航。
  const AppBottomNav({
    required this.currentIndex,
    required this.onSelect,
    super.key,
  });

  /// 当前分支索引。
  final int currentIndex;

  /// 选中分支。
  final void Function(int index) onSelect;

  @override
  Widget build(BuildContext context) {
    final items = bottomNavItems();
    return NavigationBar(
      selectedIndex: currentIndex,
      onDestinationSelected: onSelect,
      destinations: [
        for (final item in items)
          NavigationDestination(icon: Icon(item.icon), label: item.label),
      ],
    );
  }
}
