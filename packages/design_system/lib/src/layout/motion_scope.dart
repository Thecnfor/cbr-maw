import 'package:flutter/widgets.dart';

/// `prefers-reduced-motion` 的唯一入口（docs/06 §7.3）。
///
/// 业务代码**禁止**直接写裸 `Duration(milliseconds: …)`；一律经 [CbrMotionScope]。
class CbrMotionScope extends InheritedWidget {
  const CbrMotionScope({
    super.key,
    required this.disableAnimations,
    required super.child,
  });

  /// 通常取 `MediaQuery.disableAnimationsOf(context)`。
  final bool disableAnimations;

  static CbrMotionScope? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<CbrMotionScope>();

  /// 减少动画开启时，所有时长解析为 [Duration.zero]。
  static Duration duration(BuildContext context, Duration duration) =>
      (maybeOf(context)?.disableAnimations ?? false) ? Duration.zero : duration;

  @override
  bool updateShouldNotify(CbrMotionScope oldWidget) =>
      oldWidget.disableAnimations != disableAnimations;
}
