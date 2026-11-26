import 'dart:io';

import 'package:dio/dio.dart';

/// 密钥校验结果分类（docs/22 屏 1：401 / 网络 / 代理 三态分列）。
enum KeyProbeOutcome {
  /// 校验通过。
  ok('ok'),

  /// 密钥无效或过期。
  unauthorized('unauthorized'),

  /// 网络不可达。
  network('network'),

  /// 代理配置问题（连接被代理拒绝 / 代理本身不可达）。
  proxy('proxy');

  const KeyProbeOutcome(this.wire);

  /// 字面量。
  final String wire;
}

/// 一条校验结论：三段式（错在哪 / 怎么改 / 影响什么）。
final class KeyProbeResult {
  const KeyProbeResult(this.outcome, this.what, this.how, this.impact);

  /// 通过。
  static const ok = KeyProbeResult(
    KeyProbeOutcome.ok,
    '密钥有效',
    '可以继续',
    '模型调用可用',
  );

  /// 分类。
  final KeyProbeOutcome outcome;

  /// 错在哪。
  final String what;

  /// 怎么改。
  final String how;

  /// 影响什么。
  final String impact;
}

/// 密钥校验器（注入以便测试，不依赖真实网络）。
abstract interface class KeyProber {
  /// 校验一把密钥；[key] 已在调用前 trim。
  Future<KeyProbeResult> verify(String key);
}

/// DeepSeek 校验：`GET /user/balance` 确认账号，再 `POST /chat/completions`
/// （`max_tokens=1`）确认模型可用（docs/21 §1 旧版口径）。
final class DeepSeekKeyProber implements KeyProber {
  /// 创建校验器。
  DeepSeekKeyProber({
    required this.baseUrl,
    required this.model,
    this.timeout = const Duration(seconds: 15),
  });

  /// 接口地址（来自配置，已 trim）。
  final String baseUrl;

  /// 模型名。
  final String model;

  /// 超时。
  final Duration timeout;

  @override
  Future<KeyProbeResult> verify(String key) async {
    final trimmed = key.trim();
    if (trimmed.isEmpty) {
      return const KeyProbeResult(
        KeyProbeOutcome.unauthorized,
        '未填写密钥',
        '粘贴主模型密钥后重试',
        '无法调用模型',
      );
    }
    final base = baseUrl.trim();
    final uri = Uri.tryParse(base);
    if (uri == null || !uri.hasScheme || uri.host.isEmpty) {
      return KeyProbeResult(
        KeyProbeOutcome.network,
        '模型接口地址非法：$base',
        '在设置 → 连接中填写完整地址（含 https://）',
        '无法调用模型',
      );
    }
    final dio = Dio(
      BaseOptions(
        connectTimeout: timeout,
        receiveTimeout: timeout,
        headers: {'Authorization': 'Bearer $trimmed'},
      ),
    );
    try {
      await dio.get<Object?>('$base/user/balance');
      await dio.post<Object?>(
        '$base/chat/completions',
        data: {
          'model': model,
          'messages': [
            {'role': 'user', 'content': 'ping'},
          ],
          'max_tokens': 1,
          'temperature': 0,
        },
      );
      return KeyProbeResult.ok;
    } on DioException catch (error) {
      final status = error.response?.statusCode;
      if (status == 401 || status == 403) {
        return const KeyProbeResult(
          KeyProbeOutcome.unauthorized,
          '密钥无效或已过期',
          '确认账号状态与余额，或换一把 key',
          '无法调用模型；其余功能仍可用（可浏览本地数据与来源台账）',
        );
      }
      if (status == 407 || _looksLikeProxy(error)) {
        return const KeyProbeResult(
          KeyProbeOutcome.proxy,
          '代理拒绝或不可达',
          '检查设置 → 网络中的代理地址（本机常用 http://127.0.0.1:7897）',
          '仅影响模型调用；本地数据仍可浏览',
        );
      }
      return KeyProbeResult(
        KeyProbeOutcome.network,
        '无法连接模型服务（${error.type.name}）',
        '检查网络或代理设置（设置 → 网络）',
        '仅影响模型调用',
      );
    } finally {
      dio.close();
    }
  }

  /// 代理相关线索：代理环境变量存在且连接失败，或错误消息提到 proxy。
  static bool _looksLikeProxy(DioException error) {
    final message = '${error.message ?? ''} ${error.error ?? ''}'.toLowerCase();
    if (message.contains('proxy') || message.contains('tunnel')) {
      return true;
    }
    const proxyVars = ['HTTPS_PROXY', 'https_proxy', 'ALL_PROXY', 'all_proxy'];
    return proxyVars.any(
      (name) => (Platform.environment[name] ?? '').isNotEmpty,
    );
  }
}
