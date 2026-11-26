/// 路由表（go_router）。
///
/// 路径一律英文 kebab-case；顶层四条分支的顺序即底部导航顺序。
/// 侧栏承载其余页面（分组进入，非底部导航项）。
library;

import '../app/ui.dart';

/// 工作台路由常量（唯一真源，测试与命令面板共用）。
abstract final class Routes {
  /// 概览。
  static const overview = '/overview';

  /// 对话式研判。
  static const investigation = '/investigation';

  /// 风险卡。
  static const riskCards = '/risk-cards';

  /// 时间线。
  static const timeline = '/timeline';

  /// 来源台账。
  static const sources = '/sources';

  /// 数据卡。
  static const dataCards = '/data-cards';

  /// 情景。
  static const scenarios = '/scenarios';

  /// 时空（v2 预留占位）。
  static const spatial = '/spatial';

  /// 设置。
  static const settings = '/settings';

  /// 首次运行向导（设置内嵌）。
  static const settingsFirstRun = '/settings/first-run';

  /// 首次上手（填密钥 → 选数据模式，docs/22 屏 1–2）。
  static const welcome = '/welcome';

  /// 诊断。
  static const diagnostics = '/diagnostics';

  /// 新手引导。
  static const onboarding = '/onboarding';

  /// 投递箱。
  static const inbox = '/inbox';

  /// 风险卡详情。
  static String riskCard(String claimId) => '/risk-cards/$claimId';

  /// 证据详情。
  static String evidence(String evidenceId) => '/evidence/$evidenceId';

  /// 时间线详情。
  static String timelineRun(String runId) => '/timeline/$runId';

  /// 证据详情根（侧栏不进入，从结论跳转）。
  static const evidenceRoot = '/evidence';

  /// 分支顺序（= 底部导航 4 项）。
  static const List<String> branches = [
    overview,
    investigation,
    riskCards,
    timeline,
  ];
}

/// 导航项定义（侧栏 / 底部导航 / 命令面板共用同一份）。
final class NavItem {
  const NavItem({
    required this.path,
    required this.label,
    required this.icon,
    required this.group,
    this.branch = false,
  });

  /// 目标路径。
  final String path;

  /// 中文名。
  final String label;

  /// 图标。
  final IconData icon;

  /// 分组名（侧栏分组标题）。
  final String group;

  /// 是否为底部导航项（顶层四分支之一）。
  final bool branch;
}

/// 侧栏与命令面板的完整导航清单（顺序固定）。
const List<NavItem> navItems = [
  NavItem(
    path: Routes.overview,
    label: '概览',
    icon: Icons.dashboard_outlined,
    group: '工作台',
    branch: true,
  ),
  NavItem(
    path: Routes.investigation,
    label: '对话式研判',
    icon: Icons.forum_outlined,
    group: '工作台',
    branch: true,
  ),
  NavItem(
    path: Routes.riskCards,
    label: '风险卡',
    icon: Icons.shield_outlined,
    group: '工作台',
    branch: true,
  ),
  NavItem(
    path: Routes.timeline,
    label: '时间线',
    icon: Icons.timeline_outlined,
    group: '工作台',
    branch: true,
  ),
  NavItem(
    path: Routes.sources,
    label: '来源台账',
    icon: Icons.hub_outlined,
    group: '数据',
  ),
  NavItem(
    path: Routes.dataCards,
    label: '数据卡',
    icon: Icons.dataset_outlined,
    group: '数据',
  ),
  NavItem(
    path: Routes.inbox,
    label: '投递箱',
    icon: Icons.move_to_inbox_outlined,
    group: '数据',
  ),
  NavItem(
    path: Routes.scenarios,
    label: '情景',
    icon: Icons.alt_route_outlined,
    group: '分析',
  ),
  NavItem(
    path: Routes.spatial,
    label: '时空',
    icon: Icons.public_outlined,
    group: '分析',
  ),
  NavItem(
    path: Routes.onboarding,
    label: '新手引导',
    icon: Icons.school_outlined,
    group: '系统',
  ),
  NavItem(
    path: Routes.diagnostics,
    label: '诊断',
    icon: Icons.monitor_heart_outlined,
    group: '系统',
  ),
  NavItem(
    path: Routes.settings,
    label: '设置',
    icon: Icons.settings_outlined,
    group: '系统',
  ),
];

/// 侧栏分组（按首次出现顺序）。
Map<String, List<NavItem>> groupedNavItems() {
  final groups = <String, List<NavItem>>{};
  for (final item in navItems) {
    groups.putIfAbsent(item.group, () => []).add(item);
  }
  return groups;
}

/// 底部导航 4 项（顺序 = 分支索引）。
List<NavItem> bottomNavItems() =>
    navItems.where((item) => item.branch).toList(growable: false);

/// 当前路径命中的导航项（用于高亮）。
NavItem? navItemFor(String location) {
  for (final item in navItems) {
    if (location == item.path || location.startsWith('${item.path}/')) {
      return item;
    }
  }
  return null;
}

/// 分支索引（用于 [StatefulNavigationShell.goBranch]）。
int branchIndexFor(String location) {
  final item = navItemFor(location);
  if (item == null || !item.branch) {
    return 0;
  }
  return Routes.branches.indexOf(item.path);
}

/// 深链规范化：`cbr-maw://risk-cards/ev_123` 与 `https://cbr.local/risk-cards/ev_123`
/// 都落到 `/risk-cards/ev_123`。
///
/// 非法或空路径返回 null（调用方保持原路由）。
String? normalizeDeepLink(String uri) {
  final parsed = Uri.tryParse(uri);
  if (parsed == null) {
    return null;
  }
  // 自定义 scheme：host 承载第一段路径。
  if (parsed.scheme == 'cbr-maw') {
    final segments = [
      if (parsed.host.isNotEmpty) parsed.host,
      ...parsed.pathSegments.where((s) => s.isNotEmpty),
    ];
    if (segments.isEmpty) {
      return null;
    }
    return '/${segments.join('/')}';
  }
  // http(s)：路径即路由。
  if (parsed.scheme == 'http' || parsed.scheme == 'https') {
    final segments = parsed.pathSegments.where((s) => s.isNotEmpty).toList();
    if (segments.isEmpty) {
      return null;
    }
    return '/${segments.join('/')}';
  }
  return null;
}
