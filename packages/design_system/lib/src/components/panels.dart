import 'package:material_ui/material_ui.dart';

import '../tokens/colors.dart';
import '../tokens/tokens.dart';
import 'badges.dart';
import 'cards.dart';
import 'icons.dart';

/// 角色间结论分歧（docs/06 §6.3 `ConflictPanel`）。
///
/// 冲突必须展示双方各自的证据，不只显示结论。
@immutable
class CbrConflictSide {
  const CbrConflictSide({
    required this.role,
    required this.view,
    required this.evidence,
  });

  final CbrRole role;
  final String view;
  final List<String> evidence;
}

class CbrConflictPanel extends StatelessWidget {
  const CbrConflictPanel({
    super.key,
    required this.title,
    required this.left,
    required this.right,
    this.resolution,
  });

  final String title;
  final CbrConflictSide left;
  final CbrConflictSide right;

  /// 已消解时给裁决依据；null 表示待人工裁决。
  final String? resolution;

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
                CbrIcons.warning,
                size: CbrIconSize.md,
                color: palette.statusOf(CbrStatusTone.warn).ink,
              ),
              const SizedBox(width: CbrSpace.s2),
              Expanded(
                child: Text(
                  title,
                  style: CbrType.title.copyWith(color: palette.textPrimary),
                ),
              ),
              CbrTag(
                text: resolution == null ? '待人工裁决' : '已消解',
                tone: resolution == null
                    ? CbrStatusTone.warn
                    : CbrStatusTone.ok,
              ),
            ],
          ),
          const SizedBox(height: CbrSpace.s4),
          LayoutBuilder(
            builder: (context, constraints) {
              final bool stacked = constraints.maxWidth < 520;
              final List<Widget> sides = <Widget>[
                _Side(side: left),
                _Side(side: right),
              ];
              if (stacked) {
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    sides[0],
                    const SizedBox(height: CbrSpace.s4),
                    sides[1],
                  ],
                );
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Expanded(child: sides[0]),
                  const SizedBox(width: CbrSpace.s4),
                  Expanded(child: sides[1]),
                ],
              );
            },
          ),
          if (resolution != null) ...<Widget>[
            const SizedBox(height: CbrSpace.s4),
            Text(
              '裁决依据：$resolution',
              style: CbrType.label.copyWith(color: palette.textSecondary),
            ),
          ],
        ],
      ),
    );
  }
}

class _Side extends StatelessWidget {
  const _Side({required this.side});

  final CbrConflictSide side;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final roleColors = palette.roleOf(side.role);
    return Container(
      padding: const EdgeInsets.all(CbrSpace.s4),
      decoration: BoxDecoration(
        color: palette.surfaceInset,
        borderRadius: CbrRadius.mdAll,
        border: Border(left: BorderSide(color: roleColors.solid, width: 2)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            children: <Widget>[
              Icon(
                CbrIcons.forRole(side.role),
                size: CbrIconSize.sm,
                color: roleColors.ink,
              ),
              const SizedBox(width: CbrSpace.s2),
              Text(
                side.role.label,
                style: CbrType.labelStrong.copyWith(color: roleColors.ink),
              ),
            ],
          ),
          const SizedBox(height: CbrSpace.s2),
          Text(
            side.view,
            style: CbrType.body.copyWith(color: palette.textPrimary),
          ),
          if (side.evidence.isNotEmpty) ...<Widget>[
            const SizedBox(height: CbrSpace.s2),
            for (final item in side.evidence)
              Padding(
                padding: const EdgeInsets.only(top: CbrSpace.s1),
                child: Text(
                  '· $item',
                  style: CbrType.caption.copyWith(color: palette.textSecondary),
                ),
              ),
          ],
        ],
      ),
    );
  }
}

/// 研判结论（docs/06 §9.2 `DecisionSummary`）。
///
/// 支撑与限制必须同时出现；限制为空时写「无已知限制」，不留空。
class CbrDecisionPanel extends StatelessWidget {
  const CbrDecisionPanel({
    super.key,
    required this.conclusion,
    required this.riskLevel,
    this.supports = const <String>[],
    this.limitations = const <String>[],
  });

  final String conclusion;
  final CbrRiskLevel riskLevel;
  final List<String> supports;
  final List<String> limitations;

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
              Expanded(
                child: Text(
                  '研判结论',
                  style: CbrType.title.copyWith(color: palette.textPrimary),
                ),
              ),
              CbrRiskBadge(level: riskLevel),
            ],
          ),
          const SizedBox(height: CbrSpace.s3),
          Text(
            conclusion,
            style: CbrType.bodyStrong.copyWith(color: palette.textPrimary),
          ),
          if (supports.isNotEmpty) ...<Widget>[
            const SizedBox(height: CbrSpace.s4),
            Text(
              '支撑',
              style: CbrType.labelStrong.copyWith(color: palette.textSecondary),
            ),
            for (final item in supports)
              Padding(
                padding: const EdgeInsets.only(top: CbrSpace.s1),
                child: Text(
                  '· $item',
                  style: CbrType.label.copyWith(color: palette.textSecondary),
                ),
              ),
          ],
          const SizedBox(height: CbrSpace.s4),
          Text(
            '限制',
            style: CbrType.labelStrong.copyWith(color: palette.textSecondary),
          ),
          for (final item
              in limitations.isEmpty ? const <String>['无已知限制'] : limitations)
            Padding(
              padding: const EdgeInsets.only(top: CbrSpace.s1),
              child: Text(
                '· $item',
                style: CbrType.label.copyWith(
                  color: limitations.isEmpty
                      ? palette.textTertiary
                      : palette.textSecondary,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// 时间线条目。
@immutable
class CbrTimelineEntry {
  const CbrTimelineEntry({
    required this.title,
    required this.timestamp,
    this.description,
    this.tone = CbrStatusTone.idle,
  });

  final String title;
  final String timestamp;
  final String? description;
  final CbrStatusTone tone;
}

/// 时间线（纵向，最新在上由调用方决定顺序）。
class CbrTimeline extends StatelessWidget {
  const CbrTimeline({super.key, required this.entries});

  final List<CbrTimelineEntry> entries;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    if (entries.isEmpty) {
      return Text(
        '暂无事件',
        style: CbrType.label.copyWith(color: palette.textTertiary),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        for (var i = 0; i < entries.length; i++)
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                SizedBox(
                  width: 16,
                  child: Column(
                    children: <Widget>[
                      Padding(
                        padding: const EdgeInsets.only(top: CbrSpace.s2),
                        child: CbrStatusDot(
                          tone: entries[i].tone,
                          label: entries[i].title,
                          size: 8,
                        ),
                      ),
                      if (i < entries.length - 1)
                        Expanded(
                          child: Container(
                            width: CbrBorder.hairline,
                            color: palette.borderSubtle,
                          ),
                        ),
                    ],
                  ),
                ),
                const SizedBox(width: CbrSpace.s3),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.only(bottom: CbrSpace.s4),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Row(
                          children: <Widget>[
                            Expanded(
                              child: Text(
                                entries[i].title,
                                style: CbrType.labelStrong.copyWith(
                                  color: palette.textPrimary,
                                ),
                              ),
                            ),
                            Text(
                              entries[i].timestamp,
                              style: CbrType.caption.copyWith(
                                color: palette.textTertiary,
                              ),
                            ),
                          ],
                        ),
                        if (entries[i].description != null)
                          Padding(
                            padding: const EdgeInsets.only(top: CbrSpace.s1),
                            child: Text(
                              entries[i].description!,
                              style: CbrType.label.copyWith(
                                color: palette.textSecondary,
                              ),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

/// 成本与预算（docs/04 §5.2 `CostMeter`）。
///
/// 数值全部来自真实调用统计；缺失时由调用方给 `null` 并显示「暂无数据」，
/// 不得用 0 冒充。
class CbrCostMeter extends StatelessWidget {
  const CbrCostMeter({
    super.key,
    this.tokens,
    this.toolCalls,
    this.coordinationCost,
    this.budget,
  });

  final int? tokens;
  final int? toolCalls;
  final double? coordinationCost;
  final double? budget;

  String _fmt(num? value, {String? unit}) {
    if (value == null) return '暂无数据';
    final text = value is int ? '$value' : value.toStringAsFixed(2);
    return unit == null ? text : '$text $unit';
  }

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final double? ratio =
        (budget == null || budget == 0 || coordinationCost == null)
        ? null
        : (coordinationCost! / budget!).clamp(0.0, 1.0);
    return Container(
      padding: const EdgeInsets.all(CbrSpace.s4),
      decoration: BoxDecoration(
        color: palette.surfaceInset,
        borderRadius: CbrRadius.mdAll,
        border: Border.all(
          color: palette.borderSubtle,
          width: CbrBorder.hairline,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Text(
            '本次协同成本',
            style: CbrType.labelStrong.copyWith(color: palette.textPrimary),
          ),
          const SizedBox(height: CbrSpace.s2),
          Wrap(
            spacing: CbrSpace.s5,
            runSpacing: CbrSpace.s2,
            children: <Widget>[
              _metric(palette, 'Token', _fmt(tokens)),
              _metric(palette, '工具调用', _fmt(toolCalls, unit: '次')),
              _metric(
                palette,
                '协同成本',
                coordinationCost == null
                    ? '暂无数据'
                    : '${coordinationCost!.toStringAsFixed(2)} / ${budget?.toStringAsFixed(2) ?? '未设预算'}',
              ),
            ],
          ),
          if (ratio != null) ...<Widget>[
            const SizedBox(height: CbrSpace.s3),
            ClipRRect(
              borderRadius: CbrRadius.pillAll,
              child: LinearProgressIndicator(
                value: ratio,
                minHeight: 4,
                backgroundColor: palette.surfaceHover,
                valueColor: AlwaysStoppedAnimation<Color>(
                  ratio > 0.9
                      ? palette.statusOf(CbrStatusTone.danger).solid
                      : palette.statusOf(CbrStatusTone.info).solid,
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  Widget _metric(CbrPalette palette, String label, String value) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: <Widget>[
      Text(label, style: CbrType.caption.copyWith(color: palette.textTertiary)),
      Text(
        value,
        style: CbrType.numericSmall.copyWith(color: palette.textPrimary),
      ),
    ],
  );
}

/// 角色研判卡（docs/06 §6.3、docs/09 §9.2 `RoleCard`）。
///
/// 角色必须图标 + 颜色 + 文字三重编码；判定窗口必须显式标出，否则读者
/// 无法解释角色间结论差异（docs/08 §3.1）。
class CbrRoleCard extends StatelessWidget {
  const CbrRoleCard({
    super.key,
    required this.role,
    required this.headline,
    this.riskLevel,
    this.horizonDays,
    this.evidenceCount,
    this.degraded = false,
  });

  final CbrRole role;
  final String headline;
  final CbrRiskLevel? riskLevel;
  final int? horizonDays;
  final int? evidenceCount;

  /// 降级运行必须明示（零 Mock 严格模式）。
  final bool degraded;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final roleColors = palette.roleOf(role);
    return Container(
      padding: const EdgeInsets.all(CbrSpace.s4),
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
                CbrIcons.forRole(role),
                size: CbrIconSize.md,
                color: roleColors.ink,
              ),
              const SizedBox(width: CbrSpace.s2),
              Text(
                role.label,
                style: CbrType.labelStrong.copyWith(color: roleColors.ink),
              ),
              if (horizonDays != null) ...<Widget>[
                const SizedBox(width: CbrSpace.s3),
                Text(
                  '判定窗口 $horizonDays 天',
                  style: CbrType.caption.copyWith(color: palette.textTertiary),
                ),
              ],
              const Spacer(),
              if (riskLevel != null)
                CbrRiskBadge(level: riskLevel!, compact: true),
            ],
          ),
          const SizedBox(height: CbrSpace.s3),
          Text(
            headline,
            style: CbrType.body.copyWith(color: palette.textPrimary),
          ),
          if (evidenceCount != null || degraded) ...<Widget>[
            const SizedBox(height: CbrSpace.s3),
            Row(
              children: <Widget>[
                if (evidenceCount != null)
                  Text(
                    '引用证据 $evidenceCount 条',
                    style: CbrType.caption.copyWith(
                      color: palette.textTertiary,
                    ),
                  ),
                const Spacer(),
                if (degraded)
                  const CbrTag(text: '降级运行', tone: CbrStatusTone.warn),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// 指标表：列定义来自 props，单元格值按 format 渲染。
class CbrMetricTable extends StatelessWidget {
  const CbrMetricTable({
    super.key,
    required this.columns,
    required this.rows,
    this.density,
  });

  final List<Object?> columns;
  final List<Object?> rows;
  final String? density;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    final List<Map<String, Object?>> cols = columns
        .map(
          (c) =>
              c is Map ? c.cast<String, Object?>() : const <String, Object?>{},
        )
        .where((c) => c['key'] is String)
        .toList();
    if (cols.isEmpty) {
      return Text(
        '表格未提供列定义',
        style: CbrType.label.copyWith(color: palette.textTertiary),
      );
    }
    return Container(
      decoration: BoxDecoration(
        border: Border.all(
          color: palette.borderDefault,
          width: CbrBorder.hairline,
        ),
        borderRadius: CbrRadius.mdAll,
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: <Widget>[
          Container(
            color: palette.surfaceInset,
            padding: const EdgeInsets.symmetric(
              horizontal: CbrSpace.s3,
              vertical: CbrSpace.s3,
            ),
            child: Row(
              children: <Widget>[
                for (final col in cols)
                  Expanded(
                    child: Text(
                      col['title'] as String,
                      style: CbrType.labelStrong.copyWith(
                        color: palette.textSecondary,
                      ),
                    ),
                  ),
              ],
            ),
          ),
          for (var i = 0; i < rows.length; i++)
            Container(
              padding: const EdgeInsets.symmetric(
                horizontal: CbrSpace.s3,
                vertical: CbrSpace.s2,
              ),
              decoration: BoxDecoration(
                border: Border(
                  top: BorderSide(
                    color: palette.borderSubtle,
                    width: CbrBorder.hairline,
                  ),
                ),
              ),
              child: Row(
                children: <Widget>[
                  for (final col in cols)
                    Expanded(child: _cell(context, col, rows[i])),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Widget _cell(BuildContext context, Map<String, Object?> col, Object? row) {
    final palette = CbrPalette.of(context);
    final values = row is Map ? (row['values'] as Map?) : null;
    final raw = values?[col['key']];
    final unit = col['unit'] as String?;
    final format = col['format'] as String?;
    if (raw == null) {
      return Text(
        '—',
        style: CbrType.numericSmall.copyWith(color: palette.textTertiary),
      );
    }
    final String text;
    if (raw is num) {
      text = switch (format) {
        'percent' => '${(raw * 100).toStringAsFixed(1)}%',
        _ => raw.toString(),
      };
    } else {
      text = raw.toString();
    }
    return CbrNumericText(value: text, unit: unit, style: CbrType.numericSmall);
  }
}

/// 结论表：verdict 只允许三值，必须带置信度与证据数。
class CbrClaimTable extends StatelessWidget {
  const CbrClaimTable({super.key, required this.claims});

  final List<Object?> claims;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Container(
      decoration: BoxDecoration(
        border: Border.all(
          color: palette.borderDefault,
          width: CbrBorder.hairline,
        ),
        borderRadius: CbrRadius.mdAll,
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(
        children: <Widget>[
          for (var i = 0; i < claims.length; i++)
            Builder(
              builder: (context) {
                final claim = claims[i] is Map
                    ? (claims[i] as Map).cast<String, Object?>()
                    : const <String, Object?>{};
                final String verdict = cbrVerdictLabel(claim['verdict']);
                final confidence = claim['confidence'];
                final evidenceIds = claim['evidenceIds'];
                return Container(
                  padding: const EdgeInsets.all(CbrSpace.s4),
                  decoration: BoxDecoration(
                    border: Border(
                      top: BorderSide(
                        color: i == 0
                            ? Colors.transparent
                            : palette.borderSubtle,
                        width: CbrBorder.hairline,
                      ),
                    ),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          claim['text']?.toString() ?? '',
                          style: CbrType.body.copyWith(
                            color: palette.textPrimary,
                          ),
                        ),
                      ),
                      const SizedBox(width: CbrSpace.s3),
                      CbrTag(
                        text: verdict,
                        tone: switch (claim['verdict']) {
                          'confirmed' => CbrStatusTone.ok,
                          'refuted' => CbrStatusTone.danger,
                          _ => CbrStatusTone.idle,
                        },
                      ),
                      if (confidence is num)
                        Padding(
                          padding: const EdgeInsets.only(left: CbrSpace.s3),
                          child: CbrNumericText(
                            value: '${(confidence * 100).toStringAsFixed(0)}%',
                            style: CbrType.numericSmall,
                          ),
                        ),
                      if (evidenceIds is List)
                        Padding(
                          padding: const EdgeInsets.only(left: CbrSpace.s3),
                          child: Text(
                            '证据 ${evidenceIds.length}',
                            style: CbrType.caption.copyWith(
                              color: palette.textTertiary,
                            ),
                          ),
                        ),
                    ],
                  ),
                );
              },
            ),
        ],
      ),
    );
  }
}

/// verdict 的中文措辞（docs/08 §3.3）。
String cbrVerdictLabel(Object? verdict) => switch (verdict) {
  'confirmed' => '已证实',
  'refuted' => '已推翻',
  _ => '无法判断',
};

/// 证据覆盖度摘要。
class CbrVerificationSummary extends StatelessWidget {
  const CbrVerificationSummary({
    super.key,
    required this.confirmed,
    required this.refuted,
    required this.uncertain,
    this.coverage,
    this.gaps = const <String>[],
  });

  final int confirmed;
  final int refuted;
  final int uncertain;
  final double? coverage;
  final List<String> gaps;

  @override
  Widget build(BuildContext context) {
    final palette = CbrPalette.of(context);
    return Container(
      padding: const EdgeInsets.all(CbrSpace.s4),
      decoration: BoxDecoration(
        color: palette.surfaceInset,
        borderRadius: CbrRadius.mdAll,
        border: Border.all(
          color: palette.borderSubtle,
          width: CbrBorder.hairline,
        ),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Wrap(
            spacing: CbrSpace.s4,
            runSpacing: CbrSpace.s2,
            children: <Widget>[
              CbrTag(text: '已证实 $confirmed', tone: CbrStatusTone.ok),
              CbrTag(text: '已推翻 $refuted', tone: CbrStatusTone.danger),
              CbrTag(text: '无法判断 $uncertain', tone: CbrStatusTone.idle),
              if (coverage != null)
                CbrTag(text: '证据覆盖 ${(coverage! * 100).toStringAsFixed(0)}%'),
            ],
          ),
          if (gaps.isNotEmpty) ...<Widget>[
            const SizedBox(height: CbrSpace.s3),
            Text(
              '证据缺口',
              style: CbrType.labelStrong.copyWith(color: palette.textSecondary),
            ),
            for (final gap in gaps)
              Padding(
                padding: const EdgeInsets.only(top: CbrSpace.s1),
                child: Text(
                  '· $gap',
                  style: CbrType.caption.copyWith(color: palette.textSecondary),
                ),
              ),
          ],
        ],
      ),
    );
  }
}
