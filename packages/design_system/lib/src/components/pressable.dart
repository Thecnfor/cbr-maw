import 'package:flutter/services.dart';
import 'package:material_ui/material_ui.dart';

import '../tokens/colors.dart';
import '../tokens/tokens.dart';

/// 可点击元素的统一底座：焦点环 + 键盘激活 + 命中区 + 语义标签。
///
/// 焦点样式不依赖 hover（docs/07 §5.3）：环用 `focus.ring` 2dp，四周预留
/// 2dp 间隙，避免出现时推动布局。
class CbrPressable extends StatefulWidget {
  const CbrPressable({
    super.key,
    required this.child,
    this.onPressed,
    this.semanticLabel,
    this.semanticSelected,
    this.semanticExpanded,
    this.tooltip,
    this.minTapTarget = 0,
    this.borderRadius = CbrRadius.mdAll,
    this.background,
    this.padding = EdgeInsets.zero,
    this.mouseCursor,
  });

  final Widget child;
  final VoidCallback? onPressed;

  /// 图标按钮必须给中文 label（docs/07 §5.4）。
  final String? semanticLabel;
  final bool? semanticSelected;
  final bool? semanticExpanded;
  final String? tooltip;
  final double minTapTarget;
  final BorderRadius borderRadius;
  final Color? background;
  final EdgeInsetsGeometry padding;
  final MouseCursor? mouseCursor;

  @override
  State<CbrPressable> createState() => _CbrPressableState();
}

class _CbrPressableState extends State<CbrPressable> {
  bool _focused = false;
  bool _hovered = false;
  bool _pressed = false;

  bool get _enabled => widget.onPressed != null;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final Color? bg = _pressed
        ? palette.surfaceHover
        : _hovered
        ? palette.surfaceHover
        : widget.background;

    Widget content = AnimatedContainer(
      duration: CbrMotion.fast,
      curve: CbrMotion.easeStandard,
      constraints: BoxConstraints(
        minWidth: widget.minTapTarget,
        minHeight: widget.minTapTarget,
      ),
      padding: widget.padding,
      decoration: BoxDecoration(
        color: bg,
        borderRadius: widget.borderRadius,
        border: Border.all(
          color: _focused ? palette.focusRing : Colors.transparent,
          width: CbrBorder.focus,
        ),
      ),
      child: Opacity(opacity: _enabled ? 1 : 0.5, child: widget.child),
    );

    content = Semantics(
      button: true,
      enabled: _enabled,
      label: widget.semanticLabel,
      selected: widget.semanticSelected,
      expanded: widget.semanticExpanded,
      excludeSemantics: widget.semanticLabel != null,
      child: content,
    );

    if (widget.tooltip != null) {
      content = Tooltip(message: widget.tooltip!, child: content);
    }

    // 环与内容之间留 2dp：用外层 padding 承载，避免焦点出现时布局跳动。
    content = Padding(
      padding: const EdgeInsets.all(CbrBorder.focusOffset),
      child: content,
    );

    return FocusableActionDetector(
      enabled: _enabled,
      mouseCursor: _enabled
          ? (widget.mouseCursor ?? SystemMouseCursors.click)
          : SystemMouseCursors.basic,
      shortcuts: const <ShortcutActivator, Intent>{
        SingleActivator(LogicalKeyboardKey.enter): ActivateIntent(),
        SingleActivator(LogicalKeyboardKey.space): ActivateIntent(),
      },
      actions: <Type, Action<Intent>>{
        ActivateIntent: CallbackAction<ActivateIntent>(
          onInvoke: (_) {
            widget.onPressed?.call();
            return null;
          },
        ),
      },
      onShowHoverHighlight: (v) => setState(() => _hovered = v),
      onShowFocusHighlight: (v) => setState(() => _focused = v),
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onTapDown: _enabled ? (_) => setState(() => _pressed = true) : null,
        onTapCancel: _enabled ? () => setState(() => _pressed = false) : null,
        onTap: _enabled
            ? () {
                setState(() => _pressed = false);
                widget.onPressed!.call();
              }
            : null,
        child: content,
      ),
    );
  }
}

/// 图标按钮：必须有中文语义标签与 Tooltip（docs/06 §5.3）。
class CbrIconButton extends StatelessWidget {
  const CbrIconButton({
    super.key,
    required this.icon,
    required this.label,
    this.onPressed,
    this.selected = false,
    this.size = CbrIconSize.md,
    this.minTapTarget = 32,
    this.color,
  });

  final IconData icon;
  final String label;
  final VoidCallback? onPressed;
  final bool selected;
  final double size;
  final double minTapTarget;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return CbrPressable(
      onPressed: onPressed,
      semanticLabel: label,
      semanticSelected: selected,
      tooltip: label,
      minTapTarget: minTapTarget,
      borderRadius: CbrRadius.smAll,
      background: selected ? palette.surfaceHover : null,
      child: Icon(
        icon,
        size: size,
        color: onPressed == null
            ? palette.textDisabled
            : (color ??
                  (selected ? palette.textPrimary : palette.textSecondary)),
      ),
    );
  }
}
