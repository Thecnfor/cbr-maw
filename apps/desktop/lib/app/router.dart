import 'dart:async';

import 'package:go_router/go_router.dart';

import './ui.dart';

import '../agents/investigation_controller.dart';
import '../features/data_cards/data_cards_page.dart';
import '../features/diagnostics/diagnostics_page.dart';
import '../features/evidence/evidence_page.dart';
import '../features/inbox/inbox_page.dart';
import '../features/investigation/investigation_page.dart';
import '../features/onboarding/onboarding_page.dart';
import '../features/onboarding/welcome_page.dart';
import '../features/overview/overview_page.dart';
import '../features/risk_cards/risk_cards_page.dart';
import '../features/scenarios/scenarios_page.dart';
import '../features/settings/settings_page.dart';
import '../features/sources/sources_page.dart';
import '../features/timeline/timeline_page.dart';
import 'app_state.dart';
import 'preferences.dart';
import 'routes.dart';
import 'shell/app_shell.dart';
import 'theme/tokens.dart';

/// 应用路由装配。
///
/// - 四条顶层分支（StatefulShellRoute.indexedStack）：/overview、/investigation、
///   /risk-cards、/timeline；
/// - 其余页面挂在根导航上（侧栏进入，不占用底部导航）；
/// - 未配置密钥 → redirect 到 /settings/first-run；
/// - errorBuilder 渲染中文 404。
final class AppRouter {
  /// 装配 router。
  AppRouter({
    required this.state,
    required this.controller,
    required this.preferences,
    required this.onOpenPalette,
  });

  /// 应用状态。
  final AppState state;

  /// 研判控制器。
  final InvestigationController controller;

  /// 界面偏好（折叠 / 主题）；shell 内部订阅，避免重建 router 丢导航状态。
  final UiPreferences preferences;

  /// 打开命令面板。
  final VoidCallback onOpenPalette;

  late final GoRouter router = _build();

  /// 深链入口：`cbr-maw://` 与 `http(s)://` 都规范化成内部路由。
  String? initialLocationFrom(String? launchUri) {
    if (launchUri == null) {
      return null;
    }
    return normalizeDeepLink(launchUri);
  }

  GoRouter _build() {
    AppShellNavigator.register((path) => router.go(path));
    return GoRouter(
      initialLocation: Routes.overview,
      debugLogDiagnostics: false,
      redirect: (context, routerState) {
        final location = routerState.uri.path;
        final onWelcome = location == Routes.welcome;
        // 首次上手：填密钥 / 选数据模式 / 显式只读，缺一不可。
        if (!preferences.onboardingComplete && !onWelcome) {
          return Routes.welcome;
        }
        // 已配密钥但未选数据模式 → 回上手页补选。
        if (preferences.onboardingComplete &&
            preferences.dataMode == null &&
            !onWelcome) {
          return Routes.welcome;
        }
        final needsSetup = !state.hasApiKey;
        final onFirstRun = location == Routes.settingsFirstRun;
        if (needsSetup && !preferences.readOnly && !onFirstRun && !onWelcome) {
          return Routes.settingsFirstRun;
        }
        return null;
      },
      errorBuilder: (context, routerState) =>
          _NotFoundPage(location: routerState.uri.toString()),
      routes: [
        StatefulShellRoute.indexedStack(
          builder: (context, shellState, navigationShell) => ListenableBuilder(
            listenable: Listenable.merge([preferences, state.inboxLog]),
            builder: (context, _) => AppShell(
              navigationShell: navigationShell,
              collapsed: preferences.nav.collapsed,
              onToggleCollapsed: preferences.setNavCollapsed,
              onOpenPalette: onOpenPalette,
              kernelStateLabel: state.kernelState.label,
              kernelReady: state.kernelState.name == 'ready',
              clock: _clockLabel(),
              synthetic: preferences.dataMode?.synthetic ?? false,
              pendingInbox: state.inboxLog.pendingCount,
              sidebarFooter: _SidebarFooter(
                kernelReady: state.kernelState.name == 'ready',
                themeMode: preferences.themeMode,
                onToggleTheme: () {
                  final next = preferences.themeMode == ThemeMode.dark
                      ? ThemeMode.light
                      : ThemeMode.dark;
                  unawaited(preferences.setThemeMode(next));
                },
              ),
            ),
          ),
          branches: [
            StatefulShellBranch(
              routes: [
                GoRoute(
                  path: Routes.overview,
                  builder: (context, _) => OverviewPage(state: state),
                ),
              ],
            ),
            StatefulShellBranch(
              routes: [
                GoRoute(
                  path: Routes.investigation,
                  builder: (context, _) =>
                      InvestigationPage(state: state, controller: controller),
                ),
              ],
            ),
            StatefulShellBranch(
              routes: [
                GoRoute(
                  path: Routes.riskCards,
                  builder: (context, _) => RiskCardsPage(state: state),
                  routes: [
                    GoRoute(
                      path: ':claimId',
                      builder: (context, routeState) => RiskCardDetailPage(
                        state: state,
                        claimId: routeState.pathParameters['claimId'] ?? '',
                      ),
                    ),
                  ],
                ),
              ],
            ),
            StatefulShellBranch(
              routes: [
                GoRoute(
                  path: Routes.timeline,
                  builder: (context, _) => TimelinePage(state: state),
                  routes: [
                    GoRoute(
                      path: ':runId',
                      builder: (context, routeState) => TimelineRunPage(
                        runId: routeState.pathParameters['runId'] ?? '',
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ],
        ),
        GoRoute(
          path: Routes.sources,
          builder: (context, _) => SourcesPage(state: state),
        ),
        GoRoute(
          path: Routes.dataCards,
          builder: (context, _) => const DataCardsPage(),
        ),
        GoRoute(
          path: Routes.scenarios,
          builder: (context, _) => const ScenariosPage(),
        ),
        GoRoute(
          path: Routes.spatial,
          builder: (context, _) => const SpatialPage(),
        ),
        GoRoute(path: Routes.inbox, builder: (context, _) => const InboxPage()),
        GoRoute(
          path: Routes.welcome,
          builder: (context, _) => const WelcomePage(),
        ),
        GoRoute(
          path: Routes.onboarding,
          builder: (context, _) => const OnboardingPage(),
        ),
        GoRoute(
          path: Routes.diagnostics,
          builder: (context, _) => const DiagnosticsPage(),
        ),
        GoRoute(
          path: Routes.settings,
          builder: (context, _) => const SettingsPage(),
          routes: [
            GoRoute(
              path: 'first-run',
              builder: (context, _) => const SettingsPage(firstRun: true),
            ),
          ],
        ),
        GoRoute(
          path: Routes.evidenceRoot,
          builder: (context, _) =>
              const _NotFoundPage(location: Routes.evidenceRoot),
          routes: [
            GoRoute(
              path: ':evidenceId',
              builder: (context, routeState) => EvidencePage(
                state: state,
                evidenceId: routeState.pathParameters['evidenceId'] ?? '',
              ),
            ),
          ],
        ),
      ],
    );
  }

  static String _clockLabel() {
    final now = DateTime.now();
    final hh = now.hour.toString().padLeft(2, '0');
    final mm = now.minute.toString().padLeft(2, '0');
    return '$hh:$mm';
  }
}

final class _SidebarFooter extends StatelessWidget {
  const _SidebarFooter({
    required this.kernelReady,
    required this.onToggleTheme,
    required this.themeMode,
  });

  final bool kernelReady;
  final VoidCallback onToggleTheme;
  final ThemeMode themeMode;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Row(
      children: [
        Icon(
          kernelReady ? Icons.check_circle_outline : Icons.schedule,
          size: 14,
          color: kernelReady
              ? theme.colorScheme.primary
              : theme.colorScheme.onSurfaceVariant,
        ),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            kernelReady ? '内核就绪' : '内核未就绪',
            style: TextStyle(
              fontSize: 12,
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
        ),
        IconButton(
          tooltip: themeMode == ThemeMode.dark ? '切换到浅色' : '切换到深色',
          onPressed: onToggleTheme,
          icon: Icon(
            themeMode == ThemeMode.dark
                ? Icons.light_mode_outlined
                : Icons.dark_mode_outlined,
            size: 16,
          ),
        ),
      ],
    );
  }
}

/// 404 页（中文文案 + 返回入口）。
final class _NotFoundPage extends StatelessWidget {
  const _NotFoundPage({required this.location});

  final String location;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(Tokens.space6),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const Text(
                  '页面不存在',
                  style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: Tokens.space2),
                Text('无法找到 $location。', textAlign: TextAlign.center),
                const SizedBox(height: Tokens.space1),
                const Text(
                  '可返回概览，或按 Ctrl+K 打开命令面板跳转。',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: Tokens.space4),
                FilledButton(
                  onPressed: () => AppShellNavigator.go(Routes.overview),
                  child: const Text('返回概览'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
