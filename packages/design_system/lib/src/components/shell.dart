import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../layout/breakpoints.dart';
import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'badges.dart';
import 'icons.dart';
import 'navigation.dart';
import 'pressable.dart';

/// 应用外壳：侧栏 + 顶栏 + 内容区三段式（docs/06 §6.1、docs/07 §1.2）。
///
/// - 导航形态按内容宽度自动切换：`compact` 底部导航 / `medium`·`expanded`
///   Rail 72dp / `large` 以上侧栏 248dp（可折叠 64dp）。
/// - 检视区常驻与否由 [inspector] 与断点共同决定，调用方决定何时打开。
class CbrAppShell extends StatefulWidget {
  const CbrAppShell({
    super.key,
    required this.navItems,
    required this.selectedNavId,
    required this.onSelectNav,
    required this.breadcrumbs,
    required this.body,
    this.navCollapsed = false,
    this.onToggleNavCollapsed,
    this.statusLabel,
    this.statusTone = CbrStatusTone.ok,
    this.statusGlowing = false,
    this.topBarActions = const <Widget>[],
    this.onSearch,
    this.onCommand,
    this.onToggleTheme,
    this.themeIsDark = false,
    this.inspector,
    this.navFooter,
  });

  final List<CbrNavItem> navItems;
  final String selectedNavId;
  final ValueChanged<String> onSelectNav;
  final List<String> breadcrumbs;
  final Widget body;
  final bool navCollapsed;
  final VoidCallback? onToggleNavCollapsed;
  final String? statusLabel;
  final CbrStatusTone statusTone;
  final bool statusGlowing;
  final List<Widget> topBarActions;
  final VoidCallback? onSearch;
  final VoidCallback? onCommand;
  final VoidCallback? onToggleTheme;
  final bool themeIsDark;
  final Widget? inspector;
  final Widget? navFooter;

  @override
  State<CbrAppShell> createState() => _CbrAppShellState();
}

class _CbrAppShellState extends State<CbrAppShell> {
  final FocusNode _skipFocus = FocusNode(debugLabel: 'skip-to-content');

  @override
  void dispose() {
    _skipFocus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return CbrLayoutBuilder(
      builder: (context, breakpoint, constraints) {
        final CbrNavMode navMode = breakpoint.navMode;
        final bool bottomNav = navMode == CbrNavMode.bottomBar;
        final bool rail = navMode == CbrNavMode.rail;

        final Widget topBar = CbrTopBar(
          breadcrumbs: widget.breadcrumbs,
          statusLabel: widget.statusLabel,
          statusTone: widget.statusTone,
          statusGlowing: widget.statusGlowing,
          actions: widget.topBarActions,
          onSearch: widget.onSearch,
          onCommand: widget.onCommand,
          onToggleTheme: widget.onToggleTheme,
          themeIsDark: widget.themeIsDark,
        );

        final Widget main = Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            if (widget.inspector != null && breakpoint.hasPersistentInspector)
              Expanded(child: widget.body),
            if (widget.inspector != null && breakpoint.hasPersistentInspector)
              SizedBox(
                width: CbrLayout.inspectorAnchored,
                child: widget.inspector,
              ),
            if (widget.inspector == null || !breakpoint.hasPersistentInspector)
              Expanded(child: widget.body),
          ],
        );

        final Widget contentColumn = Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: <Widget>[
            // 跳转链接：桌面可见，移动端为屏幕阅读器可聚焦的隐藏按钮。
            _SkipToContent(focusNode: _skipFocus, visible: !bottomNav),
            topBar,
            Expanded(child: main),
          ],
        );

        if (bottomNav) {
          return Scaffold(
            backgroundColor: palette.surfaceSunken,
            body: contentColumn,
            bottomNavigationBar: CbrMobileNavBar(
              items: widget.navItems,
              selectedId: widget.selectedNavId,
              onSelect: widget.onSelectNav,
            ),
          );
        }

        return Scaffold(
          backgroundColor: palette.surfaceSunken,
          body: Row(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: <Widget>[
              CbrSideNav(
                items: widget.navItems,
                selectedId: widget.selectedNavId,
                onSelect: widget.onSelectNav,
                rail: rail,
                collapsed: widget.navCollapsed,
                footer: widget.navFooter,
              ),
              Expanded(child: contentColumn),
            ],
          ),
        );
      },
    );
  }
}

class _SkipToContent extends StatelessWidget {
  const _SkipToContent({required this.focusNode, required this.visible});

  final FocusNode focusNode;
  final bool visible;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Semantics(
      button: true,
      label: '跳到主内容',
      child: visible
          ? SizedBox(
              height: 0,
              child: OverflowBox(
                maxHeight: 48,
                alignment: Alignment.centerLeft,
                child: _button(palette),
              ),
            )
          : SizedBox(
              height: 0,
              child: Focus(
                focusNode: focusNode,
                child: const SizedBox.shrink(),
              ),
            ),
    );
  }

  Widget _button(CbrPalette palette) => CbrPressable(
    semanticLabel: '跳到主内容',
    onPressed: () {},
    minTapTarget: 32,
    child: Text(
      '跳到主内容',
      style: CbrType.label.copyWith(color: palette.textSecondary),
    ),
  );
}

/// 命令面板外壳（docs/06 §6.1）：焦点陷阱 + Esc 关闭并归还焦点。
///
/// 只负责外观与键盘约定；搜索逻辑由调用方注入。
class CbrCommandPalette extends StatelessWidget {
  const CbrCommandPalette({
    super.key,
    required this.onClose,
    required this.child,
    this.hintText = '搜索或输入命令',
  });

  final VoidCallback onClose;
  final Widget child;
  final String hintText;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final CbrBreakpoint breakpoint = CbrBreakpointScope.of(context);
    final double width = breakpoint.atLeastLarge
        ? CbrLayout.commandPaletteWide
        : CbrLayout.commandPalette;

    return CallbackShortcuts(
      bindings: <ShortcutActivator, VoidCallback>{
        const SingleActivator(LogicalKeyboardKey.escape): onClose,
      },
      child: Stack(
        children: <Widget>[
          Positioned.fill(
            child: GestureDetector(
              onTap: onClose,
              child: ColoredBox(color: palette.surfaceOverlay),
            ),
          ),
          Center(
            child: FocusScope(
              autofocus: true,
              child: Container(
                width: width,
                constraints: const BoxConstraints(maxHeight: 480),
                decoration: BoxDecoration(
                  color: palette.surfaceRaised,
                  borderRadius: CbrRadius.xlAll,
                  border: Border.all(
                    color: palette.borderDefault,
                    width: CbrBorder.hairline,
                  ),
                  boxShadow: CbrElevation.forBrightness(palette.brightness, 4),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: <Widget>[
                    Padding(
                      padding: const EdgeInsets.all(CbrSpace.s4),
                      child: Row(
                        children: <Widget>[
                          Icon(
                            CbrIcons.search,
                            size: CbrIconSize.md,
                            color: palette.textSecondary,
                          ),
                          const SizedBox(width: CbrSpace.s3),
                          Expanded(
                            child: TextField(
                              autofocus: true,
                              decoration: InputDecoration(
                                hintText: hintText,
                                border: InputBorder.none,
                                enabledBorder: InputBorder.none,
                                focusedBorder: InputBorder.none,
                                filled: false,
                              ),
                              style: CbrType.body.copyWith(
                                color: palette.textPrimary,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    Divider(
                      color: palette.borderSubtle,
                      height: CbrBorder.hairline,
                    ),
                    Flexible(child: child),
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 确认卡（docs/06 §6.3 `ApprovalCard`、docs/08 §4.2）。
///
/// 标题用「动词 + 对象」；正文首行按动作风险级给固定措辞；主按钮文案具体，
/// 不用「确定 / OK」。
class CbrApprovalCard extends StatelessWidget {
  const CbrApprovalCard({
    super.key,
    required this.title,
    required this.risk,
    required this.body,
    required this.confirmLabel,
    this.cancelLabel = '取消',
    this.onConfirm,
    this.onCancel,
  });

  final String title;
  final CbrActionRisk risk;
  final List<String> body;
  final String confirmLabel;
  final String cancelLabel;
  final VoidCallback? onConfirm;
  final VoidCallback? onCancel;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final String lead = switch (risk) {
      CbrActionRisk.highRisk => '高风险操作：',
      CbrActionRisk.confirmRequired => '此操作会修改本地数据。',
      CbrActionRisk.viewOnly => '',
    };
    return Container(
      padding: const EdgeInsets.all(CbrSpace.s6),
      decoration: BoxDecoration(
        color: palette.surfaceRaised,
        borderRadius: CbrRadius.lgAll,
        border: Border.all(
          color: palette.borderDefault,
          width: CbrBorder.hairline,
        ),
        boxShadow: CbrElevation.forBrightness(palette.brightness, 3),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  title,
                  style: CbrType.headline2.copyWith(color: palette.textPrimary),
                ),
              ),
              CbrActionRiskBadge(risk: risk),
            ],
          ),
          const SizedBox(height: CbrSpace.s4),
          if (lead.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: CbrSpace.s2),
              child: Text(
                lead,
                style: CbrType.bodyStrong.copyWith(
                  color: risk == CbrActionRisk.highRisk
                      ? palette.statusOf(CbrStatusTone.danger).ink
                      : palette.textPrimary,
                ),
              ),
            ),
          for (final line in body)
            Padding(
              padding: const EdgeInsets.only(bottom: CbrSpace.s2),
              child: Text(
                line,
                style: CbrType.body.copyWith(color: palette.textSecondary),
              ),
            ),
          const SizedBox(height: CbrSpace.s4),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: <Widget>[
              TextButton(onPressed: onCancel, child: Text(cancelLabel)),
              const SizedBox(width: CbrSpace.s3),
              FilledButton(onPressed: onConfirm, child: Text(confirmLabel)),
            ],
          ),
        ],
      ),
    );
  }
}
