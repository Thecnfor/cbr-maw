import 'package:cbr_maw/genui/adapter/surface_bridge.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:genui/genui.dart' show Surface;
import 'package:material_ui/material_ui.dart';

/// 全部夹具均为显式 synthetic，不含任何真实业务数据。
void main() {
  testWidgets('白名单组件由官方 Surface 渲染（synthetic）', (tester) async {
    final bridge = SurfaceBridge();
    addTearDown(bridge.dispose);
    bridge.handleMessage(bridge.createSurface('synthetic-surface'));
    bridge.handleMessage(
      bridge.updateComponents('synthetic-surface', [
        {
          'id': 'root',
          'component': 'Column',
          'children': <String>['t1'],
        },
        {'id': 't1', 'component': 'Text', 'text': 'synthetic-hello'},
      ]),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Surface(surfaceContext: bridge.contextFor('synthetic-surface')),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('synthetic-hello'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('未登记组件被拒收并给出原因，不进入渲染（synthetic）', (tester) async {
    final bridge = SurfaceBridge();
    addTearDown(bridge.dispose);
    bridge.handleMessage(bridge.createSurface('synthetic-surface'));
    bridge.handleMessage(
      bridge.updateComponents('synthetic-surface', [
        {'id': 'root', 'component': 'SyntheticUnknownWidget'},
      ]),
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Surface(surfaceContext: bridge.contextFor('synthetic-surface')),
        ),
      ),
    );
    await tester.pumpAndSettle();

    final rejection = bridge.rejections.single;
    expect(rejection.componentKind, 'SyntheticUnknownWidget');
    expect(rejection.reason, contains('未登记'));
    // 未知组件从未进入 controller：surface 没有 root，Surface 渲染为空。
    expect(
      bridge.contextFor('synthetic-surface').definition.value?.components,
      isNot(contains('root')),
    );
    expect(find.byType(ErrorWidget), findsNothing);
    expect(tester.takeException(), isNull);
  });
}
