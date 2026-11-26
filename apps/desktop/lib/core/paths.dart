import 'dart:io';

import 'package:path/path.dart' as p;

/// 路径解析：可写根与只读资源根（docs/11 §7.2）。
///
/// 优先级：命令行参数 > 环境变量（仅人工调试）> 平台默认目录。
final class AppPaths {
  const AppPaths({required this.dataHome, required this.resourceHome});

  /// 按启动参数与平台解析。
  ///
  /// `--data-home <path>` / `--resource-home <path>` 覆盖默认值；
  /// 环境变量 `CBR_DATA_HOME` / `CBR_HOME` 仅作人工调试兜底。
  factory AppPaths.resolve(List<String> args, {Map<String, String>? env}) {
    final environment = env ?? Platform.environment;
    final dataHome =
        _argValue(args, '--data-home') ??
        _nonEmpty(environment['CBR_DATA_HOME']) ??
        _platformDataHome(environment);
    final resourceHome =
        _argValue(args, '--resource-home') ??
        _nonEmpty(environment['CBR_HOME']) ??
        _platformResourceHome();
    return AppPaths(
      dataHome: p.normalize(p.absolute(dataHome)),
      resourceHome: p.normalize(p.absolute(resourceHome)),
    );
  }

  /// 可写根：workspaces/ inbox/ traces/ logs/ secrets/ configs/。
  final String dataHome;

  /// 只读资源根：configs/ contracts/ data/knowledge/corpus。
  final String resourceHome;

  /// 投递箱目录（可写根下，绝不在安装目录）。
  String get inboxDir => p.join(dataHome, 'inbox');

  /// 密钥目录。
  String get secretsDir => p.join(dataHome, 'secrets');

  /// 日志目录。
  String get logsDir => p.join(dataHome, 'logs');

  /// 工作区目录。
  String get workspacesDir => p.join(dataHome, 'workspaces');

  /// 用户覆盖配置目录。
  String get userConfigDir => p.join(dataHome, 'configs');

  /// 只读配置目录。
  String get resourceConfigDir => p.join(resourceHome, 'configs');

  /// 确保可写目录存在。
  Future<void> ensureWritableDirs() async {
    for (final dir in [
      inboxDir,
      secretsDir,
      logsDir,
      workspacesDir,
      userConfigDir,
    ]) {
      await Directory(dir).create(recursive: true);
    }
  }

  /// 当前工作区路径。
  String get workspacePath => p.join(workspacesDir, 'default.duckdb');

  static String? _argValue(List<String> args, String flag) {
    for (var i = 0; i < args.length; i++) {
      final arg = args[i];
      if (arg == flag && i + 1 < args.length) {
        return args[i + 1];
      }
      if (arg.startsWith('$flag=')) {
        return arg.substring(flag.length + 1);
      }
    }
    return null;
  }

  static String? _nonEmpty(String? value) =>
      (value == null || value.isEmpty) ? null : value;

  static String _platformDataHome(Map<String, String> env) {
    if (Platform.isWindows) {
      final local = env['LOCALAPPDATA'];
      if (local != null && local.isNotEmpty) {
        return p.join(local, 'CBR-MAW');
      }
    }
    if (Platform.isMacOS) {
      final home = env['HOME'];
      if (home != null && home.isNotEmpty) {
        return p.join(home, 'Library', 'Application Support', 'CBR-MAW');
      }
    }
    final xdg = env['XDG_DATA_HOME'];
    if (xdg != null && xdg.isNotEmpty) {
      return p.join(xdg, 'cbr-maw');
    }
    return p.join(env['HOME'] ?? '.', '.local', 'share', 'cbr-maw');
  }

  static String _platformResourceHome() => Directory.current.path;
}
