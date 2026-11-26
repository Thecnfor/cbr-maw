import 'package:material_ui/material_ui.dart';

import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'badges.dart';
import 'icons.dart';
import 'pressable.dart';
import 'states.dart';

/// 数值文本：统一 tabular figures + 单位（docs/06 §6.2）。
class CbrNumericText extends StatelessWidget {
  const CbrNumericText({
    super.key,
    required this.value,
    this.unit,
    this.style,
    this.color,
  });

  final String value;
  final String? unit;
  final TextStyle? style;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final TextStyle base = (style ?? CbrType.numeric).copyWith(
      color: color ?? palette.textPrimary,
      fontFeatures: const <FontFeature>[FontFeature.tabularFigures()],
    );
    return Semantics(
      label: unit == null ? value : '$value $unit',
      excludeSemantics: true,
      child: Text.rich(
        TextSpan(
          children: <InlineSpan>[
            TextSpan(text: value),
            if (unit != null)
              TextSpan(
                text: ' $unit',
                style: CbrType.caption.copyWith(color: palette.textSecondary),
              ),
          ],
        ),
        style: base,
      ),
    );
  }
}

/// KPI 卡（docs/06 §6.2）。
///
/// 涨跌必须同时给箭头 + 正负号，颜色只是冗余通道（docs/06 §2.7）。
/// 值不可得（需授权）时**不得显示任何占位数值**，改渲染 [CbrKpiCard.unavailable]。
class CbrKpiCard extends StatelessWidget {
  const CbrKpiCard({
    super.key,
    required this.title,
    required this.value,
    this.unit,
    this.changeText,
    this.changeDirection,
    this.level,
    this.caption,
    this.marketConvention = CbrMarketConvention.cn,
    this.stale,
    this.onTap,
    this.loading = false,
  }) : _unavailable = null;

  /// 数据不可得：值区域显示状态文字，无数字、无破折号。
  const CbrKpiCard.unavailable({
    super.key,
    required this.title,
    required CbrSourceStatus status,
    required String sourceName,
    this.caption,
  }) : value = null,
       unit = null,
       changeText = null,
       changeDirection = null,
       level = null,
       marketConvention = CbrMarketConvention.cn,
       stale = null,
       onTap = null,
       loading = false,
       _unavailable = (status, sourceName);

  final String title;
  final String? value;
  final String? unit;

  /// 变化幅度，如 `+1.2` / `−0.8`。符号由调用方给出，箭头由组件补。
  final String? changeText;

  /// `1` 涨、`-1` 跌、`0` 持平；null 表示不适用。
  final int? changeDirection;

  final CbrRiskLevel? level;
  final String? caption;
  final CbrMarketConvention marketConvention;
  final CbrStaleBadge? stale;
  final VoidCallback? onTap;
  final bool loading;
  final (CbrSourceStatus, String)? _unavailable;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final Widget body = Container(
      padding: const EdgeInsets.all(CbrSpace.s5),
      decoration: BoxDecoration(
        color: palette.surfaceBase,
        borderRadius: CbrRadius.lgAll,
        border: Border.all(
          color: palette.borderDefault,
          width: CbrBorder.hairline,
        ),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Expanded(
                child: Text(
                  title,
                  overflow: TextOverflow.ellipsis,
                  style: CbrType.label.copyWith(color: palette.textSecondary),
                ),
              ),
              if (level != null) CbrRiskBadge(level: level!, compact: true),
            ],
          ),
          const SizedBox(height: CbrSpace.s3),
          if (loading)
            const CbrSkeleton(width: 96, height: 28)
          else if (_unavailable != null)
            _UnavailableValue(
              status: _unavailable.$1,
              sourceName: _unavailable.$2,
            )
          else
            Row(
              crossAxisAlignment: CrossAxisAlignment.baseline,
              textBaseline: TextBaseline.alphabetic,
              children: <Widget>[
                Flexible(
                  child: CbrNumericText(
                    value: value!,
                    unit: unit,
                    style: CbrType.numericLarge,
                  ),
                ),
                if (changeText != null) ...<Widget>[
                  const SizedBox(width: CbrSpace.s3),
                  _ChangeLabel(
                    text: changeText!,
                    direction: changeDirection ?? 0,
                    convention: marketConvention,
                  ),
                ],
              ],
            ),
          if (caption != null) ...<Widget>[
            const SizedBox(height: CbrSpace.s2),
            Text(
              caption!,
              style: CbrType.caption.copyWith(color: palette.textTertiary),
            ),
          ],
          if (stale != null) ...<Widget>[
            const SizedBox(height: CbrSpace.s3),
            stale!,
          ],
        ],
      ),
    );

    if (onTap == null) return body;
    return Semantics(
      button: true,
      label: '$title，查看详情',
      child: GestureDetector(onTap: onTap, child: body),
    );
  }
}

class _UnavailableValue extends StatelessWidget {
  const _UnavailableValue({required this.status, required this.sourceName});

  final CbrSourceStatus status;
  final String sourceName;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final colors = palette.statusOf(status.tone);
    return Semantics(
      label: '$sourceName ${status.label}，未显示任何数值',
      excludeSemantics: true,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(CbrIcons.lock, size: CbrIconSize.lg, color: colors.ink),
              const SizedBox(width: CbrSpace.s2),
              Text(
                status.label,
                style: CbrType.headline2.copyWith(color: colors.ink),
              ),
            ],
          ),
          const SizedBox(height: CbrSpace.s1),
          Text(
            '$sourceName 未授权',
            style: CbrType.caption.copyWith(color: palette.textTertiary),
          ),
        ],
      ),
    );
  }
}

class _ChangeLabel extends StatelessWidget {
  const _ChangeLabel({
    required this.text,
    required this.direction,
    required this.convention,
  });

  final String text;
  final int direction;
  final CbrMarketConvention convention;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final Color color = direction > 0
        ? palette.marketUp(convention)
        : direction < 0
        ? palette.marketDown(convention)
        : palette.textSecondary;
    final String arrow = direction > 0
        ? '▲'
        : direction < 0
        ? '▼'
        : '—';
    return Semantics(
      label: direction > 0
          ? '上涨 $text'
          : direction < 0
          ? '下跌 $text'
          : '持平 $text',
      excludeSemantics: true,
      child: Text(
        '$arrow $text',
        style: CbrType.numericSmall.copyWith(color: color),
      ),
    );
  }
}

/// 证据卡：原文片段 + 来源 + 时间 + 可达性（docs/06 §6.2）。
class CbrEvidenceCard extends StatelessWidget {
  const CbrEvidenceCard({
    super.key,
    required this.excerpt,
    required this.sourceName,
    required this.timestamp,
    this.status = CbrSourceStatus.fetched,
    this.title,
    this.reason,
    this.expanded = false,
    this.onToggleExpand,
    this.onOpen,
  });

  final String excerpt;
  final String sourceName;
  final String timestamp;
  final CbrSourceStatus status;
  final String? title;
  final String? reason;
  final bool expanded;
  final VoidCallback? onToggleExpand;
  final VoidCallback? onOpen;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Container(
      padding: const EdgeInsets.all(CbrSpace.s5),
      decoration: BoxDecoration(
        color: palette.surfaceBase,
        borderRadius: CbrRadius.lgAll,
        border: Border.all(
          color: palette.borderDefault,
          width: CbrBorder.hairline,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(
                CbrIcons.evidence,
                size: CbrIconSize.md,
                color: palette.textSecondary,
              ),
              const SizedBox(width: CbrSpace.s2),
              Expanded(
                child: Text(
                  title ?? '证据',
                  style: CbrType.title.copyWith(color: palette.textPrimary),
                ),
              ),
              CbrSourceStatusChip(
                status: status,
                sourceName: sourceName,
                reason: reason,
              ),
            ],
          ),
          const SizedBox(height: CbrSpace.s3),
          Semantics(
            label: '引用，来自 $sourceName，$timestamp',
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.all(CbrSpace.s4),
              decoration: BoxDecoration(
                color: palette.surfaceInset,
                borderRadius: CbrRadius.mdAll,
                border: Border(
                  left: BorderSide(color: palette.borderStrong, width: 2),
                ),
              ),
              child: Text(
                excerpt,
                maxLines: expanded ? null : 3,
                overflow: expanded ? null : TextOverflow.ellipsis,
                style: CbrType.body.copyWith(color: palette.textSecondary),
              ),
            ),
          ),
          const SizedBox(height: CbrSpace.s3),
          Row(
            children: <Widget>[
              Icon(
                CbrIcons.clock,
                size: CbrIconSize.xs,
                color: palette.textTertiary,
              ),
              const SizedBox(width: CbrSpace.s2),
              Text(
                '$sourceName · $timestamp',
                style: CbrType.caption.copyWith(color: palette.textTertiary),
              ),
              const Spacer(),
              if (onToggleExpand != null)
                Semantics(
                  expanded: expanded,
                  button: true,
                  label: expanded ? '收起证据原文' : '展开证据原文',
                  child: TextButton(
                    onPressed: onToggleExpand,
                    child: Text(expanded ? '收起' : '展开原文'),
                  ),
                ),
              if (onOpen != null)
                CbrIconButton(
                  icon: CbrIcons.external,
                  label: '打开证据来源',
                  onPressed: onOpen,
                ),
            ],
          ),
        ],
      ),
    );
  }
}

/// 指标卡（紧凑）：标题 + 数值 + 单位，用于列表/仪表盘。
class CbrMetricTile extends StatelessWidget {
  const CbrMetricTile({
    super.key,
    required this.label,
    required this.value,
    this.unit,
    this.tone,
  });

  final String label;
  final String value;
  final String? unit;
  final CbrStatusTone? tone;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final Color valueColor = tone == null
        ? palette.textPrimary
        : palette.statusOf(tone!).ink;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: CbrSpace.s3),
      child: Row(
        children: <Widget>[
          Expanded(
            child: Text(
              label,
              style: CbrType.label.copyWith(color: palette.textSecondary),
            ),
          ),
          CbrNumericText(
            value: value,
            unit: unit,
            style: CbrType.numeric,
            color: valueColor,
          ),
        ],
      ),
    );
  }
}
