import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'errors.dart';

/// 运行配置：`<resource>/configs/app.json` 为基线，`<data-home>/configs/app.json` 覆盖。
///
/// 业务配置只走文件，不走环境变量（contracts/README.md §1）。
final class AppConfig {
  const AppConfig({
    required this.appName,
    required this.timezone,
    required this.llmBaseUrl,
    required this.llmModel,
    required this.llmTimeoutSeconds,
    required this.staleThresholdDays,
    required this.monthlyStaleThresholdDays,
    required this.syntheticDefault,
  });

  /// 缺省配置（无文件时生效；所有值都是口径而非数据）。
  static const AppConfig defaults = AppConfig(
    appName: 'CBR-MAW',
    timezone: 'Asia/Shanghai',
    llmBaseUrl: 'https://api.deepseek.com',
    llmModel: 'deepseek-chat',
    llmTimeoutSeconds: 60,
    staleThresholdDays: 3,
    monthlyStaleThresholdDays: 40,
    syntheticDefault: true,
  );

  /// 应用名。
  final String appName;

  /// 时区。
  final String timezone;

  /// 模型接口地址。
  final String llmBaseUrl;

  /// 主模型。
  final String llmModel;

  /// 模型调用超时（秒）。
  final int llmTimeoutSeconds;

  /// 日频陈旧阈值（天）。
  final int staleThresholdDays;

  /// 月频陈旧阈值（天）。
  final int monthlyStaleThresholdDays;

  /// 默认数据集是否为仿真（仅作标注来源，不参与取数）。
  final bool syntheticDefault;

  /// 读取基线 + 用户覆盖。
  ///
  /// 文件缺失不算错误（用缺省值）；文件存在但非法则显式失败并指出字段。
  static Future<AppConfig> load({
    required String resourceConfigDir,
    required String userConfigDir,
  }) async {
    var merged = <String, Object?>{};
    for (final dir in [resourceConfigDir, userConfigDir]) {
      final file = File(p.join(dir, 'app.json'));
      if (!await file.exists()) {
        continue;
      }
      final Object? decoded;
      try {
        decoded = jsonDecode(await file.readAsString());
      } on FormatException catch (e) {
        throw AppError.config(
          why: '${p.join(dir, 'app.json')} 不是合法 JSON（${e.message}）',
          detail: {'file': file.path},
        );
      }
      if (decoded is! Map<String, Object?>) {
        throw AppError.config(why: '${file.path} 顶层必须是 JSON 对象');
      }
      merged = _deepMerge(merged, decoded);
    }
    return _fromJson(merged);
  }

  static AppConfig _fromJson(Map<String, Object?> json) {
    final llm = _map(json['llm']);
    final ingest = _map(json['ingest']);
    final data = _map(json['data']);
    return AppConfig(
      appName: _str(json['app_name']) ?? defaults.appName,
      timezone: _str(json['timezone']) ?? defaults.timezone,
      llmBaseUrl: _str(llm['base_url']) ?? defaults.llmBaseUrl,
      llmModel: _str(llm['model']) ?? defaults.llmModel,
      llmTimeoutSeconds:
          _int(llm['timeout_seconds']) ?? defaults.llmTimeoutSeconds,
      staleThresholdDays:
          _int(ingest['stale_threshold_days']) ?? defaults.staleThresholdDays,
      monthlyStaleThresholdDays:
          _int(ingest['monthly_stale_threshold_days']) ??
          defaults.monthlyStaleThresholdDays,
      syntheticDefault: _bool(data['synthetic']) ?? defaults.syntheticDefault,
    );
  }

  static Map<String, Object?> _map(Object? value) =>
      value is Map<String, Object?> ? value : const {};

  static String? _str(Object? value) => value is String ? value : null;

  static int? _int(Object? value) => value is int ? value : null;

  static bool? _bool(Object? value) => value is bool ? value : null;

  static Map<String, Object?> _deepMerge(
    Map<String, Object?> base,
    Map<String, Object?> overlay,
  ) {
    final out = <String, Object?>{...base};
    for (final entry in overlay.entries) {
      final existing = out[entry.key];
      final incoming = entry.value;
      if (existing is Map<String, Object?> &&
          incoming is Map<String, Object?>) {
        out[entry.key] = _deepMerge(existing, incoming);
      } else {
        out[entry.key] = incoming;
      }
    }
    return out;
  }
}
