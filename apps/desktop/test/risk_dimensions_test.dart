import 'package:cbr_maw/app/widgets/dimensions.dart';
import 'package:cbr_maw/app/widgets/synthetic.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:cbr_maw/app/ui.dart';

Widget _host(Widget child) => MaterialApp(
  home: Scaffold(body: SingleChildScrollView(child: child)),
);

void main() {
  group('六维分解', () {
    testWidgets('缺失维度写「未计入」而不是 0', (tester) async {
      await tester.pumpWidget(
        _host(
          const DimensionBreakdown(
            dims: {
              'dim_equity': 0.42,
              'dim_global': {'value': 0.61},
            },
            missingDims: ['dim_credit'],
            absenceReasons: {'dim_credit': '未计入（需授权）'},
          ),
        ),
      );
      expect(find.text('股票'), findsOneWidget);
      expect(find.text('信用'), findsOneWidget);
      // 有值的维度显示三位小数。
      expect(find.text('0.420'), findsOneWidget);
      expect(find.text('0.610'), findsOneWidget);
      // 缺失维度：文案明确，且不出现 0.000。
      expect(find.text('未计入（需授权）'), findsOneWidget);
      expect(find.text('0.000'), findsNothing);
    });

    testWidgets('缺席维度顺序固定且占位不隐藏', (tester) async {
      await tester.pumpWidget(
        _host(
          const DimensionBreakdown(
            dims: {},
            missingDims: ['dim_equity', 'dim_bond'],
          ),
        ),
      );
      for (final dim in sixDimensions) {
        expect(find.text(dim.label), findsOneWidget);
      }
      // dims 全空 → 六维全部按缺失呈现，不隐藏也不补 0。
      expect(find.text('未计入（数据不足）'), findsNWidgets(6));
    });

    test('缺席原因按来源五态推导', () {
      expect(absenceReason(SourceState.needAuth), '未计入（需授权）');
      expect(absenceReason(SourceState.needLogin), '未计入（需授权）');
      expect(absenceReason(SourceState.restricted), '未计入（不可达）');
      expect(absenceReason(SourceState.unreachable), '未计入（不可达）');
      expect(absenceReason(null), '未计入（数据不足）');
    });
  });

  group('SYNTHETIC 标记', () {
    testWidgets('角标文字自足，不依赖颜色', (tester) async {
      await tester.pumpWidget(_host(const SyntheticBadge()));
      expect(find.textContaining(SyntheticBadge.marker), findsOneWidget);
      expect(find.textContaining('不可用于投资或监管决策'), findsOneWidget);
    });

    testWidgets('全局顶部条', (tester) async {
      await tester.pumpWidget(_host(const SyntheticTopBar()));
      expect(find.textContaining('SYNTHETIC'), findsOneWidget);
    });
  });
}
