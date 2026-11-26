import 'package:material_ui/material_ui.dart';

import '../layout/breakpoints.dart';
import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'icons.dart';
import 'pressable.dart';

/// 检视区三态（docs/07 §1.2、§1.3）：常驻第三栏 / 覆盖式抽屉 / 全屏抽屉。
class CbrInspector extends StatelessWidget {
  const CbrInspector({
    super.key,
    required this.title,
    required this.child,
    required this.onClose,
    this.mode,
  });

  final String title;
  final Widget child;
  final VoidCallback onClose;

  /// 不传时按当前断点推导。
  final CbrInspectorMode? mode;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final CbrInspectorMode resolved =
        mode ??
        (CbrBreakpointScope.maybeOf(context) ??
                CbrBreakpoint.fromWidth(MediaQuery.sizeOf(context).width))
            .inspectorMode;
    final bool persistent = resolved == CbrInspectorMode.persistent;
    final double width = switch (resolved) {
      CbrInspectorMode.persistent => CbrLayout.inspectorAnchored,
      CbrInspectorMode.overlay => CbrLayout.inspectorAnchored,
      CbrInspectorMode.overlayWide => CbrLayout.inspectorOverlayWide,
      CbrInspectorMode.fullScreen => double.infinity,
    };

    final Widget panel = Container(
      width: width,
      color: palette.surfaceBase,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: <Widget>[
          Container(
            height: 48,
            padding: const EdgeInsets.symmetric(horizontal: CbrSpace.s4),
            decoration: BoxDecoration(
              border: Border(
                bottom: BorderSide(
                  color: palette.borderSubtle,
                  width: CbrBorder.hairline,
                ),
              ),
            ),
            child: Row(
              children: <Widget>[
                Icon(
                  CbrIcons.panelRight,
                  size: CbrIconSize.md,
                  color: palette.textSecondary,
                ),
                const SizedBox(width: CbrSpace.s3),
                Expanded(
                  child: Text(
                    title,
                    overflow: TextOverflow.ellipsis,
                    style: CbrType.title.copyWith(color: palette.textPrimary),
                  ),
                ),
                CbrIconButton(
                  icon: CbrIcons.close,
                  label: '关闭检视区',
                  onPressed: onClose,
                ),
              ],
            ),
          ),
          Expanded(
            child: Semantics(
              container: true,
              label: '检视区',
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(CbrSpace.s5),
                child: child,
              ),
            ),
          ),
        ],
      ),
    );

    if (persistent) {
      return DecoratedBox(
        decoration: BoxDecoration(
          border: Border(
            left: BorderSide(
              color: palette.borderSubtle,
              width: CbrBorder.hairline,
            ),
          ),
        ),
        child: panel,
      );
    }

    // 覆盖式 / 全屏：滑入，不挤压主区；焦点在关闭时归还（由调用方负责）。
    return FocusScope(
      child: Stack(
        children: <Widget>[
          Positioned.fill(
            child: GestureDetector(
              onTap: onClose,
              child: ColoredBox(color: palette.surfaceOverlay),
            ),
          ),
          Positioned(top: 0, right: 0, bottom: 0, child: panel),
        ],
      ),
    );
  }
}
