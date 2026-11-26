import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';
import 'package:genui/genui.dart';
import 'package:json_schema_builder/json_schema_builder.dart';
import 'package:material_ui/material_ui.dart';

import 'helpers.dart';

/// CBR 领域组件（docs/06 §9.2 左列 + docs/04 §5.2）。
///
/// 每个组件复用设计系统的同一份 widget（VC-1），Agent 只能传语义参数
/// （VC-2）；颜色 / 字号 / 间距 / 图标字形一律不接受。

// ── RoleCard ──────────────────────────────────────────────────────────────

final _roleCardSchema = S.object(
  description: '单个角色的研判卡：角色、风险等级、判定窗口、要点、引用。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'role': cbrRoleSchema,
    'riskLevel': cbrRiskLevelSchema,
    'horizonDays': S.integer(description: '判定窗口天数。', minimum: 1),
    'headline': S.string(description: '一句话结论。'),
    'claimIds': S.list(items: S.string()),
    'evidenceIds': S.list(items: S.string()),
    'degraded': S.boolean(description: '是否处于降级运行。'),
  },
  required: <String>['role', 'headline'],
);

final roleCard = CatalogItem(
  name: 'RoleCard',
  dataSchema: _roleCardSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final role = cbrRole(json['role']);
    final level = json['riskLevel'] == null
        ? null
        : cbrRiskLevel(json['riskLevel']);
    final horizon = cbrInt(json['horizonDays']);
    final degraded = json['degraded'] == true;
    final evidenceCount = cbrList(json['evidenceIds']).length;
    return cbrStateful(
      ctx,
      CbrRoleCard(
        role: role,
        headline: cbrStringOr(json['headline'], ''),
        riskLevel: level,
        horizonDays: horizon,
        evidenceCount: evidenceCount,
        degraded: degraded,
      ),
    );
  },
  exampleData: <ExampleBuilderCallback>[
    () => '''
      [
        {"id": "root", "component": "RoleCard", "role": "financing",
         "riskLevel": "high", "horizonDays": 20, "headline": "偿付能力连续三期走弱"}
      ]
    ''',
  ],
);

// ── MetricTable ───────────────────────────────────────────────────────────

final _metricTableSchema = S.object(
  description: '指标表：列定义 + 行数据。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'density': S.string(enumValues: <String>['compact', 'standard', 'touch']),
    'columns': S.list(
      items: S.object(
        properties: <String, Schema>{
          'key': S.string(),
          'title': S.string(),
          'unit': S.string(),
          'align': S.string(enumValues: <String>['left', 'right', 'center']),
          'format': S.string(enumValues: <String>['text', 'number', 'percent']),
          'priority': S.integer(minimum: 1, maximum: 3),
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

final metricTable = CatalogItem(
  name: 'MetricTable',
  dataSchema: _metricTableSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return cbrStateful(
      ctx,
      CbrMetricTable(
        columns: cbrList(json['columns']),
        rows: cbrList(json['rows']),
        density: cbrString(json['density']),
      ),
    );
  },
);

// ── ClaimTable ────────────────────────────────────────────────────────────

final _claimTableSchema = S.object(
  description: '结论表：每条 claim 必须绑定证据与置信度。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'claims': S.list(
      items: S.object(
        properties: <String, Schema>{
          'text': S.string(),
          'verdict': S.string(
            enumValues: <String>['confirmed', 'refuted', 'uncertain'],
          ),
          'evidenceIds': S.list(items: S.string()),
          'confidence': S.number(minimum: 0, maximum: 1),
        },
        required: <String>['text'],
      ),
    ),
  },
  required: <String>['claims'],
);

final claimTable = CatalogItem(
  name: 'ClaimTable',
  dataSchema: _claimTableSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final claims = cbrList(json['claims']);
    return cbrStateful(
      ctx,
      claims.isEmpty
          ? const CbrEmptyState(title: '暂无结论', description: '当前没有可展示的结论条目。')
          : CbrClaimTable(claims: claims),
    );
  },
);

// ── DataCardList ──────────────────────────────────────────────────────────

final _dataCardListSchema = S.object(
  description: 'KPI 卡列表。值不可得时必须给 status + sourceName，不得给数值。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'cards': S.list(
      items: S.object(
        properties: <String, Schema>{
          'title': S.string(),
          'value': S.string(description: '已格式化数值；不可得时不要提供。'),
          'unit': S.string(),
          'trend': S.string(description: '带正负号的变化文本。'),
          'trendDirection': S.integer(minimum: -1, maximum: 1),
          'stale': S.string(description: '上次成功抓取时间。'),
          'level': cbrRiskLevelSchema,
          'status': cbrSourceStatusSchema,
          'sourceName': S.string(),
        },
        required: <String>['title'],
      ),
    ),
  },
  required: <String>['cards'],
);

final dataCardList = CatalogItem(
  name: 'DataCardList',
  dataSchema: _dataCardListSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final cards = cbrList(json['cards']);
    return cbrStateful(
      ctx,
      LayoutBuilder(
        builder: (context, constraints) {
          final int columns = constraints.maxWidth >= 960
              ? 3
              : constraints.maxWidth >= 600
              ? 2
              : 1;
          const double spacing = CbrSpace.s4;
          final double width =
              (constraints.maxWidth - spacing * (columns - 1)) / columns;
          return Wrap(
            spacing: spacing,
            runSpacing: spacing,
            children: <Widget>[
              for (final raw in cards)
                SizedBox(width: width, child: _dataCard(cbrMap(raw))),
            ],
          );
        },
      ),
    );
  },
);

Widget _dataCard(Map<String, Object?> card) {
  final status = cbrString(card['status']);
  final sourceName = cbrString(card['sourceName']);
  final stale = cbrString(card['stale']);
  if (status != null && status != 'fetched' && sourceName != null) {
    return CbrKpiCard.unavailable(
      title: cbrStringOr(card['title'], ''),
      status: cbrSourceStatus(status),
      sourceName: sourceName,
      caption: stale,
    );
  }
  return CbrKpiCard(
    title: cbrStringOr(card['title'], ''),
    value: cbrStringOr(card['value'], '—'),
    unit: cbrString(card['unit']),
    changeText: cbrString(card['trend']),
    changeDirection: cbrInt(card['trendDirection']),
    level: card['level'] == null ? null : cbrRiskLevel(card['level']),
    stale: stale == null ? null : CbrStaleBadge(lastSuccessAt: stale),
  );
}

// ── EvidenceList ──────────────────────────────────────────────────────────

final _evidenceListSchema = S.object(
  description: '证据卡列表：原文片段 + 来源 + 时间 + 可达性。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'items': S.list(
      items: S.object(
        properties: <String, Schema>{
          'title': S.string(),
          'excerpt': S.string(),
          'source': S.string(),
          'timestamp': S.string(),
          'reachable': cbrSourceStatusSchema,
          'reason': S.string(),
          'expanded': S.boolean(),
        },
        required: <String>['excerpt', 'source', 'timestamp'],
      ),
    ),
  },
  required: <String>['items'],
);

final evidenceList = CatalogItem(
  name: 'EvidenceList',
  dataSchema: _evidenceListSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final items = cbrList(json['items']);
    return cbrStateful(
      ctx,
      items.isEmpty
          ? const CbrEmptyState(
              title: '暂无证据',
              description: '该结论尚未绑定任何证据。',
              icon: CbrIcons.evidence,
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                for (final raw in items)
                  Padding(
                    padding: const EdgeInsets.only(bottom: CbrSpace.s3),
                    child: _evidenceCard(cbrMap(raw)),
                  ),
              ],
            ),
    );
  },
);

Widget _evidenceCard(Map<String, Object?> item) => CbrEvidenceCard(
  excerpt: cbrStringOr(item['excerpt'], ''),
  title: cbrString(item['title']),
  sourceName: cbrStringOr(item['source'], ''),
  timestamp: cbrStringOr(item['timestamp'], ''),
  status: cbrSourceStatus(item['reachable']),
  reason: cbrString(item['reason']),
  expanded: item['expanded'] == true,
);

// ── ConflictDiff ──────────────────────────────────────────────────────────

final _conflictDiffSchema = S.object(
  description: '角色冲突对照：双方各自的结论与证据。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'title': S.string(),
    'roleA': cbrRoleSchema,
    'roleB': cbrRoleSchema,
    'viewA': S.string(),
    'viewB': S.string(),
    'evidenceA': S.list(items: S.string()),
    'evidenceB': S.list(items: S.string()),
    'resolution': S.string(),
  },
  required: <String>['roleA', 'roleB', 'viewA', 'viewB'],
);

final conflictDiff = CatalogItem(
  name: 'ConflictDiff',
  dataSchema: _conflictDiffSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return cbrStateful(
      ctx,
      CbrConflictPanel(
        title: cbrStringOr(json['title'], '角色结论分歧'),
        left: CbrConflictSide(
          role: cbrRole(json['roleA']),
          view: cbrStringOr(json['viewA'], ''),
          evidence: cbrList(json['evidenceA'])
              .map((Object? e) => e.toString())
              .toList()
              .toList(),
        ),
        right: CbrConflictSide(
          role: cbrRole(json['roleB']),
          view: cbrStringOr(json['viewB'], ''),
          evidence: cbrList(json['evidenceB'])
              .map((Object? e) => e.toString())
              .toList()
              .toList(),
        ),
        resolution: cbrString(json['resolution']),
      ),
    );
  },
);

// ── CrossValidationList ───────────────────────────────────────────────────

final _crossValidationSchema = S.object(
  description: '交叉验证结论：只允许 confirmed / refuted / uncertain。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'findings': S.list(
      items: S.object(
        properties: <String, Schema>{
          'verdict': S.string(
            enumValues: <String>['confirmed', 'refuted', 'uncertain'],
          ),
          'note': S.string(),
          'claimId': S.string(),
        },
        required: <String>['verdict'],
      ),
    ),
  },
  required: <String>['findings'],
);

final crossValidationList = CatalogItem(
  name: 'CrossValidationList',
  dataSchema: _crossValidationSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    final findings = cbrList(json['findings']);
    return cbrStateful(
      ctx,
      findings.isEmpty
          ? const CbrEmptyState(
              title: '暂无交叉验证结论',
              description: '本轮尚未完成交叉验证。',
              icon: CbrIcons.riskLow,
            )
          : Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: <Widget>[
                for (final raw in findings)
                  Padding(
                    padding: const EdgeInsets.only(bottom: CbrSpace.s2),
                    child: _findingRow(cbrMap(raw)),
                  ),
              ],
            ),
    );
  },
);

Widget _findingRow(Map<String, Object?> finding) {
  final String verdict = cbrStringOr(finding['verdict'], 'uncertain');
  final (String label, CbrStatusTone tone, IconData icon) = switch (verdict) {
    'confirmed' => ('已证实', CbrStatusTone.ok, CbrIcons.success),
    'refuted' => ('已推翻', CbrStatusTone.danger, CbrIcons.error),
    _ => ('无法判断', CbrStatusTone.idle, CbrIcons.info),
  };
  return Builder(
    builder: (context) {
      final palette = CbrPalette.of(context);
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Icon(icon, size: CbrIconSize.md, color: palette.statusOf(tone).ink),
          const SizedBox(width: CbrSpace.s2),
          CbrTag(text: label, tone: tone),
          const SizedBox(width: CbrSpace.s3),
          Expanded(
            child: Text(
              cbrStringOr(finding['note'], ''),
              style: CbrType.label.copyWith(color: palette.textSecondary),
            ),
          ),
        ],
      );
    },
  );
}

// ── VerificationSummary ───────────────────────────────────────────────────

final _verificationSummarySchema = S.object(
  description: '证据覆盖度摘要：证实/推翻/不确定计数与缺口。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'confirmed': S.integer(minimum: 0),
    'refuted': S.integer(minimum: 0),
    'uncertain': S.integer(minimum: 0),
    'coverage': S.number(minimum: 0, maximum: 1),
    'gaps': S.list(items: S.string()),
  },
  required: <String>['confirmed', 'refuted', 'uncertain'],
);

final verificationSummary = CatalogItem(
  name: 'VerificationSummary',
  dataSchema: _verificationSummarySchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return cbrStateful(
      ctx,
      CbrVerificationSummary(
        confirmed: cbrInt(json['confirmed']) ?? 0,
        refuted: cbrInt(json['refuted']) ?? 0,
        uncertain: cbrInt(json['uncertain']) ?? 0,
        coverage: cbrDouble(json['coverage']),
        gaps: cbrList(json['gaps'])
            .map((Object? e) => e.toString())
            .toList()
            .toList(),
      ),
    );
  },
);

// ── DecisionSummary ───────────────────────────────────────────────────────

final _decisionSummarySchema = S.object(
  description: '最终研判结论：结论 + 风险等级 + 支撑 + 限制。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'conclusion': S.string(),
    'riskLevel': cbrRiskLevelSchema,
    'supports': S.list(items: S.string()),
    'limitations': S.list(items: S.string()),
  },
  required: <String>['conclusion', 'riskLevel'],
);

final decisionSummary = CatalogItem(
  name: 'DecisionSummary',
  dataSchema: _decisionSummarySchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return cbrStateful(
      ctx,
      CbrDecisionPanel(
        conclusion: cbrStringOr(json['conclusion'], ''),
        riskLevel: cbrRiskLevel(json['riskLevel']),
        supports: cbrList(json['supports'])
            .map((Object? e) => e.toString())
            .toList()
            .toList(),
        limitations: cbrList(json['limitations'])
            .map((Object? e) => e.toString())
            .toList()
            .toList(),
      ),
    );
  },
);

// ── CostMeter ─────────────────────────────────────────────────────────────

final _costMeterSchema = S.object(
  description: '本次协同成本：token、工具调用、协同成本与预算。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'tokens': S.integer(minimum: 0),
    'toolCalls': S.integer(minimum: 0),
    'coordinationCost': S.number(minimum: 0),
    'budget': S.number(minimum: 0),
  },
  required: <String>[],
);

final costMeter = CatalogItem(
  name: 'CostMeter',
  dataSchema: _costMeterSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return cbrStateful(
      ctx,
      CbrCostMeter(
        tokens: cbrInt(json['tokens']),
        toolCalls: cbrInt(json['toolCalls']),
        coordinationCost: cbrDouble(json['coordinationCost']),
        budget: cbrDouble(json['budget']),
      ),
    );
  },
);

// ── ConfirmCard ───────────────────────────────────────────────────────────

final _confirmCardSchema = S.object(
  description: '动作确认卡。按钮文案必须具体，不用「确定 / OK」。',
  properties: <String, Schema>{
    'state': cbrStateSchema,
    'title': S.string(),
    'actionRisk': cbrActionRiskSchema,
    'body': S.list(items: S.string()),
    'confirmLabel': S.string(),
    'cancelLabel': S.string(),
    'action': A2uiSchemas.action(),
  },
  required: <String>['title', 'actionRisk', 'confirmLabel', 'action'],
);

final confirmCard = CatalogItem(
  name: 'ConfirmCard',
  dataSchema: _confirmCardSchema,
  widgetBuilder: (ctx) {
    final json = cbrJson(ctx);
    return cbrStateful(
      ctx,
      CbrApprovalCard(
        title: cbrStringOr(json['title'], ''),
        risk: cbrActionRisk(json['actionRisk']),
        body: cbrList(json['body'])
            .map((Object? e) => e.toString())
            .toList()
            .toList(),
        confirmLabel: cbrStringOr(json['confirmLabel'], '确认执行'),
        cancelLabel: cbrStringOr(json['cancelLabel'], '取消'),
        onConfirm: () => cbrDispatch(ctx, json['action']),
        onCancel: () {},
      ),
    );
  },
);
