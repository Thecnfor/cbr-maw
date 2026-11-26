/// A2UI 组件目录（安全边界）：未登记组件一律拒绝渲染（docs/03 §10.2 / docs/04）。
///
/// 组件 ID 用 UpperCamelCase（与 docs/06 §9.2 一致）；线路层节点 id 由适配层
/// 生成 kebab-case，二者不混用。
///
/// **单一真源**：可渲染组件集合取自 `cbr_maw_a2ui_catalog`
/// （`cbrRegisteredComponentNames`，docs/12 P1-5）。本文件只保留
/// 「属性白名单 + 动作风险级」这类渲染守卫元数据，不再维护第二份组件名单。
library;

import 'package:cbr_maw_a2ui_catalog/cbr_maw_a2ui_catalog.dart'
    show cbrRegisteredComponentNames;

/// 组件风险声明（组件被点击时的默认动作风险级）。
enum ActionRisk {
  l0('L0', 0),
  l1('L1', 1),
  l2('L2', 2);

  const ActionRisk(this.wire, this.order);

  /// JSON 字面量。
  final String wire;

  /// 强度序。
  final int order;

  /// 从字面量解析。
  static ActionRisk parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ArgumentError('非法动作风险级：$raw');
  }
}

/// 取更强风险级（缺省按 L1 保守处理）。
ActionRisk strongerRisk(ActionRisk? a, ActionRisk? b) {
  final left = a ?? ActionRisk.l1;
  final right = b ?? ActionRisk.l1;
  return left.order >= right.order ? left : right;
}

/// 单个组件定义。
final class CatalogComponent {
  /// 创建组件定义。
  const CatalogComponent({
    required this.kind,
    required this.description,
    required this.props,
    this.risk,
  });

  /// 组件 ID（UpperCamelCase）。
  final String kind;

  /// 说明。
  final String description;

  /// 允许的 props 名（白名单；越界参数被丢弃并记 trace）。
  final List<String> props;

  /// 组件声明的动作风险级（无可点击动作时为 null）。
  final ActionRisk? risk;
}

/// 组件目录。
final class CbrCatalog {
  /// 创建目录。
  const CbrCatalog(this.components);

  /// 已登记组件。
  final List<CatalogComponent> components;

  /// 按名取组件（未登记返回 null）。
  CatalogComponent? find(String kind) {
    for (final component in components) {
      if (component.kind == kind) {
        return component;
      }
    }
    return null;
  }

  /// 是否已登记。
  bool contains(String kind) => find(kind) != null;

  /// 默认目录：CBR 领域组件 + 基础布局组件（只保留包内已登记的名字）。
  static CbrCatalog get defaultCatalog => CbrCatalog([
    for (final component in _allComponents)
      if (cbrRegisteredComponentNames.contains(component.kind)) component,
  ]);
}

/// 组件元数据（属性白名单与动作风险级）。
///
/// 名字必须出现在 `cbr_maw_a2ui_catalog` 的登记集合中，否则
/// [CbrCatalog.defaultCatalog] 会把它过滤掉（防两处名单漂移）。
const List<CatalogComponent> _allComponents = [
  CatalogComponent(
    kind: 'RoleCard',
    description: '单角色研判卡：风险等级、关键测度、主张、局限。',
    props: [
      'role',
      'displayName',
      'riskLevel',
      'headline',
      'metrics',
      'claims',
      'limitations',
      'degraded',
    ],
  ),
  CatalogComponent(
    kind: 'ClaimTable',
    description: '主张列表，每条可点击跳转证据。',
    props: ['claims'],
  ),
  CatalogComponent(
    kind: 'EvidenceList',
    description: '证据列表，含来源、发布时间与工具入参哈希。',
    props: ['items'],
  ),
  CatalogComponent(
    kind: 'ConflictDiff',
    description: '分歧对照：双方主张、证据、仲裁结果。',
    props: ['conflicts'],
  ),
  CatalogComponent(
    kind: 'ConfirmCard',
    description: '人工确认卡（HITL / 动作确认）。',
    props: ['itemId', 'kind', 'risk', 'options', 'timeoutSeconds', 'onTimeout'],
    risk: ActionRisk.l1,
  ),
  CatalogComponent(
    kind: 'VerificationSummary',
    description: '六类核验报告摘要。',
    props: ['report'],
  ),
  CatalogComponent(
    kind: 'CrossValidationList',
    description: '交叉验证结论列表。',
    props: ['findings'],
  ),
  CatalogComponent(
    kind: 'DecisionSummary',
    description: '最终结论：等级、建议、降级与局限。',
    props: ['riskLevel', 'advice', 'degradedRoles', 'limitations', 'partial'],
  ),
  CatalogComponent(
    kind: 'CostMeter',
    description: '成本账：tokens / toolCalls / latency / L / C / J / μ。',
    props: [
      'tokens',
      'toolCalls',
      'latencyMs',
      'languageCost',
      'coordinationCost',
      'jointCost',
      'mu',
    ],
  ),
  CatalogComponent(
    kind: 'MetricTable',
    description: '测度表。',
    props: ['metrics'],
  ),
  CatalogComponent(
    kind: 'DataCardList',
    description: '数据卡列表（来源、覆盖期、时点可得性）。',
    props: ['cards'],
  ),
  CatalogComponent(
    kind: 'AccessRequired',
    description: '数据不可得态：来源 + 原因 + 单一主动作。绝不出现 0 / N/A。',
    props: ['sourceId', 'state', 'reason', 'actionLabel'],
  ),
  CatalogComponent(
    kind: 'Text',
    description: '文本块。',
    props: ['text', 'variant'],
  ),
  CatalogComponent(kind: 'Column', description: '纵向布局。', props: ['children']),
  CatalogComponent(kind: 'Row', description: '横向布局。', props: ['children']),
  CatalogComponent(kind: 'Card', description: '容器卡片。', props: ['children']),
  CatalogComponent(
    kind: 'Button',
    description: '按钮（必须声明动作）。',
    props: ['label', 'action'],
    risk: ActionRisk.l1,
  ),
];
