import 'package:material_ui/material_ui.dart';

import '../layout/breakpoints.dart';
import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'badges.dart';
import 'icons.dart';
import 'pressable.dart';

/// 主导航项。
@immutable
class CbrNavItem {
  const CbrNavItem({
    required this.id,
    required this.label,
    required this.icon,
    this.badgeCount,
    this.enabled = true,
  });

  final String id;
  final String label;
  final IconData icon;
  final int? badgeCount;
  final bool enabled;
}

/// 侧栏 / Rail 导航（docs/06 §6.1、docs/07 §1.2）。
///
/// 展开 248dp、折叠 64dp；Rail 固定 72dp。折叠态仍靠 Tooltip + Semantics
/// 给出完整名称，徽标朗读为「〈名称〉，N 条未读」。
class CbrSideNav extends StatelessWidget {
  const CbrSideNav({
    super.key,
    required this.items,
    required this.selectedId,
    required this.onSelect,
    this.collapsed = false,
    this.rail = false,
    this.footer,
  });

  final List<CbrNavItem> items;
  final String selectedId;
  final ValueChanged<String> onSelect;
  final bool collapsed;

  /// 600–1099 的 `NavigationRail` 形态：只有图标，宽度 72dp。
  final bool rail;
  final Widget? footer;

  double get _width => rail
      ? CbrLayout.railWidth
      : collapsed
      ? CbrLayout.sidebarCollapsed
      : CbrLayout.sidebarExpanded;

  bool get _iconsOnly => rail || collapsed;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Semantics(
      container: true,
      explicitChildNodes: true,
      label: '主导航',
      child: Container(
        width: _width,
        decoration: BoxDecoration(
          color: palette.surfaceBase,
          border: Border(
            right: BorderSide(
              color: palette.borderSubtle,
              width: CbrBorder.hairline,
            ),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            const SizedBox(height: CbrSpace.s4),
            Expanded(
              child: ListView(
                padding: const EdgeInsets.symmetric(horizontal: CbrSpace.s3),
                children: <Widget>[
                  for (final item in items)
                    _NavEntry(
                      item: item,
                      selected: item.id == selectedId,
                      iconsOnly: _iconsOnly,
                      onSelect: onSelect,
                    ),
                ],
              ),
            ),
            if (footer != null)
              Padding(
                padding: const EdgeInsets.all(CbrSpace.s4),
                child: footer,
              ),
          ],
        ),
      ),
    );
  }
}

class _NavEntry extends StatelessWidget {
  const _NavEntry({
    required this.item,
    required this.selected,
    required this.iconsOnly,
    required this.onSelect,
  });

  final CbrNavItem item;
  final bool selected;
  final bool iconsOnly;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final Color fg = !item.enabled
        ? palette.textDisabled
        : selected
        ? palette.textPrimary
        : palette.textSecondary;
    final String semanticsLabel = item.badgeCount == null
        ? item.label
        : '${item.label}，${item.badgeCount} 条未读';

    final Widget row = Container(
      height: 36,
      margin: const EdgeInsets.only(bottom: CbrSpace.s1),
      padding: EdgeInsets.symmetric(horizontal: iconsOnly ? 0 : CbrSpace.s3),
      decoration: BoxDecoration(
        color: selected ? palette.surfaceHover : null,
        borderRadius: CbrRadius.smAll,
      ),
      child: Row(
        mainAxisAlignment: iconsOnly
            ? MainAxisAlignment.center
            : MainAxisAlignment.start,
        children: <Widget>[
          Stack(
            clipBehavior: Clip.none,
            children: <Widget>[
              Icon(item.icon, size: CbrIconSize.md, color: fg),
              if (iconsOnly && item.badgeCount != null)
                Positioned(top: -2, right: -2, child: _CountDot()),
            ],
          ),
          if (!iconsOnly) ...<Widget>[
            const SizedBox(width: CbrSpace.s3),
            Expanded(
              child: Text(
                item.label,
                overflow: TextOverflow.ellipsis,
                style: (selected ? CbrType.labelStrong : CbrType.label)
                    .copyWith(color: fg),
              ),
            ),
            if (item.badgeCount != null) _CountBadge(count: item.badgeCount!),
          ],
        ],
      ),
    );

    return Semantics(
      selected: selected,
      enabled: item.enabled,
      label: semanticsLabel,
      excludeSemantics: true,
      child: Tooltip(
        message: iconsOnly ? item.label : '',
        waitDuration: const Duration(milliseconds: 400),
        child: CbrPressable(
          onPressed: item.enabled ? () => onSelect(item.id) : null,
          semanticLabel: semanticsLabel,
          semanticSelected: selected,
          borderRadius: CbrRadius.smAll,
          child: row,
        ),
      ),
    );
  }
}

class _CountBadge extends StatelessWidget {
  const _CountBadge({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: CbrSpace.s2, vertical: 1),
      decoration: BoxDecoration(
        color: palette.statusOf(CbrStatusTone.info).tint,
        borderRadius: CbrRadius.pillAll,
      ),
      child: Text(
        '$count',
        style: CbrType.micro.copyWith(
          color: palette.statusOf(CbrStatusTone.info).ink,
        ),
      ),
    );
  }
}

class _CountDot extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Container(
      width: 6,
      height: 6,
      decoration: BoxDecoration(
        color: palette.statusOf(CbrStatusTone.info).solid,
        shape: BoxShape.circle,
      ),
    );
  }
}

/// 底部导航（compact，4 项；docs/07 §1.2）。
class CbrMobileNavBar extends StatelessWidget {
  const CbrMobileNavBar({
    super.key,
    required this.items,
    required this.selectedId,
    required this.onSelect,
  });

  final List<CbrNavItem> items;
  final String selectedId;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Semantics(
      container: true,
      explicitChildNodes: true,
      label: '主导航',
      child: Container(
        decoration: BoxDecoration(
          color: palette.surfaceBase,
          border: Border(
            top: BorderSide(
              color: palette.borderSubtle,
              width: CbrBorder.hairline,
            ),
          ),
        ),
        child: SafeArea(
          top: false,
          child: SizedBox(
            height: 56,
            child: Row(
              children: <Widget>[
                for (final item in items.take(4))
                  Expanded(
                    child: Semantics(
                      selected: item.id == selectedId,
                      label: item.label,
                      excludeSemantics: true,
                      child: CbrPressable(
                        onPressed: item.enabled
                            ? () => onSelect(item.id)
                            : null,
                        semanticLabel: item.label,
                        semanticSelected: item.id == selectedId,
                        minTapTarget: CbrLayout.touchTarget,
                        borderRadius: CbrRadius.smAll,
                        child: Column(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: <Widget>[
                            Icon(
                              item.icon,
                              size: CbrIconSize.lg,
                              color: item.id == selectedId
                                  ? palette.textPrimary
                                  : palette.textSecondary,
                            ),
                            const SizedBox(height: CbrSpace.s1),
                            Text(
                              item.label,
                              style: CbrType.micro.copyWith(
                                color: item.id == selectedId
                                    ? palette.textPrimary
                                    : palette.textSecondary,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 顶栏（docs/06 §6.1、docs/07 §1.2）：面包屑 + 状态区 + 搜索 / 命令 / 主题。
class CbrTopBar extends StatelessWidget {
  const CbrTopBar({
    super.key,
    required this.breadcrumbs,
    this.statusLabel,
    this.statusTone = CbrStatusTone.ok,
    this.statusGlowing = false,
    this.actions = const <Widget>[],
    this.onSearch,
    this.onCommand,
    this.onToggleTheme,
    this.themeIsDark = false,
  });

  final List<String> breadcrumbs;

  /// 状态点必须朗读为文字，不得朗读为「绿点」（docs/07 §5.4）。
  final String? statusLabel;
  final CbrStatusTone statusTone;
  final bool statusGlowing;
  final List<Widget> actions;
  final VoidCallback? onSearch;
  final VoidCallback? onCommand;
  final VoidCallback? onToggleTheme;
  final bool themeIsDark;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final CbrBreakpoint breakpoint =
        CbrBreakpointScope.maybeOf(context) ??
        CbrBreakpoint.fromWidth(MediaQuery.sizeOf(context).width);
    final bool compact = breakpoint.isCompact;
    final String title = breadcrumbs.isEmpty ? '' : breadcrumbs.last;
    final String prefix = breadcrumbs.length > 1
        ? breadcrumbs.sublist(0, breadcrumbs.length - 1).join(' / ')
        : '';

    return Container(
      height: breakpoint.topBarHeight,
      padding: EdgeInsets.symmetric(horizontal: breakpoint.pageGutter),
      decoration: BoxDecoration(
        color: palette.surfaceBase,
        border: Border(
          bottom: BorderSide(
            color: palette.borderSubtle,
            width: CbrBorder.hairline,
          ),
        ),
      ),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Row(
              children: <Widget>[
                if (!compact && prefix.isNotEmpty) ...<Widget>[
                  Text(
                    prefix,
                    style: CbrType.caption.copyWith(
                      color: palette.textTertiary,
                    ),
                  ),
                  const SizedBox(width: CbrSpace.s2),
                  Icon(
                    CbrIcons.chevronRight,
                    size: CbrIconSize.xs,
                    color: palette.textTertiary,
                  ),
                  const SizedBox(width: CbrSpace.s2),
                ],
                Flexible(
                  child: Text(
                    title,
                    overflow: TextOverflow.ellipsis,
                    style: CbrType.title.copyWith(color: palette.textPrimary),
                  ),
                ),
              ],
            ),
          ),
          if (statusLabel != null && !compact) ...<Widget>[
            CbrStatusDot(
              tone: statusTone,
              label: statusLabel!,
              showLabel: true,
              glowing: statusGlowing,
            ),
            const SizedBox(width: CbrSpace.s5),
          ],
          if (onSearch != null)
            CbrIconButton(
              icon: CbrIcons.search,
              label: '搜索',
              onPressed: onSearch,
            ),
          if (onCommand != null)
            CbrIconButton(
              icon: CbrIcons.command,
              label: '命令面板',
              onPressed: onCommand,
            ),
          if (onToggleTheme != null)
            CbrIconButton(
              icon: themeIsDark ? CbrIcons.themeLight : CbrIcons.themeDark,
              label: themeIsDark ? '切换到浅色模式' : '切换到深色模式',
              onPressed: onToggleTheme,
            ),
          ...actions,
        ],
      ),
    );
  }
}

/// 面包屑导航（顶栏内的紧凑版；单行）。
class CbrBreadcrumbs extends StatelessWidget {
  const CbrBreadcrumbs({super.key, required this.items, this.onTap});

  final List<String> items;
  final ValueChanged<int>? onTap;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Wrap(
      crossAxisAlignment: WrapCrossAlignment.center,
      children: <Widget>[
        for (var i = 0; i < items.length; i++) ...<Widget>[
          if (i > 0)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: CbrSpace.s2),
              child: Icon(
                CbrIcons.chevronRight,
                size: CbrIconSize.xs,
                color: palette.textTertiary,
              ),
            ),
          if (onTap != null && i < items.length - 1)
            TextButton(onPressed: () => onTap!(i), child: Text(items[i]))
          else
            Text(
              items[i],
              style: i == items.length - 1
                  ? CbrType.title.copyWith(color: palette.textPrimary)
                  : CbrType.label.copyWith(color: palette.textSecondary),
            ),
        ],
      ],
    );
  }
}
