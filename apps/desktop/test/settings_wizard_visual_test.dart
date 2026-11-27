import 'dart:io';

import 'package:cbr_maw/app/app_scope.dart';
import 'package:cbr_maw/app/app_state.dart';
import 'package:cbr_maw/app/preferences.dart';
import 'package:cbr_maw/app/theme/theme.dart';
import 'package:cbr_maw/app/ui.dart';
import 'package:cbr_maw/features/settings/settings_page.dart';


import 'package:flutter/services.dart' show ByteData, FontLoader;
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 首次运行向导的视觉回归（docs/06 §2–§5）。
///
/// 存在理由：在 Xvfb 上跑真实二进制时，标题出现了源码里不存在的黄色下划线与
/// 红色步骤文字。要么是主题泄漏（text-decoration / 语义色误用），要么是软件
/// 渲染器的字体回退产物。golden 用 Skia 在测试环境渲染，可以区分两者：
/// 若 golden 干净而真机脏 → 渲染器；若 golden 同样脏 → 代码。
/// 载入系统中文字体：Flutter 测试环境默认只有 Ahem（全是豆腐块），
/// 不载字体时 golden 无法用于评审排版。
Future<void> _loadCjkFont() async {
  // 常规与粗体都要载入：只载常规时，w600/w700 的字形会回落到 Ahem（豆腐块）。
  const faces = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
  ];
  final loader = FontLoader('Roboto');
  var loaded = 0;
  for (final path in faces) {
    final file = File(path);
    if (!file.existsSync()) {
      continue;
    }
    final bytes = await file.readAsBytes();
    loader.addFont(Future.value(ByteData.sublistView(bytes)));
    loaded++;
  }
  if (loaded > 0) {
    await loader.load();
  }
}

void main() {
  setUpAll(_loadCjkFont);

  late Directory tmp;
  late AppState state;
  late UiPreferences prefs;

  setUp(() async {
    tmp = Directory.systemTemp.createTempSync('cbr-wizard-visual-');
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

  Future<void> pumpWizard(WidgetTester tester) async {
    await tester.pumpWidget(
      AppStateScope(
        state: state,
        preferences: prefs,
        child: MaterialApp(
          theme: AppTheme.dark(),
          home: const Scaffold(body: SettingsPage(firstRun: true)),
        ),
      ),
    );
    await tester.pumpAndSettle();
  }

  testWidgets('标题无下划线、步骤条不用 danger 色（synthetic）', (tester) async {
    await pumpWizard(tester);

    final underlined = <String>[];
    for (final text in tester.widgetList<Text>(find.byType(Text))) {
      final decoration = text.style?.decoration;
      if (decoration != null && decoration != TextDecoration.none) {
        underlined.add('${text.data} → $decoration');
      }
    }
    expect(underlined, isEmpty, reason: '出现下划线装饰：$underlined');

    final danger = AppTheme.dark().colorScheme.error;
    for (final label in ['填写主模型密钥', '选择数据模式', '开始第一次研判']) {
      final finder = find.text(label);
      if (finder.evaluate().isEmpty) {
        continue;
      }
      expect(
        tester.widget<Text>(finder.first).style?.color,
        isNot(danger),
        reason: '步骤「$label」被渲染成 danger 色',
      );
    }

    expect(find.text('首次运行'), findsOneWidget);
  });

  testWidgets('golden 快照（synthetic，1280×800）', (tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 800));
    addTearDown(() => tester.binding.setSurfaceSize(null));

    await pumpWizard(tester);

    await expectLater(
      find.byType(Scaffold),
      matchesGoldenFile('goldens/settings_wizard_dark.png'),
    );
  });
}
