import 'dart:async';

import 'package:material_ui/material_ui.dart';

import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'icons.dart';
import 'pressable.dart';

enum CbrToastTone { success, error, info, undo }

/// Toast：停留 ≥4s，错误 ≥8s 且不自动消失（docs/06 §6.4）。
///
/// 用 [CbrToast.show] 弹出；不引入全局状态，保持最薄一层。
class CbrToast {
  const CbrToast._();

  static OverlayEntry? _current;
  static Timer? _timer;

  static void show(
    BuildContext context, {
    required String message,
    CbrToastTone tone = CbrToastTone.info,
    String? actionLabel,
    VoidCallback? onAction,
  }) {
    dismiss();
    final overlay = Overlay.of(context);
    final entry = OverlayEntry(
      builder: (context) => _ToastView(
        message: message,
        tone: tone,
        actionLabel: actionLabel,
        onAction: onAction,
        onDismiss: dismiss,
      ),
    );
    _current = entry;
    overlay.insert(entry);
    final Duration duration = switch (tone) {
      CbrToastTone.error => const Duration(seconds: 8),
      _ => const Duration(seconds: 4),
    };
    _timer = Timer(duration, dismiss);
  }

  static void dismiss() {
    _timer?.cancel();
    _timer = null;
    _current?.remove();
    _current = null;
  }
}

class _ToastView extends StatelessWidget {
  const _ToastView({
    required this.message,
    required this.tone,
    required this.onDismiss,
    this.actionLabel,
    this.onAction,
  });

  final String message;
  final CbrToastTone tone;
  final VoidCallback onDismiss;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final CbrStatusTone statusTone = switch (tone) {
      CbrToastTone.success => CbrStatusTone.ok,
      CbrToastTone.error => CbrStatusTone.danger,
      CbrToastTone.info => CbrStatusTone.info,
      CbrToastTone.undo => CbrStatusTone.warn,
    };
    final colors = palette.statusOf(statusTone);
    final IconData icon = switch (tone) {
      CbrToastTone.success => CbrIcons.success,
      CbrToastTone.error => CbrIcons.error,
      CbrToastTone.info => CbrIcons.info,
      CbrToastTone.undo => CbrIcons.retry,
    };
    return Positioned(
      left: CbrSpace.s5,
      right: CbrSpace.s5,
      bottom: CbrSpace.s5,
      child: Align(
        alignment: Alignment.bottomCenter,
        child: Semantics(
          liveRegion: true,
          label: message,
          child: Container(
            constraints: const BoxConstraints(maxWidth: 560),
            padding: const EdgeInsets.symmetric(
              horizontal: CbrSpace.s4,
              vertical: CbrSpace.s3,
            ),
            decoration: BoxDecoration(
              color: palette.surfaceRaised,
              borderRadius: CbrRadius.mdAll,
              border: Border.all(
                color: colors.ink.withValues(alpha: 0.28),
                width: CbrBorder.hairline,
              ),
              boxShadow: CbrElevation.forBrightness(palette.brightness, 3),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: <Widget>[
                Icon(icon, size: CbrIconSize.md, color: colors.ink),
                const SizedBox(width: CbrSpace.s3),
                Flexible(
                  child: Text(
                    message,
                    style: CbrType.body.copyWith(color: palette.textPrimary),
                  ),
                ),
                if (actionLabel != null) ...<Widget>[
                  const SizedBox(width: CbrSpace.s3),
                  TextButton(onPressed: onAction, child: Text(actionLabel!)),
                ],
                CbrIconButton(
                  icon: CbrIcons.close,
                  label: '关闭提示',
                  size: CbrIconSize.sm,
                  onPressed: onDismiss,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
