import 'package:cbr_maw/agents/roles/role_config.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart' show toolRegistry;
import 'package:flutter_test/flutter_test.dart';

/// 角色配置与跨语言契约（contracts/tools/tools.json）的一致性守卫。
///
/// 配置真源迁移自 docs/legacy-configs/roles.yaml；契约真源是 contracts/tools/tools.json。
/// 两者不一致会导致「配置允许但内核拒绝」的运行时事故，故在此锁死。
void main() {
  final catalog = RoleCatalog.parse(_json);

  test('三角色齐全，horizon 与设计一致（10 / 5 / 20）', () {
    expect(catalog.analyticalRoles, hasLength(3));
    expect(catalog.spec(RoleId.regulator).horizonDays, 10);
    expect(catalog.spec(RoleId.investor).horizonDays, 5);
    expect(catalog.spec(RoleId.financing).horizonDays, 20);
  });

  test('角色 tool_permissions 均在工具注册表内，且契约允许该角色', () {
    for (final role in catalog.analyticalRoles) {
      final spec = catalog.spec(role);
      for (final tool in spec.toolPermissions) {
        final contract = toolRegistry.where((t) => t.tool == tool).firstOrNull;
        expect(contract, isNotNull, reason: '工具 $tool 未在契约注册表中');
        // 配置与契约必须一致（否则越权在运行时才暴露）。
        expect(
          contract!.allowsRole(role.wire),
          isTrue,
          reason: '契约未授权 ${role.wire} 调用 $tool',
        );
      }
    }
  });

  test('阈值键与升级阈值键存在于 thresholds 中', () {
    for (final role in catalog.analyticalRoles) {
      final spec = catalog.spec(role);
      final key = spec.escalationThresholdKey;
      if (key != null) {
        expect(
          spec.thresholds.containsKey(key),
          isTrue,
          reason: '${role.wire} 的升级阈值键 $key 不在 thresholds 中',
        );
      }
    }
  });

  test('crossValidator 不出卡且无工具权限', () {
    expect(RoleId.crossValidator.producesCard, isFalse);
    expect(catalog.specs.containsKey(RoleId.crossValidator), isFalse);
  });
}

const _json = '''
{
  "roles": {
    "regulator": {
      "display_name": "监管主体智能体", "horizon_days": 10, "objective": "o", "focus": [],
      "info_permissions": ["market.cn_equity"],
      "tool_permissions": ["risk_measure", "systemic_risk", "capital_flow", "scenario", "forecast", "knowledge_search"],
      "thresholds": {"high_stress_prob": 0.5, "dy_spillover": 0.5},
      "decision_loss_weights": {"miss": 5.0},
      "escalation_keywords": ["spillover"], "escalation_threshold_key": "dy_spillover",
      "forbidden_actions": [], "output_style": "s"
    },
    "investor": {
      "display_name": "投资主体智能体", "horizon_days": 5, "objective": "o", "focus": [],
      "info_permissions": ["market.cn_equity"],
      "tool_permissions": ["risk_measure", "systemic_risk", "capital_flow", "scenario", "forecast", "knowledge_search"],
      "thresholds": {"high_stress_prob": 0.45, "max_drawdown": 0.1},
      "decision_loss_weights": {"tail_loss": 5.0},
      "escalation_keywords": ["drawdown"], "escalation_threshold_key": "max_drawdown",
      "forbidden_actions": [], "output_style": "s"
    },
    "financing": {
      "display_name": "融资主体智能体", "horizon_days": 20, "objective": "o", "focus": [],
      "info_permissions": ["market.cn_bond"],
      "tool_permissions": ["risk_measure", "funding_cost", "scenario", "forecast", "knowledge_search"],
      "thresholds": {"high_stress_prob": 0.4, "funding_cost_jump_bp": 50.0},
      "decision_loss_weights": {"cost_overrun": 3.0},
      "escalation_keywords": ["funding"], "escalation_threshold_key": "funding_cost_jump_bp",
      "forbidden_actions": [], "output_style": "s"
    }
  },
  "orchestration": {
    "modes": ["single", "independent", "collaborative", "demo"],
    "max_tool_calls_per_agent": 6, "max_tokens_per_agent": 4000,
    "max_latency_ms_per_agent": 120000, "max_wall_clock_ms": 300000, "max_delegations": 3,
    "numeric_tolerance_abs": 1e-6, "numeric_tolerance_rel": 1e-3,
    "cost_per_tool_call": 0.001, "cost_per_1k_tokens": 0.001,
    "cost_per_latency_ms": 0.00001, "coordination_weight_mu": 0.1, "max_limitations": 8
  }
}
''';
