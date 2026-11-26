/// 响应式断点（docs/07 §1.1，单位 dp，按内容宽度判定）。
enum Breakpoint {
  /// < 600。
  compact(0, '紧凑'),

  /// 600–839。
  medium(600, '中等'),

  /// 840–1099。
  expanded(840, '展开'),

  /// 1100–1439。
  large(1100, '大'),

  /// 1440–1919。
  xlarge(1440, '特大'),

  /// ≥ 1920。
  xxlarge(1920, '超大');

  const Breakpoint(this.minWidth, this.label);

  /// 该档位的最小内容宽度。
  final double minWidth;

  /// 中文标签。
  final String label;

  /// 按内容宽度取档位。
  static Breakpoint of(double width) {
    var result = Breakpoint.compact;
    for (final value in values) {
      if (width >= value.minWidth) {
        result = value;
      }
    }
    return result;
  }
}

/// 导航形态（由断点推导，不依赖设备类型）。
enum NavLayout {
  /// 底部导航（4 项）。
  bottomBar,

  /// 左侧 NavigationRail 72dp。
  rail,

  /// 侧栏展开 248dp，可折叠为 64–72dp。
  sidebar;

  /// 由断点推导。
  static NavLayout forBreakpoint(Breakpoint breakpoint) => switch (breakpoint) {
    Breakpoint.compact => NavLayout.bottomBar,
    Breakpoint.medium || Breakpoint.expanded => NavLayout.rail,
    Breakpoint.large ||
    Breakpoint.xlarge ||
    Breakpoint.xxlarge => NavLayout.sidebar,
  };
}

/// 导航尺寸常量。
abstract final class NavMetrics {
  /// 侧栏展开宽度。
  static const double sidebarWidth = 248;

  /// 侧栏折叠宽度（large 及以上 64，expanded 72）。
  static const double sidebarCollapsedWidth = 64;

  /// Rail 宽度。
  static const double railWidth = 72;

  /// 展开态顶栏高度。
  static const double topBarHeight = 52;

  /// 精简态顶栏高度。
  static const double compactTopBarHeight = 56;

  /// 检视区常驻宽度。
  static const double inspectorWidth = 380;
}

/// 导航折叠偏好（持久化键 `ui.nav_collapsed`）。
final class NavPreferences {
  const NavPreferences({required this.collapsed});

  /// 默认值：展开。
  static const NavPreferences defaults = NavPreferences(collapsed: false);

  /// 用户是否把侧栏折叠。
  final bool collapsed;

  /// 持久化键。
  static const String storageKey = 'ui.nav_collapsed';

  /// 复制。
  NavPreferences copyWith({bool? collapsed}) =>
      NavPreferences(collapsed: collapsed ?? this.collapsed);
}
