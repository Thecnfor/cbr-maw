import 'package:flutter/widgets.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../tokens/colors.dart';

/// 图标白名单（docs/06 §5.1、§9 VC-7）。
///
/// 统一入口，禁止业务代码直接 import lucide 图标常量：catalog 只允许引用
/// 这里的名字，`CbrIcons.byName` 对白名单外名字返回 [fallback] 并可由调用方记 trace。
abstract final class CbrIcons {
  static const IconData fallback = LucideIcons.circleHelp;

  static const IconData riskLow = LucideIcons.shieldCheck;
  static const IconData riskMedium = LucideIcons.shieldAlert;
  static const IconData riskHigh = LucideIcons.triangleAlert;
  static const IconData riskCritical = LucideIcons.shieldAlert;

  static const IconData evidence = LucideIcons.fileText;
  static const IconData claim = LucideIcons.fileWarning;
  static const IconData chart = LucideIcons.chartLine;
  static const IconData table = LucideIcons.table;
  static const IconData timeline = LucideIcons.listTree;
  static const IconData scale = LucideIcons.scale;
  static const IconData search = LucideIcons.search;
  static const IconData command = LucideIcons.command;
  static const IconData themeLight = LucideIcons.sun;
  static const IconData themeDark = LucideIcons.moon;
  static const IconData settings = LucideIcons.settings;
  static const IconData more = LucideIcons.ellipsis;
  static const IconData close = LucideIcons.x;
  static const IconData check = LucideIcons.check;
  static const IconData lock = LucideIcons.lock;
  static const IconData info = LucideIcons.info;
  static const IconData warning = LucideIcons.triangleAlert;
  static const IconData error = LucideIcons.circleAlert;
  static const IconData success = LucideIcons.circleCheck;
  static const IconData loading = LucideIcons.loaderCircle;
  static const IconData retry = LucideIcons.refreshCw;
  static const IconData external = LucideIcons.squareArrowOutUpRight;
  static const IconData clock = LucideIcons.clock;
  static const IconData panelRight = LucideIcons.panelRight;
  static const IconData panelLeft = LucideIcons.panelLeft;
  static const IconData download = LucideIcons.download;
  static const IconData filter = LucideIcons.filter;
  static const IconData globe = LucideIcons.globe;
  static const IconData database = LucideIcons.database;
  static const IconData users = LucideIcons.users;
  static const IconData up = LucideIcons.arrowUp;
  static const IconData down = LucideIcons.arrowDown;
  static const IconData flat = LucideIcons.minus;
  static const IconData chevronRight = LucideIcons.chevronRight;

  static const Map<String, IconData> whitelist = <String, IconData>{
    'shield-check': riskLow,
    'shield-alert': riskMedium,
    'triangle-alert': riskHigh,
    'file-text': evidence,
    'file-warning': claim,
    'chart-line': chart,
    'table': table,
    'list-tree': timeline,
    'scale': scale,
    'search': search,
    'command': command,
    'sun': themeLight,
    'moon': themeDark,
    'settings': settings,
    'ellipsis': more,
    'x': close,
    'check': check,
    'lock': lock,
    'info': info,
    'circle-alert': error,
    'circle-check': success,
    'refresh-cw': retry,
    'clock': clock,
    'panel-right': panelRight,
    'panel-left': panelLeft,
    'download': download,
    'filter': filter,
    'globe': globe,
    'database': database,
    'users': users,
    'arrow-up': up,
    'arrow-down': down,
    'minus': flat,
    'chevron-right': chevronRight,
  };

  /// 只接受 kebab-case 白名单名；未知返回 null 供上层记 trace（VC-7）。
  static IconData? byName(String name) => whitelist[name];

  static IconData forRisk(CbrRiskLevel level) => switch (level) {
    CbrRiskLevel.low => riskLow,
    CbrRiskLevel.medium => riskMedium,
    CbrRiskLevel.high => riskHigh,
    CbrRiskLevel.critical => riskCritical,
  };

  static IconData forRole(CbrRole role) => switch (role) {
    CbrRole.financing => database,
    CbrRole.investor => chart,
    CbrRole.regulator => scale,
    CbrRole.crossValidator => riskLow,
  };
}
