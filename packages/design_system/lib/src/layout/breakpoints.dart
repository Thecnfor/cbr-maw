import 'package:flutter/widgets.dart';

/// 内容宽度断点（docs/07 §1.1）。
///
/// 按 [LayoutBuilder] 的 `constraints.maxWidth` 判定，不读屏幕物理尺寸，
/// 窗口缩放或内嵌视图时实时重算。
enum CbrBreakpoint {
  /// `< 600`：手机竖屏。
  compact,

  /// `600 – 839`：手机横屏、小平板。
  medium,

  /// `840 – 1099`：平板。
  expanded,

  /// `1100 – 1439`：笔记本。
  large,

  /// `1440 – 1919`：宽屏。
  xlarge,

  /// `≥ 1920`：2K/4K。
  xxlarge;

  static const double xs = 600;
  static const double sm = 840;
  static const double md = 1100;
  static const double lg = 1440;
  static const double xl = 1920;

  static CbrBreakpoint fromWidth(double width) {
    if (width < xs) return compact;
    if (width < sm) return medium;
    if (width < md) return expanded;
    if (width < lg) return large;
    if (width < xl) return xlarge;
    return xxlarge;
  }

  bool get isCompact => this == compact;
  bool get isMedium => this == medium;

  /// `≥ 840`：双栏布局起始。
  bool get atLeastExpanded => index >= expanded.index;

  /// `≥ 1100`：侧栏展开、三栏起始。
  bool get atLeastLarge => index >= large.index;

  /// `≥ 1440`：检视区常驻第三栏。
  bool get hasPersistentInspector => index >= xlarge.index;

  /// 导航形态（docs/07 §1.2）。
  CbrNavMode get navMode => switch (this) {
    compact => CbrNavMode.bottomBar,
    medium || expanded => CbrNavMode.rail,
    large || xlarge || xxlarge => CbrNavMode.sidebar,
  };

  /// 页面左右边距（docs/06 §4.1 规则 + docs/07 §1.2）。
  double get pageGutter => switch (this) {
    compact => 12,
    medium => 16,
    expanded || large => 20,
    xlarge || xxlarge => 32,
  };

  /// 内容列数上限（docs/07 §1.2）。
  int get maxColumns => switch (this) {
    compact || medium => 1,
    expanded || large => 2,
    xlarge || xxlarge => 3,
  };

  /// 顶栏高度（docs/07 §1.2）。
  double get topBarHeight => atLeastLarge ? 52 : 56;

  /// 表格行高（docs/07 §3.2）。
  double get tableRowHeight => switch (this) {
    compact || medium => 44,
    expanded => 40,
    large || xlarge || xxlarge => 36,
  };

  /// 图表高度：`clamp(0.42 × 宽度, 下限, 上限)`（docs/07 §3.3）。
  double chartHeight(double containerWidth) {
    final double min = isCompact ? 200 : 220;
    final double max = this == xxlarge ? 440 : 420;
    return (containerWidth * 0.42).clamp(min, max);
  }

  /// 检视区形态（docs/07 §1.2）。
  CbrInspectorMode get inspectorMode => switch (this) {
    compact || medium => CbrInspectorMode.fullScreen,
    expanded => CbrInspectorMode.overlayWide,
    large => CbrInspectorMode.overlay,
    xlarge || xxlarge => CbrInspectorMode.persistent,
  };
}

/// 主导航形态（docs/07 §1.2）。
enum CbrNavMode { bottomBar, rail, sidebar }

/// 检视区形态（docs/07 §1.2）。
enum CbrInspectorMode { fullScreen, overlayWide, overlay, persistent }

/// 把当前断点与相关派生参数下发给子树。
class CbrBreakpointScope extends InheritedWidget {
  const CbrBreakpointScope({
    super.key,
    required this.breakpoint,
    required super.child,
  });

  final CbrBreakpoint breakpoint;

  static CbrBreakpoint of(BuildContext context) {
    final scope = context
        .dependOnInheritedWidgetOfExactType<CbrBreakpointScope>();
    assert(scope != null, 'CbrBreakpointScope 缺失：请用 CbrLayoutBuilder 包裹');
    return scope!.breakpoint;
  }

  /// 无 scope 时返回 null，供非关键路径探测。
  static CbrBreakpoint? maybeOf(BuildContext context) => context
      .dependOnInheritedWidgetOfExactType<CbrBreakpointScope>()
      ?.breakpoint;

  @override
  bool updateShouldNotify(CbrBreakpointScope oldWidget) =>
      oldWidget.breakpoint != breakpoint;
}

/// 按内容宽度算断点并下发 [CbrBreakpointScope]。
///
/// 所有响应式布局都应从它取宽度，不要用 `MediaQuery.sizeOf(context).width`
/// （docs/07 §3.3：内嵌视图会取错）。
class CbrLayoutBuilder extends StatelessWidget {
  const CbrLayoutBuilder({super.key, required this.builder});

  final Widget Function(
    BuildContext context,
    CbrBreakpoint breakpoint,
    BoxConstraints constraints,
  )
  builder;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final breakpoint = CbrBreakpoint.fromWidth(constraints.maxWidth);
        return CbrBreakpointScope(
          breakpoint: breakpoint,
          child: builder(context, breakpoint, constraints),
        );
      },
    );
  }
}
