import 'package:cbr_maw_design_system/cbr_maw_design_system.dart'
    show CbrLayoutBuilder;
import 'package:go_router/go_router.dart';

import '../ui.dart';
import '../layout/breakpoints.dart';
import '../routes.dart';
import '../shell/app_sidebar.dart';
import '../shell/app_top_bar.dart';
import '../shell/command_palette.dart';
import '../widgets/synthetic.dart';

/// 应用外壳：自适应导航 + 顶栏 + 内容区（docs/06 §6.1、docs/07 §1.2）。
///
/// - compact：底部导航（4 项）；
/// - medium / expanded：NavigationRail 72dp；
/// - large 及以上：侧栏 248dp，可折叠为 64dp（用户偏好持久化）。
final class AppShell extends StatefulWidget {
  /// 创建外壳。
  const AppShell({
    required this.navigationShell,
    required this.collapsed,
    required this.onToggleCollapsed,
    required this.onOpenPalette,
    required this.kernelStateLabel,
    required this.kernelReady,
    this.clock,
    this.sidebarFooter,
    this.synthetic = false,
    this.pendingInbox = 0,
    super.key,
  });

  /// go_router 的分支壳。
  final StatefulNavigationShell navigationShell;

  /// 侧栏是否折叠。
  final bool collapsed;

  /// 切换折叠。
  final ValueChanged<bool> onToggleCollapsed;

  /// 打开命令面板。
  final VoidCallback onOpenPalette;

  /// 内核状态文案。
  final String kernelStateLabel;

  /// 内核是否就绪。
  final bool kernelReady;

  /// 时钟文案。
  final String? clock;

  /// 侧栏底部状态区。
  final Widget? sidebarFooter;

  /// 是否处于 SYNTHETIC 数据模式（决定是否显示全局标记条）。
  final bool synthetic;

  /// 投递箱待处理条目数（侧栏角标）。
  final int pendingInbox;

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  final _mainFocus = FocusNode(debugLabel: 'main-content');

  @override
  void dispose() {
    _mainFocus.dispose();
    super.dispose();
  }

  void _go(String path) {
    final index = Routes.branches.indexOf(path);
    if (index >= 0) {
      widget.navigationShell.goBranch(index);
      return;
    }
    // 非分支页面：交给外层 router（由装配处注入）。
    AppShellNavigator.go(path);
  }

  @override
  Widget build(BuildContext context) {
    // 用 CbrLayoutBuilder 而不是裸 LayoutBuilder：设计系统组件靠
    // CbrBreakpointScope 取内容宽度断点，缺了它图表等组件会回退到
    // MediaQuery 的全窗宽（docs/07 §3.3 明确禁止）。
    return CbrLayoutBuilder(
      builder: (context, _, constraints) {
        final breakpoint = Breakpoint.of(constraints.maxWidth);
        final layout = NavLayout.forBreakpoint(breakpoint);
        final compact = breakpoint == Breakpoint.compact;
        final rawLocation = GoRouterState.of(context).uri.path;
        final location = rawLocation.isEmpty ? Routes.overview : rawLocation;

        final content = Column(
          children: [
            AppTopBar(
              location: location,
              kernelStateLabel: widget.kernelStateLabel,
              kernelReady: widget.kernelReady,
              onOpenPalette: widget.onOpenPalette,
              compact: compact,
              clock: widget.clock,
            ),
            if (widget.synthetic) const SyntheticTopBar(),
            Expanded(child: widget.navigationShell),
          ],
        );

        return Scaffold(
          body: Row(
            children: [
              if (layout == NavLayout.sidebar)
                AppSidebar(
                  currentLocation: location,
                  collapsed: widget.collapsed,
                  onSelect: _go,
                  onToggleCollapsed: () =>
                      widget.onToggleCollapsed(!widget.collapsed),
                  footer: widget.sidebarFooter,
                  pendingInbox: widget.pendingInbox,
                ),
              if (layout == NavLayout.rail)
                AppRail(currentLocation: location, onSelect: _go),
              Expanded(
                child: Semantics(
                  container: true,
                  label: '主内容',
                  // 焦点顺序：跳到主内容 → 导航 → 顶栏 → 主内容（docs/07 §5.3）。
                  child: Column(
                    children: [
                      _SkipToContentLink(
                        onActivate: () => _mainFocus.requestFocus(),
                      ),
                      Expanded(
                        child: Focus(focusNode: _mainFocus, child: content),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          bottomNavigationBar: layout == NavLayout.bottomBar
              ? AppBottomNav(
                  currentIndex: widget.navigationShell.currentIndex,
                  onSelect: (index) => widget.navigationShell.goBranch(
                    index,
                    initialLocation: false,
                  ),
                )
              : null,
        );
      },
    );
  }
}

/// 让 shell 内部也能跳转到非分支页面（由 router 注入）。
final class AppShellNavigator {
  const AppShellNavigator._();

  static void Function(String path)? _handler;

  /// 注册跳转处理器（router 装配时设置）。
  static void register(void Function(String path) handler) {
    _handler = handler;
  }

  /// 按路径跳转。
  static void go(String path) {
    _handler?.call(path);
  }
}

/// 命令面板打开辅助（外壳与快捷键共用）。
Future<void> openCommandPalette(BuildContext context) =>
    CommandPalette.show(context, onSelect: AppShellNavigator.go);

/// 「跳到主内容」链接：桌面可见，键盘第一站（docs/07 §5.3）。
final class _SkipToContentLink extends StatelessWidget {
  const _SkipToContentLink({required this.onActivate});

  final VoidCallback onActivate;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '跳到主内容',
      child: SizedBox(
        height: 0,
        child: OverflowBox(
          alignment: Alignment.centerLeft,
          maxHeight: 32,
          child: Focus(
            canRequestFocus: true,
            onFocusChange: (focused) {
              if (focused) {
                onActivate();
              }
            },
            child: Padding(
              padding: const EdgeInsets.only(left: 8),
              child: TextButton(
                onPressed: onActivate,
                child: const Text('跳到主内容'),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
