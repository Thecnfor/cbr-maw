import 'dart:async';
import 'dart:io';

import 'package:cbr_maw/agents/investigation_controller.dart';
import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:cbr_maw/agents/run_events.dart';
import 'package:cbr_maw/app/app_scope.dart';
import 'package:cbr_maw/app/app_state.dart';
import 'package:cbr_maw/app/preferences.dart';
import 'package:cbr_maw/app/ui.dart';
import 'package:cbr_maw/features/investigation/investigation_page.dart';
import 'package:cbr_maw/features/investigation/investigation_rules.dart';
import 'package:flutter/services.dart' show LogicalKeyboardKey;
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';

import 'agents/fixtures.dart';

/// 生成器：在放行前一直挂起，用来把研判保持在「进行中」。
final class _GatedGenerator implements TextGenerator {
  _GatedGenerator(this.gate);

  final Completer<void> gate;

  @override
  Future<LlmResponse> generateJson({
    required String system,
    required String user,
    required String purpose,
  }) async {
    final id = RegExp(r'"evidence_id":"(ev_[^"]+)"').firstMatch(user)?.group(1);
    await gate.future;
    return LlmResponse(
      json: {
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
      },
      usage: const LlmUsage(prompt: 10, completion: 5),
      latencyMs: 1,
      attempts: 1,
    );
  }
}

/// 屏 4：Ctrl+Enter 发送、Esc 中断保留、只读置灰、缺证据 claim 不可见。
void main() {
  group('研判纯规则', () {
    test('缺证据的 claim 不可见', () {
      expect(InvestigationRules.isVisible(const []), isFalse);
      expect(InvestigationRules.isVisible(['ev_1']), isTrue);
    });

    test('数值结论标「以工具重算为准」', () {
      expect(InvestigationRules.needsRecomputeNote('numeric'), isTrue);
      expect(InvestigationRules.needsRecomputeNote('text'), isFalse);
      expect(InvestigationRules.needsRecomputeNote('directional'), isFalse);
    });

    test('摘要含部分结论与降级角色', () {
      final text = InvestigationRules.summaryText(
        RunSummary(
          runId: 'r1',
          mode: 'collaborative',
          riskLevel: 'high',
          claimIds: const ['c1'],
          evidenceIds: const ['ev1'],
          conflictIds: const [],
          degradedRoles: const ['regulator'],
          limitations: const ['来源不可达'],
          tokensUsed: 10,
          costUsd: 0,
          partial: true,
        ),
        hiddenClaims: 2,
      );
      expect(text, contains('部分结论'));
      expect(text, contains('降级角色：监管方'));
      expect(text, contains('2 条无证据结论已丢弃'));
      expect(text, contains('风险等级：高'));
    });
  });

  group('对话研判界面', () {
    late Directory tmp;
    late AppState state;
    late AppState stateWithoutKey;
    late UiPreferences prefs;

    setUp(() async {
      tmp = Directory.systemTemp.createTempSync('cbr-investigation-test-');
      state = await AppState.bootstrap([
        '--data-home',
        tmp.path,
        '--resource-home',
        tmp.path,
      ]);
      // 已有主模型密钥 → 研判入口可用。
      await state.saveSecret(SecretSlot.deepseek, 'sk-test-1234');
      stateWithoutKey = await AppState.bootstrap([
        '--data-home',
        p.join(tmp.path, 'nokey'),
        '--resource-home',
        tmp.path,
      ]);
      SharedPreferences.setMockInitialValues({});
      prefs = await UiPreferences.load();
    });

    tearDown(() async {
      await state.shutdown();
      await stateWithoutKey.shutdown();
      tmp.deleteSync(recursive: true);
    });

    Future<void> pump(
      WidgetTester tester, {
      AppState? appState,
      Completer<void>? gate,
    }) async {
      final settings = settingsFor(
        generator: gate == null
            ? ScriptedGenerator((_, user) {
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
              })
            : _GatedGenerator(gate),
        invoker: FakeInvoker(
          values: {'systemic_risk': 0.62, 'funding_cost': 60.0},
        ),
      );
      final controller = InvestigationController(
        runtime: AgentRuntime(settings),
        settings: settings,
      );
      final target = appState ?? state;
      await tester.pumpWidget(
        AppStateScope(
          state: target,
          preferences: prefs,
          child: MaterialApp(
            theme: ThemeData(splashFactory: NoSplash.splashFactory),
            // 生产环境由外壳 Scaffold 承载；测试里补上 Material 祖先。
            home: Scaffold(
              body: InvestigationPage(state: target, controller: controller),
            ),
          ),
        ),
      );
      await tester.pump();
    }

    testWidgets('Ctrl+Enter 发送；Shift+Enter 换行不发送', (tester) async {
      await pump(tester);
      final field = find.byType(TextField).first;
      await tester.enterText(field, '评估跨境风险');
      await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
      await tester.pump();
      expect(find.text('我'), findsNothing);

      await tester.sendKeyDownEvent(LogicalKeyboardKey.controlLeft);
      await tester.sendKeyEvent(LogicalKeyboardKey.enter);
      await tester.sendKeyUpEvent(LogicalKeyboardKey.controlLeft);
      await tester.pump();
      expect(find.text('我'), findsOneWidget);
    });

    testWidgets('Esc 停止并保留已生成内容，标「已中断」', (tester) async {
      final gate = Completer<void>();
      addTearDown(gate.complete);
      await pump(tester, gate: gate);
      await tester.enterText(find.byType(TextField).first, '评估跨境风险');
      await tester.tap(find.text('发送'));
      await tester.pump();
      expect(find.text('停止生成（Esc）'), findsOneWidget);
      await tester.sendKeyEvent(LogicalKeyboardKey.escape);
      await tester.pump();
      expect(find.textContaining('已中断'), findsWidgets);
      expect(find.text('我'), findsOneWidget);
    });

    testWidgets('停止生成按钮同样保留内容并标「已中断」', (tester) async {
      final gate = Completer<void>();
      addTearDown(gate.complete);
      await pump(tester, gate: gate);
      await tester.enterText(find.byType(TextField).first, '评估跨境风险');
      await tester.tap(find.text('发送'));
      await tester.pump();
      await tester.tap(find.text('停止生成（Esc）'));
      await tester.pump();
      expect(find.textContaining('已中断'), findsWidgets);
      expect(find.text('我'), findsOneWidget);
    });


    testWidgets('研判完成后展示决策面板：主张/证据/冲突/降级/局限', (tester) async {
      await pump(tester);
      await tester.enterText(find.byType(TextField).first, '评估跨境风险');
      await tester.tap(find.text('发送'));
      // 冷流 + 真实 I/O 的完成需要跑真实时钟。
      await tester.runAsync(() async {
        await Future<void>.delayed(const Duration(milliseconds: 200));
      });
      await tester.pump();
      // 用设计系统的结论面板：标题「研判结论」+ 过程指标一行。
      expect(find.text('研判结论'), findsOneWidget);
      expect(find.textContaining('模式：'), findsWidgets);
      // 结论卡必须绑定证据：过程指标里证据数 > 0。
      expect(find.textContaining('证据 '), findsOneWidget);
      final supports = tester
          .widgetList<Text>(find.byType(Text))
          .map((t) => t.data ?? '')
          .firstWhere((d) => d.contains('证据 '));
      final evidenceCount = int.parse(
        RegExp(r'证据 (\d+) 条').firstMatch(supports)!.group(1)!,
      );
      expect(evidenceCount, greaterThan(0));
    });

    testWidgets('只读模式：研判入口置灰并说明原因', (tester) async {
      await prefs.enterReadOnly();
      await pump(tester, appState: stateWithoutKey);
      expect(find.textContaining('只读模式'), findsWidgets);
      expect(find.textContaining('研判入口不可用'), findsWidgets);
      final field = tester.widget<TextField>(find.byType(TextField).first);
      expect(field.enabled, isFalse);
    });
  });
}
