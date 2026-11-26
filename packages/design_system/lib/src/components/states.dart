import 'package:material_ui/material_ui.dart';

import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'badges.dart';
import 'icons.dart';
import 'pressable.dart';

/// 空态：图标 + 标题 + 说明 + 主动作（docs/06 §6.4）。
class CbrEmptyState extends StatelessWidget {
  const CbrEmptyState({
    super.key,
    required this.title,
    required this.description,
    this.primaryActionLabel,
    this.onPrimaryAction,
    this.secondaryActionLabel,
    this.onSecondaryAction,
    this.icon = CbrIcons.database,
  });

  final String title;
  final String description;
  final String? primaryActionLabel;
  final VoidCallback? onPrimaryAction;
  final String? secondaryActionLabel;
  final VoidCallback? onSecondaryAction;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return _StateBody(
      icon: icon,
      iconColor: palette.textTertiary,
      title: title,
      description: description,
      actions: <Widget>[
        if (primaryActionLabel != null)
          FilledButton(
            onPressed: onPrimaryAction,
            child: Text(primaryActionLabel!),
          ),
        if (secondaryActionLabel != null)
          TextButton(
            onPressed: onSecondaryAction,
            child: Text(secondaryActionLabel!),
          ),
      ],
    );
  }
}

/// 错误态：三段式（发生了什么 / 为什么 / 下一步）+ 重试（docs/08 §1.3）。
class CbrErrorState extends StatelessWidget {
  const CbrErrorState({
    super.key,
    required this.title,
    required this.reason,
    required this.nextStep,
    this.retryLabel = '重试',
    this.onRetry,
    this.compact = false,
  });

  final String title;
  final String reason;
  final String nextStep;
  final String retryLabel;
  final VoidCallback? onRetry;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return _StateBody(
      icon: CbrIcons.error,
      iconColor: palette.statusOf(CbrStatusTone.danger).solid,
      title: title,
      description: '$reason $nextStep',
      compact: compact,
      actions: <Widget>[
        OutlinedButton.icon(
          onPressed: onRetry,
          icon: const Icon(CbrIcons.retry, size: CbrIconSize.md),
          label: Text(retryLabel),
        ),
      ],
    );
  }
}

/// 「数据不可得（需授权 / 需登录 / 反爬受限）」——本产品最特殊的状态。
///
/// 硬规则（docs/07 §6.2）：**不得出现任何占位数值**，只写来源名 + 原因 +
/// 单一主动作；用 warn 色，不是 danger。
class CbrAccessRequiredState extends StatelessWidget {
  const CbrAccessRequiredState({
    super.key,
    required this.sourceName,
    required this.reason,
    required this.actionLabel,
    this.onAction,
    this.status = CbrSourceStatus.needsAuth,
  });

  final String sourceName;
  final String reason;
  final String actionLabel;
  final VoidCallback? onAction;
  final CbrSourceStatus status;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final colors = palette.statusOf(CbrStatusTone.warn);
    return Semantics(
      label: '$sourceName ${status.label}。$reason',
      child: Container(
        padding: const EdgeInsets.all(CbrSpace.s5),
        decoration: BoxDecoration(
          color: colors.tint,
          borderRadius: CbrRadius.lgAll,
          border: Border.all(
            color: colors.ink.withValues(alpha: 0.24),
            width: CbrBorder.hairline,
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: <Widget>[
            Row(
              children: <Widget>[
                Icon(CbrIcons.lock, size: CbrIconSize.lg, color: colors.ink),
                const SizedBox(width: CbrSpace.s3),
                Text(
                  '$sourceName ${status.label}',
                  style: CbrType.title.copyWith(color: colors.ink),
                ),
              ],
            ),
            const SizedBox(height: CbrSpace.s3),
            Text(reason, style: CbrType.body.copyWith(color: colors.ink)),
            const SizedBox(height: CbrSpace.s4),
            FilledButton(onPressed: onAction, child: Text(actionLabel)),
          ],
        ),
      ),
    );
  }
}

/// 骨架屏：尺寸必须与真实内容一致。
///
/// 一律静态灰块、不做 shimmer 循环动画 —— 既满足 reduce-motion 兜底
/// （docs/06 §7.3），也免掉一处常驻动画。
class CbrSkeleton extends StatelessWidget {
  const CbrSkeleton({
    super.key,
    this.width,
    this.height = 16,
    this.borderRadius = CbrRadius.xsAll,
    this.lines = 1,
    this.lineSpacing = CbrSpace.s3,
  });

  final double? width;
  final double height;
  final BorderRadius borderRadius;
  final int lines;
  final double lineSpacing;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final Color block = palette.surfaceHover;
    Widget bar({double? w}) => Container(
      width: w ?? width,
      height: height,
      decoration: BoxDecoration(color: block, borderRadius: borderRadius),
    );
    final Widget content = lines == 1
        ? bar()
        : Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              for (var i = 0; i < lines; i++) ...<Widget>[
                if (i > 0) SizedBox(height: lineSpacing),
                bar(w: i == lines - 1 ? (width ?? 160) * 0.6 : width),
              ],
            ],
          );
    return Semantics(label: '正在加载', excludeSemantics: true, child: content);
  }
}

/// 陈旧徽章：必须写「上次成功抓取：〈时间〉」（docs/06 §6.4）。
class CbrStaleBadge extends StatelessWidget {
  const CbrStaleBadge({
    super.key,
    required this.lastSuccessAt,
    this.severe = false,
  });

  final String lastSuccessAt;
  final bool severe;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final colors = palette.statusOf(
      severe ? CbrStatusTone.danger : CbrStatusTone.warn,
    );
    return Semantics(
      label: '数据已陈旧，上次成功抓取 $lastSuccessAt',
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: CbrSpace.s3,
          vertical: CbrSpace.s1,
        ),
        decoration: BoxDecoration(
          color: colors.tint,
          borderRadius: CbrRadius.xsAll,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(CbrIcons.clock, size: CbrIconSize.xs, color: colors.ink),
            const SizedBox(width: CbrSpace.s2),
            Text(
              '数据已陈旧 · 上次成功抓取 $lastSuccessAt',
              style: CbrType.micro.copyWith(color: colors.ink),
            ),
          ],
        ),
      ),
    );
  }
}

/// 页内提示条。
class CbrInlineBanner extends StatelessWidget {
  const CbrInlineBanner({
    super.key,
    required this.message,
    this.tone = CbrStatusTone.info,
    this.actionLabel,
    this.onAction,
    this.onDismiss,
  });

  final String message;
  final CbrStatusTone tone;
  final String? actionLabel;
  final VoidCallback? onAction;
  final VoidCallback? onDismiss;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final colors = palette.statusOf(tone);
    final IconData icon = switch (tone) {
      CbrStatusTone.ok => CbrIcons.success,
      CbrStatusTone.warn => CbrIcons.warning,
      CbrStatusTone.danger => CbrIcons.error,
      CbrStatusTone.info => CbrIcons.info,
      CbrStatusTone.idle => CbrIcons.info,
    };
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: CbrSpace.s4,
        vertical: CbrSpace.s3,
      ),
      decoration: BoxDecoration(
        color: colors.tint,
        borderRadius: CbrRadius.mdAll,
        border: Border.all(
          color: colors.ink.withValues(alpha: 0.20),
          width: CbrBorder.hairline,
        ),
      ),
      child: Row(
        children: <Widget>[
          Icon(icon, size: CbrIconSize.md, color: colors.ink),
          const SizedBox(width: CbrSpace.s3),
          Expanded(
            child: Text(
              message,
              style: CbrType.label.copyWith(color: colors.ink),
            ),
          ),
          if (actionLabel != null)
            TextButton(onPressed: onAction, child: Text(actionLabel!)),
          if (onDismiss != null)
            CbrIconButton(
              icon: CbrIcons.close,
              label: '关闭提示',
              size: CbrIconSize.sm,
              onPressed: onDismiss,
            ),
        ],
      ),
    );
  }
}

class _StateBody extends StatelessWidget {
  const _StateBody({
    required this.icon,
    required this.iconColor,
    required this.title,
    required this.description,
    this.actions = const <Widget>[],
    this.compact = false,
  });

  final IconData icon;
  final Color iconColor;
  final String title;
  final String description;
  final List<Widget> actions;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Padding(
      padding: EdgeInsets.symmetric(
        horizontal: CbrSpace.s5,
        vertical: compact ? CbrSpace.s5 : CbrSpace.s11,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          Icon(
            icon,
            size: compact ? CbrIconSize.xl : CbrIconSize.xxxl,
            color: iconColor,
          ),
          const SizedBox(height: CbrSpace.s4),
          Text(
            title,
            textAlign: TextAlign.center,
            style: CbrType.title.copyWith(color: palette.textPrimary),
          ),
          const SizedBox(height: CbrSpace.s3),
          Text(
            description,
            textAlign: TextAlign.center,
            style: CbrType.body.copyWith(color: palette.textSecondary),
          ),
          if (actions.isNotEmpty) ...<Widget>[
            const SizedBox(height: CbrSpace.s5),
            Wrap(
              spacing: CbrSpace.s3,
              runSpacing: CbrSpace.s3,
              alignment: WrapAlignment.center,
              children: actions,
            ),
          ],
        ],
      ),
    );
  }
}
