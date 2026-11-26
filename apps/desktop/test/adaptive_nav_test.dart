import 'package:cbr_maw/app/layout/breakpoints.dart';
import 'package:cbr_maw/app/routes.dart';
import 'package:cbr_maw/app/shell/app_sidebar.dart';
import 'package:cbr_maw/app/ui.dart';
import 'package:flutter_test/flutter_test.dart';

/// 只验证导航形态本身（不依赖 AppState / sidecar）。
void main() {
  Future<void> pumpAt(WidgetTester tester, double width) async {
    tester.view.physicalSize = Size(width, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(splashFactory: NoSplash.splashFactory),
        home: Scaffold(
          body: LayoutBuilder(
            builder: (context, constraints) {
              final layout = NavLayout.forBreakpoint(
                Breakpoint.of(constraints.maxWidth),
              );
              return switch (layout) {
                NavLayout.bottomBar => AppBottomNav(
                  currentIndex: 0,
                  onSelect: (_) {},
                ),
                NavLayout.rail => AppRail(
                  currentLocation: Routes.overview,
                  onSelect: (_) {},
                ),
                NavLayout.sidebar => AppSidebar(
                  currentLocation: Routes.overview,
                  collapsed: false,
                  onSelect: (_) {},
                  onToggleCollapsed: () {},
                ),
              };
            },
          ),
        ),
      ),
    );
  }

  testWidgets('窄屏（<600）→ 底部导航，4 项', (tester) async {
    await pumpAt(tester, 480);
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.byType(NavigationRail), findsNothing);
    expect(find.byType(AppSidebar), findsNothing);
    final bar = tester.widget<NavigationBar>(find.byType(NavigationBar));
    expect(bar.destinations.length, 4);
    expect(
      bar.destinations.map((d) => (d as NavigationDestination).label).toList(),
      ['概览', '对话式研判', '风险卡', '时间线'],
    );
  });

  testWidgets('中档（600–1099）→ NavigationRail', (tester) async {
    await pumpAt(tester, 900);
    expect(find.byType(NavigationRail), findsOneWidget);
    expect(find.byType(NavigationBar), findsNothing);
    expect(find.byType(AppSidebar), findsNothing);
  });

  testWidgets('宽屏（≥1100）→ 侧栏 248dp', (tester) async {
    await pumpAt(tester, 1400);
    expect(find.byType(AppSidebar), findsOneWidget);
    expect(find.byType(NavigationRail), findsNothing);
    expect(find.byType(NavigationBar), findsNothing);
    final box = tester.getSize(find.byType(AppSidebar));
    expect(box.width, NavMetrics.sidebarWidth);
  });

  testWidgets('侧栏折叠为 64dp 且 tooltip 保留完整名称', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(splashFactory: NoSplash.splashFactory),
        home: Scaffold(
          body: AppSidebar(
            currentLocation: Routes.overview,
            collapsed: true,
            onSelect: (_) {},
            onToggleCollapsed: () {},
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(
      tester.getSize(find.byType(AppSidebar)).width,
      NavMetrics.sidebarCollapsedWidth,
    );
    expect(find.byType(Tooltip), findsWidgets);
  });

  testWidgets('侧栏点击导航项回调正确路径', (tester) async {
    tester.view.physicalSize = const Size(1400, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
    String? tapped;
    await tester.pumpWidget(
      MaterialApp(
        theme: ThemeData(splashFactory: NoSplash.splashFactory),
        home: Scaffold(
          body: AppSidebar(
            currentLocation: Routes.overview,
            collapsed: false,
            onSelect: (path) => tapped = path,
            onToggleCollapsed: () {},
          ),
        ),
      ),
    );
    await tester.tap(find.text('来源台账'));
    expect(tapped, Routes.sources);
  });
}
