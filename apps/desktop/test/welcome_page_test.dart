import 'dart:io';

import 'package:cbr_maw/app/app_scope.dart';
import 'package:cbr_maw/app/app_state.dart';
import 'package:cbr_maw/app/data_mode.dart';
import 'package:cbr_maw/app/key_verifier.dart';
import 'package:cbr_maw/app/preferences.dart';
import 'package:cbr_maw/app/ui.dart';
import 'package:cbr_maw/features/onboarding/welcome_page.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 屏 1 + 屏 2 的界面行为：trim、永不复显明文、三态错误、只读入口。
final class _FakeProber implements KeyProber {
  _FakeProber(this.result);

  final KeyProbeResult result;
  final List<String> received = [];

  @override
  Future<KeyProbeResult> verify(String key) async {
    received.add(key);
    return result;
  }
}

void main() {
  late Directory tmp;
  late AppState state;
  late UiPreferences prefs;

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('cbr-welcome-test-');
    state = await AppState.bootstrap([
      '--data-home',
      tmp.path,
      '--resource-home',
      tmp.path,
    ]);
    SharedPreferences.setMockInitialValues({});
    prefs = await UiPreferences.load();
  });

  tearDown(() async {
    await state.shutdown();
    tmp.deleteSync(recursive: true);
  });

  Future<void> pump(WidgetTester tester, KeyProber prober) async {
    await tester.pumpWidget(
      AppStateScope(
        state: state,
        preferences: prefs,
        child: MaterialApp(
          theme: ThemeData(splashFactory: NoSplash.splashFactory),
          home: WelcomePage(prober: prober),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('粘贴值必须 trim（CRLF 陷阱）', (tester) async {
    // 用失败态探针：校验请求发生在写盘之前，可在 widget 测试里断言 trim。
    final prober = _FakeProber(
      const KeyProbeResult(
        KeyProbeOutcome.unauthorized,
        '密钥无效或已过期',
        '换一把 key',
        '无法调用模型',
      ),
    );
    await pump(tester, prober);
    await tester.enterText(find.byType(TextField).first, '  sk-test-1234\r\n');
    await tester.tap(find.text('验证并继续'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 100));
    expect(prober.received.single, 'sk-test-1234');
  });

  test('密钥落盘前 trim（CRLF 不进密钥库）', () async {
    await state.saveSecret(SecretSlot.deepseek, '  sk-test-1234\r\n');
    expect(await state.secrets.read('deepseek'), 'sk-test-1234');
    expect(state.masked(SecretSlot.deepseek), 'sk-****1234');
  });

  testWidgets('密钥输入永不复显明文', (tester) async {
    await pump(tester, _FakeProber(KeyProbeResult.ok));
    await tester.enterText(find.byType(TextField).first, 'sk-very-secret-9999');
    await tester.pump();
    final field = tester.widget<TextField>(find.byType(TextField).first);
    expect(field.obscureText, isTrue);
    // 只读文本（Text 组件）里不存在明文；输入框本身是密码模式。
    final texts = tester
        .widgetList<Text>(find.byType(Text))
        .map((t) => t.data ?? '')
        .where((d) => d.contains('very-secret'));
    expect(texts, isEmpty);
  });

  testWidgets('验证成功 → 进入数据模式三张卡片', (tester) async {
    await pump(tester, _FakeProber(KeyProbeResult.ok));
    await tester.enterText(find.byType(TextField).first, 'sk-ok-1234');
    // 写盘是真实 I/O：必须在 runAsync 里跑。
    await tester.runAsync(() async {
      await tester.tap(find.text('验证并继续'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await tester.pump();
    for (final mode in DataMode.values) {
      expect(find.text(mode.label), findsOneWidget);
    }
  });

  testWidgets('401 → 三段式错误分列，停在密钥页', (tester) async {
    await pump(
      tester,
      _FakeProber(
        const KeyProbeResult(
          KeyProbeOutcome.unauthorized,
          '密钥无效或已过期',
          '确认账号状态与余额，或换一把 key',
          '无法调用模型；其余功能仍可用',
        ),
      ),
    );
    await tester.enterText(find.byType(TextField).first, 'sk-bad-1234');
    await tester.tap(find.text('验证并继续'));
    await tester.pumpAndSettle();
    expect(find.text('密钥无效或已过期'), findsOneWidget);
    expect(find.textContaining('怎么改：'), findsOneWidget);
    expect(find.textContaining('影响：'), findsOneWidget);
    expect(find.text('填写主模型密钥'), findsOneWidget);
    // 未保存任何密钥。
    expect(state.hasApiKey, isFalse);
  });

  testWidgets('代理态与网络态文案不同', (tester) async {
    await pump(
      tester,
      _FakeProber(
        const KeyProbeResult(
          KeyProbeOutcome.proxy,
          '代理拒绝或不可达',
          '检查设置 → 网络中的代理地址',
          '仅影响模型调用；本地数据仍可浏览',
        ),
      ),
    );
    await tester.enterText(find.byType(TextField).first, 'sk-x-1234');
    await tester.tap(find.text('验证并继续'));
    await tester.pumpAndSettle();
    expect(find.text('代理拒绝或不可达'), findsOneWidget);
  });

  testWidgets('稍后再说 → 只读模式，标记完成但无密钥', (tester) async {
    await pump(tester, _FakeProber(KeyProbeResult.ok));
    await tester.tap(find.text('稍后再说（只读模式）'));
    await tester.pumpAndSettle();
    expect(prefs.readOnly, isTrue);
    expect(prefs.onboardingComplete, isTrue);
    expect(state.hasApiKey, isFalse);
  });
}
