import 'package:cbr_maw/agents/blackboard/evidence_blackboard.dart';
import 'package:cbr_maw/agents/budget/budget.dart';
import 'package:cbr_maw/agents/investigation_controller.dart';
import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw/agents/roles/role_config.dart';
import 'package:cbr_maw/agents/run_events.dart';
import 'package:cbr_maw/agents/tools/tool_registry.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fixtures.dart';

/// 生成一条可被回填的 numeric claim（绑定证据包里的第一条 tool 证据）。
Map<String, Object?> claimPayload(String user, {double? valueOverride}) {
  final id = RegExp(r'"evidence_id":"(ev_[^"]+)"').firstMatch(user)?.group(1);
  return {
    'headline': '压力上升',
    'claims': [
      if (id != null)
        {
          'claim_type': 'numeric',
          'subject': '系统外溢指数',
          'text': '外溢指数上升',
          'value': valueOverride ?? 0.62,
          'unit': 'ratio',
          'evidence_ids': [id],
        },
      {
        'claim_type': 'numeric',
        'subject': '无依据指标',
        'text': '凭空数值',
        'value': 0.5,
        'evidence_ids': ['ev_fabricated'],
      },
    ],
    'recommendation': '关注跨市场外溢。',
    'limitations': ['测试局限'],
  };
}

void main() {
  group('零 Mock 严格模式', () {
    test('模型不可用 → RunFailed，不产出规则模板结论', () async {
      final events = await runOnce(
        settings: settingsFor(
          generator: null,
          invoker: FakeInvoker(values: {'systemic_risk': 0.62}),
        ),
      );

      final failure = events.whereType<RunFailed>().single;
      expect(failure.code, 'E_ALL_ROLES_FAILED');
      expect(
        failure.message.contains('设置') || failure.message.contains('模型'),
        isTrue,
      );
      expect(events.whereType<RunFinished>(), isEmpty);
      expect(events.whereType<ClaimProduced>(), isEmpty);
    });

    test('生成器抛 LlmFailure → 显式失败而非模板', () async {
      final settings = settingsFor(
        generator: ScriptedGenerator(
          (_, _) => throw const LlmFailure(
            code: LlmFailureCode.missingKey,
            message: '未配置 DeepSeek API 密钥。请到「设置 → 连接」填写密钥后重试。',
          ),
        ),
        invoker: FakeInvoker(values: {'systemic_risk': 0.62}),
      );
      final events = await runOnce(settings: settings);
      final failure = events.whereType<RunFailed>().single;
      expect(failure.message, contains('设置'));
      expect(events.whereType<RunFinished>(), isEmpty);
    });

    test('全部数据源失败 → 不产出任何结论', () async {
      final events = await runOnce(
        settings: settingsFor(
          generator: ScriptedGenerator((_, _) => claimPayload('')),
          invoker: FakeInvoker(),
        ),
      );
      expect(events.whereType<RunFailed>().single.code, 'E_NO_USABLE_EVIDENCE');
      expect(events.whereType<RunFinished>(), isEmpty);
    });
  });

  group('编排全链路', () {
    test('collaborative：产卡、回填 claim、丢弃无证据 claim', () async {
      final generator = ScriptedGenerator((_, user) => claimPayload(user));
      final events = await runOnce(
        settings: settingsFor(
          generator: generator,
          invoker: FakeInvoker(
            values: {
              'systemic_risk': 0.62,
              'risk_measure': 0.11,
              'capital_flow': 0.2,
              'scenario': 0.05,
              'forecast': 0.4,
              'funding_cost': 60.0,
            },
          ),
        ),
      );

      final summary = events.whereType<RunFinished>().single.summary;
      // 每个角色 1 条有效 claim（无证据那条被丢弃）。
      expect(summary.claimIds, hasLength(3));
      expect(summary.riskLevel, isNot('low'));
      expect(
        events.whereType<ClaimProduced>().every(
          (e) => e.evidenceIds.isNotEmpty,
        ),
        isTrue,
      );
      // 工具调用事件如实上报（含数值）。
      final toolEvents = events.whereType<ToolInvoked>().toList();
      expect(toolEvents, isNotEmpty);
      expect(toolEvents.every((e) => e.denied == false), isTrue);
      // 交叉验证与证据共享都发生过。
      expect(
        events.whereType<AgentActivity>().any(
          (e) => e.action == 'evidence_share',
        ),
        isTrue,
      );
      expect(
        events.whereType<AgentActivity>().any((e) => e.action == 'peer_review'),
        isTrue,
      );
    });

    test('single 模式：一个通用 agent 依次完成三主体任务', () async {
      final generator = ScriptedGenerator((_, user) => claimPayload(user));
      final events = await runOnce(
        mode: 'single',
        settings: settingsFor(
          generator: generator,
          invoker: FakeInvoker(
            values: {'systemic_risk': 0.62, 'funding_cost': 60.0},
          ),
          mode: 'single',
        ),
      );
      final summary = events.whereType<RunFinished>().single.summary;
      expect(summary.mode, 'single');
      expect(summary.claimIds, hasLength(3));
      final actions = events
          .whereType<AgentActivity>()
          .map((e) => e.action)
          .toSet();
      expect(actions, isNot(contains('evidence_share')));
      expect(actions, isNot(contains('peer_review')));
    });

    test('demo 模式走完整协同链（与 collaborative 同开关）', () async {
      final events = await runOnce(
        mode: 'demo',
        settings: settingsFor(
          generator: ScriptedGenerator((_, user) => claimPayload(user)),
          invoker: FakeInvoker(
            values: {'systemic_risk': 0.62, 'funding_cost': 60.0},
          ),
          mode: 'demo',
        ),
      );
      final summary = events.whereType<RunFinished>().single.summary;
      expect(summary.mode, 'demo');
      expect(
        events.whereType<AgentActivity>().any((e) => e.action == 'peer_review'),
        isTrue,
      );
    });

    test('independent 模式跳过共享/交叉验证/协调', () async {
      final events = await runOnce(
        mode: 'independent',
        settings: settingsFor(
          generator: ScriptedGenerator((_, user) => claimPayload(user)),
          invoker: FakeInvoker(
            values: {'systemic_risk': 0.62, 'funding_cost': 60.0},
          ),
          mode: 'independent',
        ),
      );
      final actions = events
          .whereType<AgentActivity>()
          .map((e) => e.action)
          .toSet();
      expect(actions, isNot(contains('evidence_share')));
      expect(actions, isNot(contains('peer_review')));
      expect(events.whereType<ConflictFound>(), isEmpty);
      expect(events.whereType<RunFinished>(), hasLength(1));
    });
  });

  group('越权不执行', () {
    test('工具白名单外 → 不调用、记审计、核验 permission 违规', () async {
      final roleCatalog = catalog();
      final invoker = FakeInvoker(values: {'risk_measure': 0.1});
      final registry = ToolRegistry(specs: roleCatalog.specs, invoker: invoker);

      final outcome = await registry.run(
        role: RoleId.financing,
        tool: 'systemic_risk',
        asOf: '2024-08-05',
      );
      expect(outcome.ok, isFalse);
      expect(outcome.denied, isTrue);
      expect(invoker.calls, isEmpty);
      expect(registry.denials, contains((RoleId.financing, 'systemic_risk')));
    });

    test('未知角色/工具在 default_deny 下一律拒绝', () async {
      final registry = ToolRegistry(
        specs: catalog().specs,
        invoker: FakeInvoker(values: {'risk_measure': 0.1}),
      );
      expect(registry.allows(RoleId.regulator, 'unknown_tool'), isFalse);
      expect(registry.allows(RoleId.crossValidator, 'risk_measure'), isFalse);
      expect(registry.allows(RoleId.regulator, 'risk_measure'), isTrue);
    });
  });

  group('预算耗尽降级为部分结论', () {
    test('工具预算耗尽 → summary.partial 且 limitations 说明', () async {
      final settings = settingsFor(
        generator: ScriptedGenerator((_, user) => claimPayload(user)),
        invoker: FakeInvoker(values: {'systemic_risk': 0.62}),
      );
      // 把每角色工具上限压到 1，迫使检索阶段截断。
      final tight = AgentSettings(
        catalog: RoleCatalog.parse(_tightCatalog),
        prompts: settings.prompts,
        registry: settings.registry,
        generator: settings.generator,
      );
      final events = await runOnce(settings: tight);
      final summary = events.whereType<RunFinished>().single.summary;
      expect(summary.partial, isTrue);
      expect(
        summary.limitations.any((l) => l.contains('预算') || l.contains('部分结论')),
        isTrue,
      );
      // 零 Mock：仍然是真实角色结论，不是 mock。
      expect(summary.claimIds, isNotEmpty);
    });

    test('BudgetGuard 截断 token 与工具调用', () {
      final guard = BudgetGuard(
        perRole: const RoleBudget(
          maxToolCalls: 1,
          maxTokens: 10,
          maxLatencyMs: 1000,
        ),
        maxWallClockMs: 60000,
        maxJointCost: null,
        actorCount: 1,
        costModel: const CostModel(
          costPerToolCall: 0.001,
          costPer1kTokens: 0.001,
          costPerLatencyMs: 0.00001,
          coordinationWeightMu: 0.1,
        ),
      );
      expect(guard.requestToolCall(0), isTrue);
      expect(guard.requestToolCall(0), isFalse);
      expect(guard.truncated, isTrue);
      expect(guard.chargeTokens(0, 50), 10);
      expect(guard.jointCost, greaterThan(0));
    });
  });

  group('黑板去重与别名', () {
    test('同内容不同 id 归一，保留最早 id 为规范 id', () {
      Evidence make(String id) => Evidence(
        evidenceId: id,
        kind: EvidenceKind.tool,
        asOf: DateTime.utc(2024, 8, 5),
        title: 't',
        value: 0.5,
        createdAt: DateTime.utc(2024, 8, 5),
        hash: 'same-hash',
      );
      final board = EvidenceBlackboard()
        ..add(make('ev_first'))
        ..add(make('ev_second'));
      expect(board.items, hasLength(1));
      expect(board.duplicateCount, 1);
      expect(board.resolveId('ev_second'), 'ev_first');
      expect(board.lookup('ev_second')?.evidenceId, 'ev_first');
    });
  });
}

const _tightCatalog = '''
{
  "roles": {
    "regulator": {
      "display_name": "监管", "horizon_days": 10, "objective": "o", "focus": [],
      "info_permissions": ["market.cn_equity"], "tool_permissions": ["risk_measure"],
      "thresholds": {"high_stress_prob": 0.5},
      "decision_loss_weights": {"miss": 5.0},
      "escalation_keywords": [], "escalation_threshold_key": null,
      "forbidden_actions": [], "output_style": "s"
    },
    "investor": {
      "display_name": "投资", "horizon_days": 5, "objective": "o", "focus": [],
      "info_permissions": ["market.cn_equity"], "tool_permissions": ["risk_measure"],
      "thresholds": {"high_stress_prob": 0.45},
      "decision_loss_weights": {"tail_loss": 5.0},
      "escalation_keywords": [], "escalation_threshold_key": null,
      "forbidden_actions": [], "output_style": "s"
    },
    "financing": {
      "display_name": "融资", "horizon_days": 20, "objective": "o", "focus": [],
      "info_permissions": ["market.cn_bond"], "tool_permissions": ["risk_measure"],
      "thresholds": {"high_stress_prob": 0.4},
      "decision_loss_weights": {"cost_overrun": 3.0},
      "escalation_keywords": [], "escalation_threshold_key": null,
      "forbidden_actions": [], "output_style": "s"
    }
  },
  "orchestration": {
    "modes": ["single", "independent", "collaborative", "demo"],
    "max_tool_calls_per_agent": 1, "max_tokens_per_agent": 4000,
    "max_latency_ms_per_agent": 120000, "max_wall_clock_ms": 300000, "max_delegations": 3,
    "numeric_tolerance_abs": 1e-6, "numeric_tolerance_rel": 1e-3,
    "cost_per_tool_call": 0.001, "cost_per_1k_tokens": 0.001,
    "cost_per_latency_ms": 0.00001, "coordination_weight_mu": 0.1, "max_limitations": 8
  }
}
''';
