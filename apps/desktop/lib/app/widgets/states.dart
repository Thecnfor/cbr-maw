import 'package:cbr_maw_design_system/cbr_maw_design_system.dart'
    show CbrEmptyState, CbrInlineBanner, CbrStatusTone;

import '../ui.dart';
import '../theme/theme.dart';
import '../theme/tokens.dart';

/// 空态（图标 + 标题 + 说明 + 主动作）。
final class EmptyState extends StatelessWidget {
  /// 创建空态。
  const EmptyState({
    required this.title,
    required this.message,
    this.icon = Icons.inbox_outlined,
    this.actionLabel,
    this.onAction,
    super.key,
  });

  /// 标题。
  final String title;

  /// 说明。
  final String message;

  /// 图标。
  final IconData icon;

  /// 主动作文案。
  final String? actionLabel;

  /// 主动作回调。
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    // 转发到设计系统的空态：图标尺寸、间距、按钮样式与全站统一，
    // app 侧不再维护第二套（docs/12 P1-5 单一真源）。
    return CbrEmptyState(
      title: title,
      description: message,
      primaryActionLabel: actionLabel,
      onPrimaryAction: onAction,
    );
  }
}

/// 错误态（三段式文案 + 重试）。
final class ErrorStateView extends StatelessWidget {
  /// 创建错误态。
  const ErrorStateView({
    required this.what,
    required this.why,
    required this.next,
    this.onRetry,
    super.key,
  });

  /// 发生了什么。
  final String what;

  /// 为什么。
  final String why;

  /// 下一步。
  final String next;

  /// 重试。
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = SemanticColors.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Tokens.space6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline, size: 32, color: colors.dangerInk),
            const SizedBox(height: Tokens.space3),
            Text('$what。', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: Tokens.space1),
            Text(why, textAlign: TextAlign.center),
            const SizedBox(height: Tokens.space1),
            Text(
              next,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: Tokens.space4),
              OutlinedButton(onPressed: onRetry, child: const Text('重试')),
            ],
          ],
        ),
      ),
    );
  }
}

/// 「数据不可得（需授权）」状态：**不得出现任何占位数值**（docs/07 §6.2）。
final class AccessRequiredState extends StatelessWidget {
  /// 创建需授权态。
  const AccessRequiredState({
    required this.sourceName,
    required this.reason,
    this.actionLabel = '前往授权',
    this.onAction,
    this.icon = Icons.lock_outline,
    super.key,
  });

  /// 来源名。
  final String sourceName;

  /// 原因。
  final String reason;

  /// 主动作文案。
  final String actionLabel;

  /// 主动作。
  final VoidCallback? onAction;

  /// 图标（需授权锁 / 反爬盾牌）。
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final colors = SemanticColors.of(context);
    return Container(
      padding: const EdgeInsets.all(Tokens.space4),
      decoration: BoxDecoration(
        color: colors.warnTint,
        borderRadius: BorderRadius.circular(Tokens.radiusCard),
        border: Border.all(color: colors.warnInk.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: colors.warnInk, size: 20),
          const SizedBox(width: Tokens.space3),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '$sourceName 未授权',
                  style: TextStyle(
                    color: colors.warnInk,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: Tokens.space1),
                Text(reason),
              ],
            ),
          ),
          if (onAction != null)
            TextButton(onPressed: onAction, child: Text(actionLabel)),
        ],
      ),
    );
  }
}

/// 页内提示条（不可只靠颜色区分）。
final class InlineBanner extends StatelessWidget {
  /// 创建提示条。
  const InlineBanner({
    required this.message,
    this.tone = BannerTone.info,
    this.icon,
    super.key,
  });

  /// 文案。
  final String message;

  /// 语气。
  final BannerTone tone;

  /// 图标（缺省按语气取）。
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    // 转发到设计系统的提示条：语义色三态（solid/ink/tint）与对比度由
    // 设计系统保证，app 侧不再自绘。
    return CbrInlineBanner(message: message, tone: _tone(tone));
  }

  static CbrStatusTone _tone(BannerTone tone) => switch (tone) {
    BannerTone.info => CbrStatusTone.info,
    BannerTone.warn => CbrStatusTone.warn,
    BannerTone.error => CbrStatusTone.danger,
    BannerTone.ok => CbrStatusTone.ok,
  };
}

/// 提示条语气。
enum BannerTone {
  /// 提示。
  info,

  /// 警告。
  warn,

  /// 错误。
  error,

  /// 成功。
  ok,
}

/// 加载骨架块。
final class SkeletonBlock extends StatelessWidget {
  /// 创建骨架块。
  const SkeletonBlock({this.height = 16, this.width, super.key});

  /// 高。
  final double height;

  /// 宽（null = 撑满）。
  final double? width;

  @override
  Widget build(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return Container(
      height: height,
      width: width,
      decoration: BoxDecoration(
        color: isDark ? Tokens.n3d : Tokens.n3,
        borderRadius: BorderRadius.circular(Tokens.space1),
      ),
    );
  }
}

/// 状态标签（文字自足，不依赖颜色）。
final class StatusTag extends StatelessWidget {
  /// 创建标签。
  const StatusTag({
    required this.label,
    required this.tone,
    this.icon,
    super.key,
  });

  /// 文字。
  final String label;

  /// 语气。
  final BannerTone tone;

  /// 图标。
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final colors = SemanticColors.of(context);
    final (Color ink, Color tint) = switch (tone) {
      BannerTone.info => (colors.infoInk, colors.infoTint),
      BannerTone.warn => (colors.warnInk, colors.warnTint),
      BannerTone.error => (colors.dangerInk, colors.dangerTint),
      BannerTone.ok => (colors.okInk, colors.okTint),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: tint,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 13, color: ink),
            const SizedBox(width: 4),
          ],
          Text(label, style: TextStyle(fontSize: 12, color: ink, height: 1.4)),
        ],
      ),
    );
  }
}
