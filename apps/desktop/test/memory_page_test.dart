import 'package:cbr_maw/app/theme/theme.dart';
import 'package:cbr_maw/app/ui.dart';
import 'package:cbr_maw/features/memory/memory_page.dart';
import 'package:flutter_test/flutter_test.dart';

/// 记忆页的渲染契约（数据全部 synthetic，不发 RPC）。
///
/// 断言重点：
/// - 三库计数逐项来自 stats，缺字段显示 `—` 而不是 0；
/// - 向量化降级时显示降级原因，不假装 ANN 可用；
/// - 检索结果为空时给明确说明，不是空白。
void main() {
  // 测试环境没有 material_ui 的 ink_sparkle 着色器，关掉水波纹。
  Widget wrap(Widget child) => MaterialApp(
    theme: AppTheme.dark().copyWith(splashFactory: NoSplash.splashFactory),
    home: child,
  );

  testWidgets('统计：三库计数与向量化状态（synthetic）', (tester) async {
    await tester.pumpWidget(
      wrap(
        Scaffold(
          body: MemoryPage(
            statsLoader: () async => {
              'rows': 42,
              'per_store': {'mi': 30, 'llr': 10, 'hlr': 2},
              'embedding_ready': true,
              'embed_dim': 512,
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('42'), findsOneWidget);
    expect(find.text('30'), findsOneWidget);
    expect(find.text('10'), findsOneWidget);
    expect(find.text('2'), findsOneWidget);
    expect(find.textContaining('已启用'), findsOneWidget);
  });

  testWidgets('统计缺失时显示 — 而不是 0（synthetic）', (tester) async {
    await tester.pumpWidget(
      wrap(
        Scaffold(
          body: MemoryPage(statsLoader: () async => const <String, Object?>{}),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('—'), findsWidgets);
    expect(find.text('0'), findsNothing);
  });

  testWidgets('向量化降级时显示分词器与原因（synthetic）', (tester) async {
    await tester.pumpWidget(
      wrap(
        Scaffold(
          body: MemoryPage(
            statsLoader: () async => {
              'rows': 3,
              'per_store': {'mi': 3, 'llr': 0, 'hlr': 0},
              'embedding_ready': false,
              'fts_tokenizer': 'icu',
              'embedding_error': '离线模型未安装',
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.textContaining('降级为全文检索'), findsOneWidget);
    expect(find.textContaining('离线模型未安装'), findsOneWidget);
  });

  testWidgets('检索：空结果给说明，非空逐条列出（synthetic）', (tester) async {
    var hits = <Map<String, Object?>>[];
    await tester.pumpWidget(
      wrap(
        Scaffold(
          body: MemoryPage(
            statsLoader: () async => const <String, Object?>{},
            searchLoader: ({
              required String asOf,
              required String query,
              int topK = 8,
            }) async => hits,
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), '北向资金');
    // 标题与按钮同名，用按钮类型定位。
    await tester.tap(find.widgetWithText(FilledButton, '检索'));
    await tester.pumpAndSettle();
    expect(find.textContaining('没有命中'), findsOneWidget);

    hits = [
      {
        'id': 'mi:synthetic:1',
        'store': 'mi',
        'as_of': '2024-01-02',
        'text': '合成记录：北向净流出（synthetic）',
      },
    ];
    // 标题与按钮同名，用按钮类型定位。
    await tester.tap(find.widgetWithText(FilledButton, '检索'));
    await tester.pumpAndSettle();
    expect(find.textContaining('合成记录'), findsOneWidget);
  });
}
