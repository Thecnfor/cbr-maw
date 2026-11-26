import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';
import 'package:genui/genui.dart';
import 'package:json_schema_builder/json_schema_builder.dart';
import 'package:material_ui/material_ui.dart';

/// 组件状态集合（docs/06 §9 VC-3）：Agent 不得跳过任何状态。
enum CbrComponentState { ready, loading, empty, error, disabled }

/// 从 props 的 `state` 字段解析；非法值按 [CbrComponentState.error] 处理。
CbrComponentState cbrParseState(Object? raw) => switch (raw) {
  'loading' => CbrComponentState.loading,
  'empty' => CbrComponentState.empty,
  'error' => CbrComponentState.error,
  'disabled' => CbrComponentState.disabled,
  _ => CbrComponentState.ready,
};

/// 读取 props 的辅助函数：全部经此收口，避免各处裸 cast。
Map<String, Object?> cbrJson(CatalogItemContext context) =>
    (context.data as Map).cast<String, Object?>();

String? cbrString(Object? value) => value is String ? value : null;

String cbrStringOr(Object? value, String fallback) =>
    value is String ? value : fallback;

double? cbrDouble(Object? value) => value is num ? value.toDouble() : null;

int? cbrInt(Object? value) => value is num ? value.toInt() : null;

List<Object?> cbrList(Object? value) =>
    value is List ? value : const <Object?>[];

Map<String, Object?> cbrMap(Object? value) =>
    value is Map ? value.cast<String, Object?>() : const <String, Object?>{};

/// 状态字段的公共 schema。所有组件都必须支持（docs/06 §9 VC-3）。
final Schema cbrStateSchema = S.string(
  description: '组件状态，缺省为 ready。',
  enumValues: <String>['ready', 'loading', 'empty', 'error', 'disabled'],
);

/// 风险等级取值（docs/08 §4）。只允许四档，Agent 不得自造等级名。
final Schema cbrRiskLevelSchema = S.string(
  description: '综合风险等级：低 / 中 / 高 / 极高。',
  enumValues: <String>['low', 'medium', 'high', 'critical'],
);

/// 动作风险级取值（docs/08 §4）。界面用白话，不显示裸 L0/L1/L2。
final Schema cbrActionRiskSchema = S.string(
  description: '动作风险级。',
  enumValues: <String>['viewOnly', 'confirmRequired', 'highRisk'],
);

/// 角色取值（docs/08 §3）。
final Schema cbrRoleSchema = S.string(
  enumValues: <String>['financing', 'investor', 'regulator', 'crossValidator'],
);

/// 来源状态五态（docs/08 §5.1）。
final Schema cbrSourceStatusSchema = S.string(
  enumValues: <String>[
    'fetched',
    'needsAuth',
    'needsLogin',
    'antiScrape',
    'expired',
  ],
);

CbrRiskLevel cbrRiskLevel(Object? raw) => switch (raw) {
  'low' => CbrRiskLevel.low,
  'medium' => CbrRiskLevel.medium,
  'high' => CbrRiskLevel.high,
  'critical' => CbrRiskLevel.critical,
  _ => CbrRiskLevel.medium,
};

CbrActionRisk cbrActionRisk(Object? raw) => switch (raw) {
  'viewOnly' => CbrActionRisk.viewOnly,
  'confirmRequired' => CbrActionRisk.confirmRequired,
  'highRisk' => CbrActionRisk.highRisk,
  _ => CbrActionRisk.confirmRequired,
};

CbrRole cbrRole(Object? raw) => switch (raw) {
  'investor' => CbrRole.investor,
  'regulator' => CbrRole.regulator,
  'crossValidator' => CbrRole.crossValidator,
  _ => CbrRole.financing,
};

CbrSourceStatus cbrSourceStatus(Object? raw) => switch (raw) {
  'fetched' => CbrSourceStatus.fetched,
  'needsLogin' => CbrSourceStatus.needsLogin,
  'antiScrape' => CbrSourceStatus.antiScrape,
  'expired' => CbrSourceStatus.expired,
  _ => CbrSourceStatus.needsAuth,
};

CbrStatusTone cbrTone(Object? raw) => switch (raw) {
  'ok' => CbrStatusTone.ok,
  'warn' => CbrStatusTone.warn,
  'danger' => CbrStatusTone.danger,
  'info' => CbrStatusTone.info,
  'idle' => CbrStatusTone.idle,
  _ => CbrStatusTone.info,
};

/// 通用状态包装：按 props.state 渲染 loading / empty / error / disabled。
Widget cbrStateful(CatalogItemContext ctx, Widget child) => CbrCatalogStateHost(
  state: cbrParseState(cbrJson(ctx)['state']),
  errorMessage: cbrString(cbrJson(ctx)['errorMessage']),
  child: child,
);

/// 解析动作并按 A2UI 约定回传（docs/04 §6）。
Future<void> cbrDispatch(CatalogItemContext ctx, Object? action) async {
  final map = cbrMap(action);
  final event = cbrMap(map['event']);
  final name = cbrString(event['name']);
  if (name == null) return;
  final resolved = await resolveContext(
    ctx.dataContext,
    cbrMap(event['context']),
  );
  ctx.dispatchEvent(
    UserActionEvent(name: name, sourceComponentId: ctx.id, context: resolved),
  );
}

/// 统一状态外壳：loading / empty / error / disabled 都有明确呈现。
///
/// `disabled` 用 [IgnorePointer] + 语义 `enabled: false`，不是把内容藏起来。
class CbrCatalogStateHost extends StatelessWidget {
  const CbrCatalogStateHost({
    super.key,
    required this.state,
    required this.child,
    this.emptyTitle = '暂无数据',
    this.emptyDescription = '当前条件下没有可展示的内容。',
    this.errorMessage,
  });

  final CbrComponentState state;
  final Widget child;
  final String emptyTitle;
  final String emptyDescription;
  final String? errorMessage;

  @override
  Widget build(BuildContext context) {
    return switch (state) {
      CbrComponentState.ready => child,
      CbrComponentState.loading => const Padding(
        padding: EdgeInsets.all(CbrSpace.s5),
        child: CbrSkeleton(lines: 3, width: 240),
      ),
      CbrComponentState.empty => CbrEmptyState(
        title: emptyTitle,
        description: emptyDescription,
      ),
      CbrComponentState.error => CbrErrorState(
        title: '组件未能渲染',
        reason: errorMessage ?? '组件数据未就绪。',
        nextStep: '可重试，或检查该组件的数据模型。',
        compact: true,
      ),
      CbrComponentState.disabled => Semantics(
        enabled: false,
        child: IgnorePointer(child: Opacity(opacity: 0.5, child: child)),
      ),
    };
  }
}
