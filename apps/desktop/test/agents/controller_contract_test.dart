import 'package:cbr_maw/agents/investigation_controller.dart';
import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:cbr_maw/agents/run_events.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fixtures.dart';

void main() {
  InvestigationController controller() {
    final settings = settingsFor(
      generator: ScriptedGenerator((_, user) {
        final id = RegExp(r'"evidence_id":"(ev_[^"]+)"')
            .firstMatch(user)
            ?.group(1);
        return {
          'headline': '压力上升',
          'claims': [
            if (id != null)
              {
                'claim_type': 'numeric',
                'subject': '外溢指数',
                'text': '外溢指数上升',
                'value': 0.62,
                'unit': 'ratio',
                'evidence_ids': [id],
              },
          ],
          'recommendation': '关注外溢。',
          'limitations': <String>[],
        };
      }),
      invoker: FakeInvoker(
        values: {'systemic_risk': 0.62, 'funding_cost': 60.0},
      ),
    );
    return InvestigationController(
      runtime: AgentRuntime(settings),
      settings: settings,
    );
  }

  test('run 返回冷流：每次监听重新执行', () async {
    final c = controller();
    final first = await c.run('评估 2024-08-05 风险', runId: 'r1').toList();
    final second = await c.run('评估 2024-08-05 风险', runId: 'r1').toList();
    expect(first.whereType<RunStarted>(), hasLength(1));
    expect(second.whereType<RunStarted>(), hasLength(1));
    expect(first.whereType<RunFinished>(), hasLength(1));
    expect(second.whereType<RunFinished>(), hasLength(1));
  });

  test('lastSummary 返回最近摘要，字段齐全', () async {
    final c = controller();
    await c.run('评估 2024-08-05 风险', runId: 'r2').toList();
    final summary = await c.lastSummary('r2');
    expect(summary, isNotNull);
    expect(summary!.runId, 'r2');
    expect(summary.mode, 'collaborative');
    expect(summary.riskLevel, isIn(['low', 'medium', 'high', 'critical']));
    expect(summary.claimIds, isNotEmpty);
    expect(summary.evidenceIds, isNotEmpty);
    expect(summary.partial, isFalse);
  });

  test('cancel 后不再产出后续事件', () async {
    final c = controller();
    await c.cancel('r3');
    final events = await c.run('评估 2024-08-05 风险', runId: 'r3').toList();
    // 已取消的 run 不产出任何事件（冷流 + 取消标记）。
    expect(events, isEmpty);
    expect(await c.lastSummary('r3'), isNull);
  });

  test('运行中取消 → 在阶段边界停止，不产出最终结论', () async {
    final slow = ScriptedGenerator((_, _) {
      throw const LlmFailure(
        code: LlmFailureCode.timeout,
        message: '模型响应超时。',
        retryable: false,
      );
    });
    final settings = settingsFor(
      generator: slow,
      invoker: FakeInvoker(values: {'systemic_risk': 0.62}),
    );
    final c = InvestigationController(
      runtime: AgentRuntime(settings),
      settings: settings,
    );
    final events = <RunEvent>[];
    final subscription = c
        .run('评估 2024-08-05 风险', runId: 'r3b')
        .listen(events.add);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    await c.cancel('r3b');
    await Future<void>.delayed(const Duration(seconds: 2));
    await subscription.cancel();
    expect(events.whereType<RunStarted>(), isNotEmpty);
    expect(events.whereType<RunFinished>(), isEmpty);
  });

  test('asOf 从问题中的日期解析，缺失时取当前时间', () async {
    final c = controller();
    final dated = await c.run('评估 2024-08-05 风险', runId: 'r4').toList();
    expect(dated.whereType<RunFinished>(), hasLength(1));
    final undated = await c.run('评估当前风险', runId: 'r5').toList();
    expect(undated.whereType<RunFinished>(), hasLength(1));
  });

  test('未配置模型 → RunFailed 且引导设置页（零 Mock）', () async {
    final settings = settingsFor(
      generator: null,
      invoker: FakeInvoker(values: {'systemic_risk': 0.62}),
    );
    final c = InvestigationController(
      runtime: AgentRuntime(settings),
      settings: settings,
    );
    final events = await c.run('评估 2024-08-05 风险', runId: 'r6').toList();
    expect(events.whereType<RunFailed>(), hasLength(1));
    expect(events.whereType<RunFinished>(), isEmpty);
  });
}
