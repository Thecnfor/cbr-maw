import 'dart:async';

import 'package:cbr_maw/agents/investigation_controller.dart';
import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw/agents/orchestrator/mode_flags.dart';
import 'package:cbr_maw/agents/roles/prompt_builder.dart';
import 'package:cbr_maw/agents/roles/role_config.dart';
import 'package:cbr_maw/agents/run_events.dart';
import 'package:cbr_maw/agents/tools/tool_registry.dart';
import 'package:flutter_test/flutter_test.dart';

/// 测试桩：确定性工具，返回固定读数（仅测试用，不进入产品代码）。
final class FakeInvoker implements ToolInvoker {
  FakeInvoker({this.values = const {}});

  final Map<String, double> values;
  final List<String> calls = [];

  @override
  Future<ToolInvocation> invoke({
    required String tool,
    required String asOf,
    required Map<String, Object?> params,
  }) async {
    calls.add(tool);
    final value = values[tool];
    if (value == null) {
      throw ToolUnavailable(tool, '测试桩未提供该工具读数');
    }
    return ToolInvocation(
      tool: tool,
      version: '1.0.0',
      value: value,
      unit: tool == 'funding_cost' ? 'bp' : 'ratio',
      payload: {'metric': tool, 'as_of': asOf},
      title: '$tool 读数',
    );
  }
}

/// 测试桩：按 purpose 返回固定 JSON 的生成器。
final class ScriptedGenerator implements TextGenerator {
  ScriptedGenerator(this.responder);

  final Map<String, Object?> Function(String purpose, String user) responder;
  final List<String> purposes = [];

  @override
  Future<LlmResponse> generateJson({
    required String system,
    required String user,
    required String purpose,
  }) async {
    purposes.add(purpose);
    return LlmResponse(
      json: responder(purpose, user),
      usage: const LlmUsage(prompt: 100, completion: 50),
      latencyMs: 10,
      attempts: 1,
    );
  }
}

const _catalogJson = '''
{
  "roles": {
    "regulator": {
      "display_name": "监管主体智能体", "horizon_days": 10,
      "objective": "监测系统性风险", "focus": ["外溢"],
      "info_permissions": ["market.cn_equity", "policy.fulltext"],
      "tool_permissions": ["risk_measure", "systemic_risk", "capital_flow", "scenario", "forecast", "knowledge_search"],
      "thresholds": {"high_stress_prob": 0.5, "critical_stress_prob": 0.7, "dy_spillover": 0.5},
      "decision_loss_weights": {"miss": 5.0, "false_alarm": 1.0},
      "escalation_keywords": ["spillover", "溢出"], "escalation_threshold_key": "dy_spillover",
      "forbidden_actions": ["给出具体证券买卖建议"], "output_style": "简报"
    },
    "investor": {
      "display_name": "投资主体智能体", "horizon_days": 5,
      "objective": "控制组合尾部损失", "focus": ["回撤"],
      "info_permissions": ["market.cn_equity", "portfolio.exposure"],
      "tool_permissions": ["risk_measure", "capital_flow", "systemic_risk", "scenario", "forecast"],
      "thresholds": {"high_stress_prob": 0.45, "max_drawdown": 0.1},
      "decision_loss_weights": {"tail_loss": 5.0, "transaction_cost": 1.0},
      "escalation_keywords": ["drawdown", "回撤"], "escalation_threshold_key": "max_drawdown",
      "forbidden_actions": ["直接建议具体个股买卖"], "output_style": "组合提示"
    },
    "financing": {
      "display_name": "融资主体智能体", "horizon_days": 20,
      "objective": "评估融资成本", "focus": ["利差"],
      "info_permissions": ["market.cn_bond", "rates.credit"],
      "tool_permissions": ["risk_measure", "funding_cost", "scenario", "forecast"],
      "thresholds": {"high_stress_prob": 0.4, "funding_cost_jump_bp": 50.0},
      "decision_loss_weights": {"cost_overrun": 3.0, "liquidity_shortfall": 5.0},
      "escalation_keywords": ["funding", "利差"], "escalation_threshold_key": "funding_cost_jump_bp",
      "forbidden_actions": ["访问市场交易头寸"], "output_style": "融资提示"
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

const _templates = {
  'common_rules': '# 通用规则\n- 数值必须来自工具证据。',
  'regulator': '# 监管 {{display_name}}\n{{objective}}\n{{thresholds}}',
  'investor': '# 投资 {{display_name}}\n{{objective}}',
  'financing': '# 融资 {{display_name}}\n{{objective}}',
  'cross_validation': '# 交叉验证 {{display_name}}\n{{tool_permissions}}',
  'single_agent': '# 单智能体\n{{regulator_objective}}',
};

RoleCatalog catalog() => RoleCatalog.parse(_catalogJson);

PromptBuilder prompts() => PromptBuilder.fromTemplates(_templates);

AgentSettings settingsFor({
  required TextGenerator? generator,
  required ToolInvoker invoker,
  String mode = 'collaborative',
}) {
  final roleCatalog = catalog();
  return AgentSettings(
    catalog: roleCatalog,
    prompts: prompts(),
    registry: ToolRegistry(specs: roleCatalog.specs, invoker: invoker),
    generator: generator,
    defaultMode: CollaborationMode.parse(mode),
  );
}

/// 跑一次研判并收集事件。
Future<List<RunEvent>> runOnce({
  required AgentSettings settings,
  String question = '评估 2024-08-05 的跨境风险',
  String mode = 'collaborative',
  RiskSignal? signal,
}) async {
  final runtime = AgentRuntime(settings);
  return runtime
      .run(
        question: question,
        runId: 'run_test',
        asOf: DateTime.utc(2024, 8, 5),
        mode: CollaborationMode.parse(mode),
        signal: signal,
      )
      .toList();
}
