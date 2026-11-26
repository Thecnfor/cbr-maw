import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';
import 'package:genui/genui.dart';
import 'package:json_schema_builder/json_schema_builder.dart';
import 'package:material_ui/material_ui.dart';

import 'helpers.dart';

/// 通用组件（docs/06 §9.2 右列）。
///
/// 全部复用设计系统实现；Agent 传的样式类参数不被 schema 接受，因此会被
/// `strict` 校验拒绝，而不是静默套用。

// ── Text ──────────────────────────────────────────────────────────────────

final text = CatalogItem(
  name: 'Text',
  dataSchema: S.object(
    description: '受控文本：只允许语义变体，不接受字号 / 字体 / 颜色。',
    properties: <String, Schema>{
      'text': S.string(),
      'variant': S.string(
        enumValues: <String>['body', 'title', 'caption', 'code'],
      ),
      'emphasis': S.boolean(),
    },
    required: <String>['text'],
  ),
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final palette = CbrPalette.of(ctx.buildContext);
    final TextStyle base = switch (cbrString(json['variant'])) {
      'title' => CbrType.title,
      'caption' => CbrType.caption,
      'code' => CbrType.code,
      _ => CbrType.body,
    };
    final style = (json['emphasis'] == true ? CbrType.bodyStrong : base)
        .copyWith(
          color: base == CbrType.caption
              ? palette.textSecondary
              : palette.textPrimary,
        );
    return Text(cbrStringOr(json['text'], ''), style: style);
  },
);

// ── Divider ───────────────────────────────────────────────────────────────

final divider = CatalogItem(
  name: 'Divider',
  dataSchema: S.object(
    description: '1dp 分隔线。',
    properties: <String, Schema>{'inset': S.boolean(description: '是否左右内缩。')},
    required: <String>[],
  ),
  widgetBuilder: (ctx) {
    final inset = cbrJson(ctx)['inset'] == true;
    return Padding(
      padding: EdgeInsets.symmetric(
        horizontal: inset ? CbrSpace.s4 : 0,
        vertical: CbrSpace.s2,
      ),
      child: const Divider(height: CbrBorder.hairline),
    );
  },
);

// ── Tag ───────────────────────────────────────────────────────────────────

final tag = CatalogItem(
  name: 'Tag',
  dataSchema: S.object(
    description: '分类标签。tone 只能取语义枚举，不能传颜色。',
    properties: <String, Schema>{
      'text': S.string(),
      'tone': S.string(
        enumValues: <String>['ok', 'warn', 'danger', 'info', 'idle'],
      ),
    },
    required: <String>['text'],
  ),
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final rawTone = cbrString(json['tone']);
    return CbrTag(
      text: cbrStringOr(json['text'], ''),
      tone: rawTone == null ? null : cbrTone(rawTone),
    );
  },
);

// ── SourceChip ────────────────────────────────────────────────────────────

final sourceChip = CatalogItem(
  name: 'SourceChip',
  dataSchema: S.object(
    description: '来源状态标签（五态）。',
    properties: <String, Schema>{
      'state': cbrStateSchema,
      'source': S.string(),
      'status': cbrSourceStatusSchema,
      'lastSuccessAt': S.string(),
      'reason': S.string(),
    },
    required: <String>['source', 'status'],
  ),
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return cbrStateful(
      ctx,
      CbrSourceStatusChip(
        status: cbrSourceStatus(json['status']),
        sourceName: cbrStringOr(json['source'], ''),
        reason: cbrString(json['reason']),
        lastSuccessAt: cbrString(json['lastSuccessAt']),
      ),
    );
  },
);

// ── EmptyState ────────────────────────────────────────────────────────────

final emptyState = CatalogItem(
  name: 'EmptyState',
  dataSchema: S.object(
    description: '空态：图标 + 标题 + 说明 + 主动作。icon 只能是白名单名。',
    properties: <String, Schema>{
      'icon': S.string(description: 'Lucide 白名单图标名（kebab-case）。'),
      'title': S.string(),
      'description': S.string(),
      'primaryAction': S.string(description: '主动作文案。'),
      'secondaryAction': S.string(),
      'action': A2uiSchemas.action(),
    },
    required: <String>['title', 'description', 'primaryAction'],
  ),
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final iconName = cbrString(json['icon']);
    return CbrEmptyState(
      title: cbrStringOr(json['title'], ''),
      description: cbrStringOr(json['description'], ''),
      icon: iconName == null
          ? CbrIcons.database
          : CbrIcons.byName(iconName) ?? CbrIcons.fallback,
      primaryActionLabel: cbrStringOr(json['primaryAction'], ''),
      onPrimaryAction: json['action'] == null
          ? null
          : () => cbrDispatch(ctx, json['action']),
      secondaryActionLabel: cbrString(json['secondaryAction']),
    );
  },
);

// ── ErrorState ────────────────────────────────────────────────────────────

final errorState = CatalogItem(
  name: 'ErrorState',
  dataSchema: S.object(
    description: '错误态：三段式文案。不接受堆栈。',
    properties: <String, Schema>{
      'title': S.string(),
      'reason': S.string(),
      'nextStep': S.string(),
      'retryable': S.boolean(),
      'action': A2uiSchemas.action(),
    },
    required: <String>['title', 'reason', 'nextStep'],
  ),
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final retryable = json['retryable'] != false;
    return CbrErrorState(
      title: cbrStringOr(json['title'], ''),
      reason: cbrStringOr(json['reason'], ''),
      nextStep: cbrStringOr(json['nextStep'], ''),
      onRetry: retryable && json['action'] != null
          ? () => cbrDispatch(ctx, json['action'])
          : null,
    );
  },
);

// ── AccessRequired ────────────────────────────────────────────────────────

final accessRequired = CatalogItem(
  name: 'AccessRequired',
  dataSchema: S.object(
    description: '数据不可得（需授权 / 需登录 / 反爬受限）。不接受任何数值占位。',
    properties: <String, Schema>{
      'source': S.string(),
      'reason': S.string(),
      'status': cbrSourceStatusSchema,
      'actionLabel': S.string(),
      'action': A2uiSchemas.action(),
    },
    required: <String>['source', 'reason', 'actionLabel'],
  ),
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return CbrAccessRequiredState(
      sourceName: cbrStringOr(json['source'], ''),
      reason: cbrStringOr(json['reason'], ''),
      actionLabel: cbrStringOr(json['actionLabel'], '前往授权'),
      status: cbrSourceStatus(json['status'] ?? 'needsAuth'),
      onAction: json['action'] == null
          ? null
          : () => cbrDispatch(ctx, json['action']),
    );
  },
);

// ── ProgressBar ───────────────────────────────────────────────────────────

final progressBar = CatalogItem(
  name: 'ProgressBar',
  dataSchema: S.object(
    description: '确定性进度：必须给 value 与 total，不接受不定进度动画。',
    properties: <String, Schema>{
      'state': cbrStateSchema,
      'value': S.number(minimum: 0),
      'total': S.number(minimum: 0),
      'label': S.string(),
    },
    required: <String>['value', 'total'],
  ),
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final palette = CbrPalette.of(ctx.buildContext);
    final value = cbrDouble(json['value']) ?? 0;
    final total = cbrDouble(json['total']) ?? 0;
    final ratio = total <= 0 ? 0.0 : (value / total).clamp(0.0, 1.0);
    return cbrStateful(
      ctx,
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          if (json['label'] != null)
            Padding(
              padding: const EdgeInsets.only(bottom: CbrSpace.s2),
              child: Text(
                '${cbrStringOr(json['label'], '')}（${value.toStringAsFixed(0)} / ${total.toStringAsFixed(0)}）',
                style: CbrType.label.copyWith(color: palette.textSecondary),
              ),
            ),
          ClipRRect(
            borderRadius: CbrRadius.pillAll,
            child: LinearProgressIndicator(
              value: ratio,
              minHeight: 6,
              backgroundColor: palette.surfaceHover,
              valueColor: AlwaysStoppedAnimation<Color>(
                palette.statusOf(CbrStatusTone.info).solid,
              ),
            ),
          ),
        ],
      ),
    );
  },
);

// ── DataTable ─────────────────────────────────────────────────────────────

final _dataTableSchema = S.object(
  description: '宽表。columns 给 key/title/priority/align/format。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'columns': S.list(
      items: S.object(
        properties: <String, Schema>{
          'key': S.string(),
          'title': S.string(),
          'priority': S.integer(minimum: 1, maximum: 3),
          'align': S.string(enumValues: <String>['left', 'right', 'center']),
          'format': S.string(enumValues: <String>['text', 'number', 'percent']),
        },
        required: <String>['key', 'title'],
      ),
    ),
    'rows': S.list(
      items: S.object(
        properties: <String, Schema>{'values': S.object()},
        required: <String>['values'],
      ),
    ),
  },
  required: <String>['columns', 'rows'],
);

final dataTable = CatalogItem(
  name: 'DataTable',
  dataSchema: _dataTableSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return cbrStateful(
      ctx,
      CbrDataTable<Map<String, Object?>>(
        columns: <CbrTableColumn<Map<String, Object?>>>[
          for (final raw in cbrList(json['columns'])) _column(cbrMap(raw)),
        ],
        rows: <Map<String, Object?>>[
          for (final raw in cbrList(json['rows'])) cbrMap(raw),
        ],
        empty: const CbrEmptyState(title: '暂无数据', description: '当前条件下没有匹配的行。'),
      ),
    );
  },
);

CbrTableColumn<Map<String, Object?>> _column(Map<String, Object?> col) {
  final String key = cbrStringOr(col['key'], '');
  final String format = cbrStringOr(col['format'], 'text');
  return CbrTableColumn<Map<String, Object?>>(
    key: key,
    title: cbrStringOr(col['title'], key),
    priority: cbrInt(col['priority']) ?? 1,
    align: switch (cbrString(col['align'])) {
      'right' => Alignment.centerRight,
      'center' => Alignment.center,
      _ => Alignment.centerLeft,
    },
    cell: (context, row) {
      final values = row['values'];
      final raw = values is Map ? values[key] : null;
      if (raw == null) {
        return const Text('—', style: CbrType.numericSmall);
      }
      if (raw is num) {
        final text = format == 'percent'
            ? '${(raw * 100).toStringAsFixed(1)}%'
            : raw.toString();
        return CbrNumericText(value: text, style: CbrType.numericSmall);
      }
      return Text(raw.toString(), style: CbrType.body);
    },
  );
}

// ── ChartCard ─────────────────────────────────────────────────────────────

final _chartCardSchema = S.object(
  description: '折线图。系列只能给 colorIndex 1..8，不能传颜色。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'title': S.string(),
    'chartType': S.string(enumValues: <String>['line']),
    'series': S.list(
      items: S.object(
        properties: <String, Schema>{
          'name': S.string(),
          'colorIndex': S.integer(minimum: 1, maximum: 8),
          'dashed': S.boolean(),
          'points': S.list(
            items: S.object(
              properties: <String, Schema>{'x': S.number(), 'y': S.number()},
              required: <String>['x', 'y'],
            ),
          ),
        },
        required: <String>['name', 'points'],
      ),
    ),
  },
  required: <String>['title', 'series'],
);

final chartCard = CatalogItem(
  name: 'ChartCard',
  dataSchema: _chartCardSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final series = <CbrSeries>[
      for (final raw in cbrList(json['series'])) _series(cbrMap(raw)),
    ];
    return cbrStateful(
      ctx,
      CbrChartCard(
        title: cbrStringOr(json['title'], ''),
        series: series,
        empty: const CbrEmptyState(title: '暂无图表数据', description: '该图表没有可用系列。'),
      ),
    );
  },
);

CbrSeries _series(Map<String, Object?> raw) => CbrSeries(
  name: cbrStringOr(raw['name'], ''),
  colorIndex: cbrInt(raw['colorIndex']) ?? 1,
  dashed: raw['dashed'] == true,
  points: <({double x, double y})>[
    for (final point in cbrList(raw['points']))
      (
        x: cbrDouble(cbrMap(point)['x']) ?? 0,
        y: cbrDouble(cbrMap(point)['y']) ?? 0,
      ),
  ],
);
