import 'package:cbr_maw/core/secret_store.dart';
import 'package:cbr_maw/app/layout/breakpoints.dart';
import 'package:cbr_maw/app/routes.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('路由表', () {
    test('四条顶层分支顺序 = 底部导航顺序', () {
      expect(Routes.branches, [
        '/overview',
        '/investigation',
        '/risk-cards',
        '/timeline',
      ]);
      final bottom = bottomNavItems().map((item) => item.path).toList();
      expect(bottom, Routes.branches);
    });

    test('路径一律英文 kebab-case', () {
      final kebab = RegExp(
        r'^/[a-z0-9]+(-[a-z0-9]+)*(/[a-z0-9]+(-[a-z0-9]+)*)*$',
      );
      for (final item in navItems) {
        expect(
          kebab.hasMatch(item.path),
          isTrue,
          reason: '${item.path} 不是 kebab-case',
        );
      }
    });

    test('侧栏承载其余页面且不重复', () {
      final paths = navItems.map((item) => item.path).toList();
      expect(paths.toSet().length, paths.length, reason: '导航路径重复');
      expect(
        paths,
        containsAll([
          Routes.sources,
          Routes.dataCards,
          Routes.scenarios,
          Routes.spatial,
          Routes.settings,
          Routes.diagnostics,
          Routes.onboarding,
          Routes.inbox,
        ]),
      );
    });

    test('详情路由带参数', () {
      expect(Routes.riskCard('cl_1'), '/risk-cards/cl_1');
      expect(Routes.evidence('ev_1'), '/evidence/ev_1');
      expect(Routes.timelineRun('run_1'), '/timeline/run_1');
    });

    test('分组顺序固定', () {
      expect(groupedNavItems().keys.toList(), ['工作台', '数据', '分析', '系统']);
    });

    test('分支索引按路径推导', () {
      expect(branchIndexFor('/risk-cards'), 2);
      expect(branchIndexFor('/risk-cards/cl_1'), 2);
      expect(branchIndexFor('/timeline/run_9'), 3);
      expect(branchIndexFor('/sources'), 0, reason: '非分支页面回落到 0');
    });

    test('深链规范化', () {
      expect(
        normalizeDeepLink('cbr-maw://risk-cards/ev_123'),
        '/risk-cards/ev_123',
      );
      expect(
        normalizeDeepLink('https://cbr.local/timeline/run_7'),
        '/timeline/run_7',
      );
      expect(normalizeDeepLink('cbr-maw://'), isNull);
      expect(normalizeDeepLink('ftp://x/y'), isNull);
    });
  });

  group('断点 → 导航形态', () {
    test('断点边界', () {
      expect(Breakpoint.of(599), Breakpoint.compact);
      expect(Breakpoint.of(600), Breakpoint.medium);
      expect(Breakpoint.of(839), Breakpoint.medium);
      expect(Breakpoint.of(840), Breakpoint.expanded);
      expect(Breakpoint.of(1099), Breakpoint.expanded);
      expect(Breakpoint.of(1100), Breakpoint.large);
      expect(Breakpoint.of(1440), Breakpoint.xlarge);
      expect(Breakpoint.of(1920), Breakpoint.xxlarge);
    });

    test('compact 底部导航 / medium+expanded Rail / large+ 侧栏', () {
      expect(NavLayout.forBreakpoint(Breakpoint.compact), NavLayout.bottomBar);
      expect(NavLayout.forBreakpoint(Breakpoint.medium), NavLayout.rail);
      expect(NavLayout.forBreakpoint(Breakpoint.expanded), NavLayout.rail);
      expect(NavLayout.forBreakpoint(Breakpoint.large), NavLayout.sidebar);
      expect(NavLayout.forBreakpoint(Breakpoint.xlarge), NavLayout.sidebar);
      expect(NavLayout.forBreakpoint(Breakpoint.xxlarge), NavLayout.sidebar);
    });

    test('侧栏宽度符合规范（248 / 折叠 64，Rail 72）', () {
      expect(NavMetrics.sidebarWidth, 248);
      expect(NavMetrics.sidebarCollapsedWidth, 64);
      expect(NavMetrics.railWidth, 72);
    });
  });

  group('密钥脱敏', () {
    test('永不回显明文', () {
      expect(maskSecret('sk-1234567890abcd'), 'sk-****abcd');
      expect(maskSecret('abcdefgh'), '****efgh');
      expect(maskSecret(''), '');
      expect(maskSecret('abc'), '****');
      expect(maskSecret('sk-1234567890abcd'), isNot(contains('1234567890')));
    });
  });
}
