import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

Widget host(Widget child) => MaterialApp(
  theme: CbrTheme.light(),
  home: Scaffold(body: child),
);

void main() {
  final items = <CbrNavItem>[
    const CbrNavItem(id: 'overview', label: '概览', icon: CbrIcons.database),
    const CbrNavItem(
      id: 'risk',
      label: '风险视图',
      icon: CbrIcons.riskHigh,
      badgeCount: 3,
    ),
    const CbrNavItem(id: 'sources', label: '来源台账', icon: CbrIcons.globe),
    const CbrNavItem(
      id: 'settings',
      label: '设置',
      icon: CbrIcons.settings,
      enabled: false,
    ),
  ];

  group('导航无障碍（docs/07 §5.4）', () {
    testWidgets('主导航容器带中文 label，当前项 selected', (tester) async {
      await tester.pumpWidget(
        host(
          SizedBox(
            height: 600,
            width: 800,
            child: CbrSideNav(
              items: items,
              selectedId: 'risk',
              onSelect: (_) {},
            ),
          ),
        ),
      );
      final SemanticsHandle handle = tester.ensureSemantics();
      expect(find.bySemanticsLabel('主导航'), findsOneWidget);
      final node = tester.getSemantics(find.text('风险视图'));
      expect(node.label, contains('风险视图'));
      expect(node.label, contains('3 条未读'));
      handle.dispose();
    });

    testWidgets('徽标计数朗读为「N 条未读」而不是裸数字', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(
        host(
          SizedBox(
            height: 600,
            width: 248,
            child: CbrSideNav(
              items: items,
              selectedId: 'overview',
              onSelect: (_) {},
            ),
          ),
        ),
      );
      expect(find.bySemanticsLabel('风险视图，3 条未读'), findsOneWidget);
      handle.dispose();
    });

    testWidgets('图标按钮必须有 Tooltip 与语义标签', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(
        host(
          CbrIconButton(
            icon: CbrIcons.download,
            label: '导出研判结果',
            onPressed: () {},
          ),
        ),
      );
      expect(find.byTooltip('导出研判结果'), findsOneWidget);
      expect(find.bySemanticsLabel('导出研判结果'), findsOneWidget);
      handle.dispose();
    });

    testWidgets('状态点有文字等价，不朗读为圆点', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(
        host(
          const CbrStatusDot(
            tone: CbrStatusTone.ok,
            label: '系统就绪',
            showLabel: true,
          ),
        ),
      );
      expect(find.bySemanticsLabel('系统就绪'), findsOneWidget);
      handle.dispose();
    });

    testWidgets('风险徽章文案自足', (tester) async {
      final handle = tester.ensureSemantics();
      await tester.pumpWidget(
        host(const CbrRiskBadge(level: CbrRiskLevel.high)),
      );
      expect(find.bySemanticsLabel('风险等级：高'), findsOneWidget);
      handle.dispose();
    });
  });

  group('应用外壳按断点切换导航形态', () {
    testWidgets('compact 用底部导航（4 项文字标签）', (tester) async {
      tester.view.physicalSize = const Size(400, 800);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(
        MaterialApp(
          theme: CbrTheme.light(),
          home: CbrAppShell(
            navItems: items,
            selectedNavId: 'overview',
            onSelectNav: (_) {},
            breadcrumbs: const <String>['工作台', '概览'],
            body: const SizedBox.expand(),
          ),
        ),
      );
      expect(find.byType(CbrMobileNavBar), findsOneWidget);
      // 底部导航必须带文字标签，不能只有图标（「概览」同时出现在面包屑与导航）。
      expect(
        find.descendant(
          of: find.byType(CbrMobileNavBar),
          matching: find.text('概览'),
        ),
        findsOneWidget,
      );
      expect(
        find.descendant(
          of: find.byType(CbrMobileNavBar),
          matching: find.text('风险视图'),
        ),
        findsOneWidget,
      );
    });

    testWidgets('xlarge 用 248dp 侧栏且检视区常驻', (tester) async {
      tester.view.physicalSize = const Size(1600, 1000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(
        MaterialApp(
          theme: CbrTheme.light(),
          home: CbrAppShell(
            navItems: items,
            selectedNavId: 'overview',
            onSelectNav: (_) {},
            breadcrumbs: const <String>['工作台', '概览'],
            body: const SizedBox.expand(),
            inspector: CbrInspector(
              title: '证据详情',
              onClose: () {},
              child: const Text('原文'),
            ),
          ),
        ),
      );
      final nav = tester.getSize(find.byType(CbrSideNav));
      expect(nav.width, CbrLayout.sidebarExpanded);
      expect(find.text('证据详情'), findsOneWidget);
    });

    testWidgets('折叠侧栏宽 64dp，仍保留 Tooltip 全名', (tester) async {
      tester.view.physicalSize = const Size(1600, 1000);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(
        MaterialApp(
          theme: CbrTheme.light(),
          home: CbrAppShell(
            navItems: items,
            selectedNavId: 'overview',
            onSelectNav: (_) {},
            breadcrumbs: const <String>['概览'],
            body: const SizedBox.expand(),
            navCollapsed: true,
          ),
        ),
      );
      expect(
        tester.getSize(find.byType(CbrSideNav)).width,
        CbrLayout.sidebarCollapsed,
      );
      expect(find.byTooltip('风险视图'), findsOneWidget);
    });
  });

  group('主题', () {
    test('浅深两套都装配出 Material 3 色板', () {
      final light = CbrTheme.light();
      final dark = CbrTheme.dark();
      expect(light.useMaterial3, isTrue);
      expect(dark.useMaterial3, isTrue);
      expect(light.colorScheme.brightness, Brightness.light);
      expect(dark.colorScheme.brightness, Brightness.dark);
      // 深色不是反色：页面底不是纯黑。
      expect(dark.scaffoldBackgroundColor, isNot(const Color(0xFF000000)));
    });

    test('焦点样式走独立 token，不依赖 hover', () {
      final theme = CbrTheme.light();
      expect(theme.focusColor, Colors.transparent);
    });
  });

  group('动效 reduce-motion', () {
    testWidgets('关闭动画时时长解析为 0', (tester) async {
      late Duration resolved;
      await tester.pumpWidget(
        CbrMotionScope(
          disableAnimations: true,
          child: Builder(
            builder: (context) {
              resolved = CbrMotionScope.duration(context, CbrMotion.slow);
              return const SizedBox.shrink();
            },
          ),
        ),
      );
      expect(resolved, Duration.zero);
    });
  });
}
