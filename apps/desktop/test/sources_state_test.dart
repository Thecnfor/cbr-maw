import 'package:cbr_maw/app/ui.dart';
import 'package:cbr_maw/app/widgets/chips.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:flutter_test/flutter_test.dart';

/// 屏 7：五态徽标 + 覆盖期 + 陈旧度；缺失与 0 必须可区分。
void main() {
  group('来源五态徽标', () {
    test('五态标签固定且文字自足', () {
      expect(SourceStateChip.labelFor(SourceState.reachable), '已获取');
      expect(SourceStateChip.labelFor(SourceState.needAuth), '需授权');
      expect(SourceStateChip.labelFor(SourceState.needLogin), '需登录');
      expect(SourceStateChip.labelFor(SourceState.restricted), '反爬受限');
      expect(SourceStateChip.labelFor(SourceState.unreachable), '反爬受限');
      // 陈旧是第五态的独立标签。
      expect(
        SourceStateChip.labelFor(SourceState.reachable, stale: true),
        '已过期',
      );
    });

    testWidgets('不可达来源不显示任何数值占位', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: Column(
              children: const [
                SourceStateChip(state: SourceState.needAuth),
                SourceStateChip(state: SourceState.reachable, stale: true),
              ],
            ),
          ),
        ),
      );
      expect(find.text('需授权'), findsOneWidget);
      expect(find.text('已过期'), findsOneWidget);
      // 不允许出现 0 / -- / N/A 之类的占位数值。
      for (final placeholder in ['0', '--', '—', 'N/A', 'null']) {
        expect(find.text(placeholder), findsNothing);
      }
    });
  });

  group('健康度字段', () {
    test('覆盖期可缺省为 null（不伪造）', () {
      const entry = HealthEntry(
        sourceId: 'src1',
        stale: false,
        state: SourceState.reachable,
      );
      expect(entry.coverageStart, isNull);
      expect(entry.coverageEnd, isNull);
      expect(entry.lastSuccessAt, isNull);
    });
  });
}
