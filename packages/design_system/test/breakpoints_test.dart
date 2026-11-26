import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

void main() {
  group('断点判定（docs/07 §1.1）', () {
    test('边界值落在正确的档位', () {
      expect(CbrBreakpoint.fromWidth(0), CbrBreakpoint.compact);
      expect(CbrBreakpoint.fromWidth(599.9), CbrBreakpoint.compact);
      expect(CbrBreakpoint.fromWidth(600), CbrBreakpoint.medium);
      expect(CbrBreakpoint.fromWidth(839.9), CbrBreakpoint.medium);
      expect(CbrBreakpoint.fromWidth(840), CbrBreakpoint.expanded);
      expect(CbrBreakpoint.fromWidth(1099.9), CbrBreakpoint.expanded);
      expect(CbrBreakpoint.fromWidth(1100), CbrBreakpoint.large);
      expect(CbrBreakpoint.fromWidth(1439.9), CbrBreakpoint.large);
      expect(CbrBreakpoint.fromWidth(1440), CbrBreakpoint.xlarge);
      expect(CbrBreakpoint.fromWidth(1919.9), CbrBreakpoint.xlarge);
      expect(CbrBreakpoint.fromWidth(1920), CbrBreakpoint.xxlarge);
    });

    test('导航形态按断点切换', () {
      expect(CbrBreakpoint.compact.navMode, CbrNavMode.bottomBar);
      expect(CbrBreakpoint.medium.navMode, CbrNavMode.rail);
      expect(CbrBreakpoint.expanded.navMode, CbrNavMode.rail);
      expect(CbrBreakpoint.large.navMode, CbrNavMode.sidebar);
      expect(CbrBreakpoint.xxlarge.navMode, CbrNavMode.sidebar);
    });

    test('检视区在 1440 以上才常驻', () {
      expect(CbrBreakpoint.large.inspectorMode, CbrInspectorMode.overlay);
      expect(CbrBreakpoint.xlarge.inspectorMode, CbrInspectorMode.persistent);
      expect(CbrBreakpoint.xxlarge.hasPersistentInspector, isTrue);
      expect(CbrBreakpoint.large.hasPersistentInspector, isFalse);
    });

    test('页面边距与表格行高按档位取值', () {
      expect(CbrBreakpoint.compact.pageGutter, 12);
      expect(CbrBreakpoint.expanded.pageGutter, 20);
      expect(CbrBreakpoint.xlarge.pageGutter, 32);
      expect(CbrBreakpoint.compact.tableRowHeight, 44);
      expect(CbrBreakpoint.large.tableRowHeight, 36);
    });

    test('图表高度 clamp(0.42×宽, 下限, 上限)', () {
      expect(CbrBreakpoint.compact.chartHeight(200), 200);
      expect(CbrBreakpoint.large.chartHeight(500), 220);
      expect(CbrBreakpoint.large.chartHeight(2000), 420);
      expect(CbrBreakpoint.xxlarge.chartHeight(2000), 440);
    });
  });

  group('CbrLayoutBuilder 按内容宽度下发断点', () {
    testWidgets('子组件读到当前断点', (tester) async {
      CbrBreakpoint? seen;
      await tester.pumpWidget(
        CbrLayoutBuilder(
          builder: (context, breakpoint, constraints) {
            seen = breakpoint;
            return const SizedBox.shrink();
          },
        ),
      );
      // 默认测试窗口 800×600 → medium
      expect(seen, CbrBreakpoint.medium);
    });

    testWidgets('CbrBreakpointScope.of 可用', (tester) async {
      late CbrBreakpoint fromScope;
      await tester.pumpWidget(
        CbrLayoutBuilder(
          builder: (context, breakpoint, constraints) => Builder(
            builder: (inner) {
              fromScope = CbrBreakpointScope.of(inner);
              return const SizedBox.shrink();
            },
          ),
        ),
      );
      expect(fromScope, CbrBreakpoint.medium);
    });
  });
}
