import 'dart:convert';
import 'dart:developer' as developer;

/// 日志：用户可感知的中文提示与开发日志分离。
///
/// 开发日志写 stderr（JSONL），stdout 留给协议/正常输出。
final class AppLog {
  AppLog({this.debugEnabled = true});

  /// 是否输出开发日志。
  final bool debugEnabled;

  /// 开发日志（结构化，写 stderr）。
  void dev(String message, {Map<String, Object?> fields = const {}}) {
    if (!debugEnabled) {
      return;
    }
    final line = jsonEncode({
      'ts': DateTime.now().toUtc().toIso8601String(),
      'level': 'debug',
      'sidecar': 'app',
      'msg': message,
      ...fields,
    });
    developer.log(line, name: 'cbr');
  }

  /// 开发错误日志。
  void error(String message, {Object? error, StackTrace? stack}) {
    if (!debugEnabled) {
      return;
    }
    developer.log(
      jsonEncode({
        'ts': DateTime.now().toUtc().toIso8601String(),
        'level': 'error',
        'sidecar': 'app',
        'msg': message,
        'error': error?.toString(),
      }),
      name: 'cbr',
      error: error,
      stackTrace: stack,
    );
  }
}
