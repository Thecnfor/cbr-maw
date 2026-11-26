// GENERATED-DO-NOT-EDIT: 与 contracts/tools/tools.json 同源；
// test/contracts_test.dart 断言两者一致。

part of 'rpc.dart';

/// 工具风险等级（L0 只读 / L1 写本地 / L2 触发外部动作需 HITL）。
enum ToolRiskLevel {
  /// L0：只读、无副作用。
  l0('L0'),
  /// L1：写本地。
  l1('L1'),
  /// L2：触发外部动作，需 HITL。
  l2('L2');

  const ToolRiskLevel(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从 JSON 字面量解析（解析即校验）。
  static ToolRiskLevel parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ContractFormatException('非法风险等级：$raw');
  }
}

/// 工具注册表条目（contracts/tools/tools.json）。
final class ToolSpec {
  const ToolSpec({
    required this.tool,
    required this.version,
    required this.riskLevel,
    required this.allowedRoles,
    required this.paramsSchemaRef,
    required this.returns,
    required this.deterministic,
    required this.legacyRef,
    required this.description,
    required this.defaultParams,
  });

  /// 工具名。
  final String tool;

  /// 工具版本。
  final String version;

  /// 动作风险等级。
  final ToolRiskLevel riskLevel;

  /// 允许调用该工具的角色（roles.yaml 的 tool_permissions）。
  final List<String> allowedRoles;

  /// 入参 schema 路径。
  final String paramsSchemaRef;

  /// 返回值结构说明（值类型名；该字段不适用时为 null）。
  final Map<String, String?> returns;

  /// 是否确定性（工具绝不调用 LLM）。
  final bool deterministic;

  /// 旧版 Python 实现参照。
  final String legacyRef;

  /// 工具说明。
  final String description;

  /// 默认参数（与 tools.yaml 一致）。
  final Map<String, Object?> defaultParams;

  /// 角色是否被允许调用该工具（default_deny）。
  bool allowsRole(String role) => allowedRoles.contains(role);

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'tool': tool,
    'version': version,
    'risk_level': riskLevel.wire,
    'allowed_roles': allowedRoles,
    'params_schema_ref': paramsSchemaRef,
    'returns': returns,
    'deterministic': deterministic,
    'legacy_ref': legacyRef,
    'description': description,
    'default_params': defaultParams,
  };
}

/// 工具注册表（contracts/tools/tools.json 的 Dart 常量）。
const List<ToolSpec> toolRegistry = [
  ToolSpec(
    tool: 'risk_measure',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['regulator', 'investor', 'financing'],
    paramsSchemaRef: 'contracts/tools/risk_measure.params.schema.json',
    returns: {'value': 'number', 'unit': 'string', 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'commorcial/src/cbr/tools/risk.py',
    description: '年化波动率、历史/参数 VaR 与 CVaR、最大回撤、压力分位（确定性纯计算）',
    defaultParams: {'lookback': 252, 'annualization': 252, 'confidence': 0.95, 'horizon_days': 1, 'values_are': 'price', 'min_observations': 20, 'series_id': 'market.cn_equity.csi300'},
  ),
  ToolSpec(
    tool: 'systemic_risk',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['regulator', 'investor'],
    paramsSchemaRef: 'contracts/tools/systemic_risk.params.schema.json',
    returns: {'value': 'number', 'unit': 'string', 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'commorcial/src/cbr/tools/systemic.py',
    description: 'ΔCoVaR、MES、Diebold-Yilmaz 跨市场溢出指数（确定性纯计算）',
    defaultParams: {'lookback': 252, 'tail_q': 0.05, 'dy_window': 120, 'dy_lag': 1, 'dy_horizon': 10, 'values_are': 'price', 'market_series_id': 'market.cn_equity.csi300', 'asset_series_id': 'market.cn_bond.cgb_index', 'series_ids': ['market.cn_equity.csi300', 'market.global.sp500', 'market.fx.usdcny', 'market.global.vix']},
  ),
  ToolSpec(
    tool: 'capital_flow',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['regulator', 'investor'],
    paramsSchemaRef: 'contracts/tools/capital_flow.params.schema.json',
    returns: {'value': 'number', 'unit': 'string', 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'commorcial/src/cbr/tools/capital.py',
    description: '跨境资金异常净流入 z-score、同步撤离、集中度与 AH 溢价（确定性纯计算）',
    defaultParams: {'lookback': 60, 'z_window': 60, 'anomaly_z': 1.5, 'top_n': 5, 'flow_unit': '亿元', 'inflow_series_id': 'crossborder.flows.northbound_net', 'outflow_series_id': 'crossborder.flows.southbound_net', 'ah_premium_series_id': 'crossborder.flows.ah_premium'},
  ),
  ToolSpec(
    tool: 'funding_cost',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['financing'],
    paramsSchemaRef: 'contracts/tools/funding_cost.params.schema.json',
    returns: {'value': 'number', 'unit': 'string', 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'commorcial/src/cbr/tools/funding.py',
    description: '信用利差代理、融资成本变化（bp）、再融资窗口估计（确定性纯计算）',
    defaultParams: {'lookback': 252, 'momentum_window': 20, 'spread_unit': 'bp', 'cost_jump_bp': 50.0, 'cost_medium_bp': 25.0, 'refinancing_horizon_days': 90, 'spread_series_id': 'rates.credit.aa_spread'},
  ),
  ToolSpec(
    tool: 'scenario',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['regulator', 'investor', 'financing'],
    paramsSchemaRef: 'contracts/tools/scenario.params.schema.json',
    returns: {'value': 'number', 'unit': 'string', 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'commorcial/src/cbr/tools/scenario.py',
    description: '汇率/美股/利差冲击的线性与历史类比情景映射及压力传导（确定性纯计算）',
    defaultParams: {'lookback': 252, 'us_equity_drop_pct': 10.0, 'fx_depreciation_pct': 5.0, 'spread_widening_bp': 100.0, 'method': 'both', 'analog_k': 10, 'spread_unit': 'bp', 'min_observations': 60, 'values_are': 'price', 'target_series_id': 'market.cn_equity.csi300', 'us_equity_series_id': 'market.global.sp500', 'fx_series_id': 'market.fx.usdcny', 'spread_series_id': 'rates.credit.aa_spread'},
  ),
  ToolSpec(
    tool: 'forecast',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['regulator', 'investor', 'financing'],
    paramsSchemaRef: 'contracts/tools/forecast.params.schema.json',
    returns: {'value': 'number', 'unit': 'string', 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'commorcial/src/cbr/tools/forecast.py',
    description: '读取共享多模态风险信号（P1 产物，只读）并输出统一 Evidence',
    defaultParams: {'horizon': 5, 'include_drivers': true},
  ),
  ToolSpec(
    tool: 'knowledge_search',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['regulator', 'investor', 'financing'],
    paramsSchemaRef: 'contracts/tools/knowledge_search.params.schema.json',
    returns: {'value': null, 'unit': null, 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'commorcial/src/cbr/tools/kb_search.py',
    description: '时点过滤的知识库检索（政策/方法学/事件复盘），返回 chunk_id 可核验引文',
    defaultParams: {'top_k': 5},
  ),
  ToolSpec(
    tool: 'dimension_dispersion',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['regulator', 'investor', 'financing'],
    paramsSchemaRef: 'contracts/tools/dimension_dispersion.params.schema.json',
    returns: {'value': 'number', 'unit': 'string', 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'docs/20-角色分歧与风险来源结构.md §2',
    description: '风险来源结构：六维压力分极差、主导维度与阶段判读（确定性纯计算）',
    defaultParams: {},
  ),
  ToolSpec(
    tool: 'capital_linkage',
    version: '1.0.0',
    riskLevel: ToolRiskLevel.l0,
    allowedRoles: ['regulator', 'investor', 'financing'],
    paramsSchemaRef: 'contracts/tools/capital_linkage.params.schema.json',
    returns: {'value': 'number', 'unit': 'string', 'as_of': 'datetime'},
    deterministic: true,
    legacyRef: 'docs/18-北向资金联动性领先信号.md §5',
    description: '双序列滚动 Kendall tau 联动性（变化率口径，含领先性诊断；确定性纯计算）',
    defaultParams: {'preset': 'csi300_x_northbound', 'window': 90, 'threshold_z': 0.5},
  ),
];
