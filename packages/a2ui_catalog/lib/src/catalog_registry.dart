import 'package:genui/genui.dart';

import 'package:material_ui/material_ui.dart';

import 'components_basic.dart' as basic;
import 'components_domain.dart' as domain;

/// CBR-MAW 自有 A2UI catalog 的版本号（docs/06 §9 VC-6）。
///
/// 与 A2UI 协议版本（v0.9）独立；升级 catalog 必须同步更新 Agent 系统提示
/// 中的组件清单并记变更日志。
const String cbrCatalogVersion = '1.0.0';

/// catalog id：反域名格式（genui 推荐）。
const String cbrCatalogId = 'cn.cbrmaw.a2ui.catalog';

/// 已登记组件的唯一名字集合。
///
/// 这是安全边界的唯一真源：不在集合内的组件一律拒绝（docs/02 F3-2、
/// docs/06 §9 VC-5）。
Set<String> get cbrRegisteredComponentNames => <String>{
  for (final item in cbrCatalogItems) item.name,
};

/// 组件名的 kebab-case 稳定 id（线路层 / 配置 / 遥测用）。
///
/// 组件**名**（`CatalogItem.name`）按 docs/03 §10 与 docs/06 §9.2 用
/// UpperCamelCase；节点 id 与配置引用用 kebab-case。两者一一对应，改一个
/// 必须同步改另一个（测试断言无遗漏、无重复）。
const Map<String, String> cbrComponentKebabIds = <String, String>{
  'RoleCard': 'role-card',
  'MetricTable': 'metric-table',
  'ClaimTable': 'claim-table',
  'DataCardList': 'data-card-list',
  'EvidenceList': 'evidence-list',
  'ConflictDiff': 'conflict-diff',
  'CrossValidationList': 'cross-validation-list',
  'VerificationSummary': 'verification-summary',
  'DecisionSummary': 'decision-summary',
  'CostMeter': 'cost-meter',
  'ConfirmCard': 'confirm-card',
  'Text': 'text',
  'Divider': 'divider',
  'Tag': 'tag',
  'SourceChip': 'source-chip',
  'EmptyState': 'empty-state',
  'ErrorState': 'error-state',
  'AccessRequired': 'access-required',
  'ProgressBar': 'progress-bar',
  'DataTable': 'data-table',
  'ChartCard': 'chart-card',
};

/// 所有已登记 [CatalogItem]。
final List<CatalogItem> cbrCatalogItems = <CatalogItem>[
  // CBR 领域
  domain.roleCard,
  domain.metricTable,
  domain.claimTable,
  domain.dataCardList,
  domain.evidenceList,
  domain.conflictDiff,
  domain.crossValidationList,
  domain.verificationSummary,
  domain.decisionSummary,
  domain.costMeter,
  domain.confirmCard,
  // 通用
  basic.text,
  basic.divider,
  basic.tag,
  basic.sourceChip,
  basic.emptyState,
  basic.errorState,
  basic.accessRequired,
  basic.progressBar,
  basic.dataTable,
  basic.chartCard,
];

/// catalog 系统提示片段：告诉模型只能用什么、不能传什么。
const String _cbrCatalogRules = '''
**CBR catalog 规则**
- 只能使用本 catalog 登记的组件；未登记组件会导致整个 surface 被拒绝。
- 只能传语义参数（label / value / variant / state / trend / level / items 等）。
  禁止传颜色、字号、字重、间距、圆角、阴影、字体、图标字形、透明度、z-index。
- 每个组件都支持 state: ready | loading | empty | error | disabled。
- 涨跌必须同时给出符号与方向（trend 带 +/−，trendDirection 为 -1/0/1）。
- 数据不可得时必须用 status + sourceName，不得给任何数值或占位符。
- 结论必须绑定 evidenceIds；限制必须写进 limitations，不得省略。
''';

/// 构造 catalog。
///
/// 只暴露 `basic`（Text / Divider / Tag 等通用）+ `cbr.basic`（领域）两部分，
/// 但全部走同一份 `cbrCatalogItems`，保证 VC-1「同一份实现」。
Catalog buildCbrCatalog({
  List<String> systemPromptFragments = const <String>[],
}) => Catalog(
  cbrCatalogItems,
  catalogId: cbrCatalogId,
  systemPromptFragments: <String>[_cbrCatalogRules, ...systemPromptFragments],
);

/// 严格校验：组件名必须已登记；参数名必须在 [cbrAllowedPropsFor] 中。
///
/// 未登记组件 → 返回 [CbrStrictViolation]；调用方据此拒绝该 surface 并写
/// `renderError{surfaceId}`（docs/06 §9 VC-5）。**不得静默丢弃**。
CbrStrictResult cbrValidateStrict({
  required String surfaceId,
  required List<({String id, String type, Map<String, Object?> props})>
  components,
}) {
  final Set<String> registered = cbrRegisteredComponentNames;
  for (final component in components) {
    // 线路层节点 id 必须 kebab-case（docs/03 §10：与 catalog 组件名的
    // UpperCamelCase 严格分开，二者不得混用）。
    if (!_kebabCase.hasMatch(component.id)) {
      return CbrStrictResult.rejected(
        CbrStrictViolation(
          surfaceId: surfaceId,
          componentId: component.id,
          kind: CbrStrictViolationKind.invalidComponentId,
          detail: '节点 id「${component.id}」不是 kebab-case',
        ),
      );
    }
    if (!registered.contains(component.type)) {
      return CbrStrictResult.rejected(
        CbrStrictViolation(
          surfaceId: surfaceId,
          componentId: component.id,
          kind: CbrStrictViolationKind.unknownComponent,
          detail: '组件「${component.type}」未在 catalog 登记',
        ),
      );
    }
    final Set<String> allowed = cbrAllowedPropsFor(component.type);
    for (final key in component.props.keys) {
      if (!allowed.contains(key)) {
        return CbrStrictResult.rejected(
          CbrStrictViolation(
            surfaceId: surfaceId,
            componentId: component.id,
            kind: CbrStrictViolationKind.unknownProperty,
            detail: '组件「${component.type}」不接受参数「$key」',
          ),
        );
      }
    }
  }
  return const CbrStrictResult.accepted();
}

/// 每个组件允许的参数名（由 schema 的 properties 推导，不在别处重复维护）。
final Map<String, Set<String>> _allowedPropsCache = <String, Set<String>>{
  for (final item in cbrCatalogItems)
    item.name: <String>{
      for (final key
          in (item.dataSchema.value['properties'] as Map<String, Object?>?)
                  ?.keys ??
              const <String>[])
        key,
      'id',
    },
};

Set<String> cbrAllowedPropsFor(String componentName) =>
    _allowedPropsCache[componentName] ?? const <String>{};

enum CbrStrictViolationKind {
  unknownComponent,
  unknownProperty,
  invalidComponentId,
}

final RegExp _kebabCase = RegExp(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$');

@immutable
class CbrStrictViolation {
  const CbrStrictViolation({
    required this.surfaceId,
    required this.componentId,
    required this.kind,
    required this.detail,
  });

  final String surfaceId;
  final String componentId;
  final CbrStrictViolationKind kind;
  final String detail;

  @override
  String toString() =>
      'renderError{surfaceId: $surfaceId, componentId: $componentId, kind: $kind, detail: $detail}';
}

@immutable
class CbrStrictResult {
  const CbrStrictResult.accepted() : violation = null;

  const CbrStrictResult.rejected(this.violation);

  final CbrStrictViolation? violation;

  bool get isAccepted => violation == null;
}
