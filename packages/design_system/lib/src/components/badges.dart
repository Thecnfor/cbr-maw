import 'package:material_ui/material_ui.dart';

import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'icons.dart';

/// 状态点：颜色 + 图标/文字等价（docs/06 §5.3、docs/07 §5.4）。
///
/// 禁止只靠圆点传达含义；[label] 必须能独立成句。
class CbrStatusDot extends StatelessWidget {
  const CbrStatusDot({
    super.key,
    required this.tone,
    required this.label,
    this.showLabel = false,
    this.size = 8,
    this.glowing = false,
  });

  final CbrStatusTone tone;
  final String label;
  final bool showLabel;
  final double size;

  /// 唯一允许的 glow 场景：此刻正在运行（docs/06 §1.2）。
  final bool glowing;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final colors = palette.statusOf(tone);
    return Semantics(
      label: label,
      excludeSemantics: true,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: <Widget>[
          if (glowing)
            Container(
              width: size + 6,
              height: size + 6,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: colors.solid.withValues(
                  alpha: palette.isDark ? 0.18 : 0.12,
                ),
              ),
              child: Container(
                width: size,
                height: size,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: colors.solid,
                ),
              ),
            )
          else
            Container(
              width: size,
              height: size,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: colors.solid,
              ),
            ),
          if (showLabel)
            Padding(
              padding: const EdgeInsets.only(left: CbrSpace.s3),
              child: Text(
                label,
                style: CbrType.caption.copyWith(color: palette.textSecondary),
              ),
            ),
        ],
      ),
    );
  }
}

/// 风险等级徽章：`tint` 底 + `ink` 字 + 图标 + 文字（docs/06 §6.2）。
///
/// 与动作风险级徽章**不共用**；不显示裸 `L1` 之类标识。
class CbrRiskBadge extends StatelessWidget {
  const CbrRiskBadge({super.key, required this.level, this.compact = false});

  final CbrRiskLevel level;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final colors = palette.statusOf(level.tone);
    return Semantics(
      label: '风险等级：${level.label}',
      excludeSemantics: true,
      child: Container(
        padding: EdgeInsets.symmetric(
          horizontal: compact ? CbrSpace.s3 : CbrSpace.s3 + 2,
          vertical: CbrSpace.s1,
        ),
        decoration: BoxDecoration(
          color: colors.tint,
          borderRadius: CbrRadius.pillAll,
          border: Border.all(
            color: colors.ink.withValues(alpha: 0.28),
            width: CbrBorder.hairline,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(
              CbrIcons.forRisk(level),
              size: CbrIconSize.xs,
              color: colors.ink,
            ),
            const SizedBox(width: CbrSpace.s2),
            Text(level.label, style: CbrType.micro.copyWith(color: colors.ink)),
          ],
        ),
      ),
    );
  }
}

/// 动作风险级徽章。文案固定为「仅查看 / 需确认的操作 / 高风险操作」。
class CbrActionRiskBadge extends StatelessWidget {
  const CbrActionRiskBadge({super.key, required this.risk});

  final CbrActionRisk risk;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final colors = palette.statusOf(risk.tone);
    return Semantics(
      label: risk.label,
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: CbrSpace.s3,
          vertical: CbrSpace.s1,
        ),
        decoration: BoxDecoration(
          color: colors.tint,
          borderRadius: CbrRadius.xsAll,
          border: Border.all(
            color: colors.ink.withValues(alpha: 0.28),
            width: CbrBorder.hairline,
          ),
        ),
        child: Text(
          risk.label,
          style: CbrType.micro.copyWith(color: colors.ink),
        ),
      ),
    );
  }
}

/// 来源状态标签（docs/08 §5.1 五态）。
enum CbrSourceStatus { fetched, needsAuth, needsLogin, antiScrape, expired }

extension CbrSourceStatusLabel on CbrSourceStatus {
  String get label => switch (this) {
    CbrSourceStatus.fetched => '已获取',
    CbrSourceStatus.needsAuth => '需授权',
    CbrSourceStatus.needsLogin => '需登录',
    CbrSourceStatus.antiScrape => '反爬受限',
    CbrSourceStatus.expired => '已过期',
  };

  /// 只有「已过期」用 danger，因为它意味着数据可能已失真。
  CbrStatusTone get tone => switch (this) {
    CbrSourceStatus.fetched => CbrStatusTone.ok,
    CbrSourceStatus.needsAuth => CbrStatusTone.warn,
    CbrSourceStatus.needsLogin => CbrStatusTone.warn,
    CbrSourceStatus.antiScrape => CbrStatusTone.warn,
    CbrSourceStatus.expired => CbrStatusTone.danger,
  };
}

/// 来源状态条：状态文字自足，不依赖颜色（docs/08 §5.1）。
class CbrSourceStatusChip extends StatelessWidget {
  const CbrSourceStatusChip({
    super.key,
    required this.status,
    required this.sourceName,
    this.reason,
    this.lastSuccessAt,
  });

  final CbrSourceStatus status;
  final String sourceName;

  /// 「反爬受限」必须以括号附注原因（docs/08 §5.1 第 6 条）。
  final String? reason;
  final String? lastSuccessAt;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final colors = palette.statusOf(status.tone);
    final label = status.label;
    final semantics = <String>[
      '$sourceName · $label',
      ?reason,
      if (lastSuccessAt != null) '上次成功抓取 $lastSuccessAt',
    ].join('，');
    return Semantics(
      label: semantics,
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: CbrSpace.s3,
          vertical: CbrSpace.s1,
        ),
        decoration: BoxDecoration(
          color: colors.tint,
          borderRadius: CbrRadius.xsAll,
          border: Border.all(
            color: colors.ink.withValues(alpha: 0.28),
            width: CbrBorder.hairline,
          ),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: <Widget>[
            Icon(
              status == CbrSourceStatus.fetched
                  ? CbrIcons.success
                  : CbrIcons.lock,
              size: CbrIconSize.xs,
              color: colors.ink,
            ),
            const SizedBox(width: CbrSpace.s2),
            Flexible(
              child: Text(
                reason == null ? label : '$label · $reason',
                overflow: TextOverflow.ellipsis,
                style: CbrType.micro.copyWith(color: colors.ink),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 分类标签。
class CbrTag extends StatelessWidget {
  const CbrTag({super.key, required this.text, this.tone});

  final String text;

  /// null 为中性标签。
  final CbrStatusTone? tone;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final Color bg = tone == null
        ? palette.surfaceHover
        : palette.statusOf(tone!).tint;
    final Color fg = tone == null
        ? palette.textSecondary
        : palette.statusOf(tone!).ink;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: CbrSpace.s3,
        vertical: CbrSpace.s1,
      ),
      decoration: BoxDecoration(color: bg, borderRadius: CbrRadius.xsAll),
      child: Text(text, style: CbrType.micro.copyWith(color: fg)),
    );
  }
}
