/// LLM 通道（docs/03 §2.5 / §9.1）：DeepSeek 生成 + JEV 裁判。
///
/// 零 Mock 严格模式：模型不可用 → 显式失败并引导到设置页，**绝不用规则模板或
/// 占位数值冒充模型结论**。所有调用记 token 与成本。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:dio/dio.dart';

/// 密钥来源（由 core 的密钥管理注入；本层不读 .env 明文）。
abstract interface class SecretProvider {
  /// 取密钥；未配置返回 null。
  Future<String?> read(String key);
}

/// 内存密钥（仅测试与设置页注入用）。
final class InMemorySecretProvider implements SecretProvider {
  /// 创建内存密钥源。
  InMemorySecretProvider([Map<String, String>? values])
    : _values = {...?values};

  final Map<String, String> _values;

  /// 写入。
  void write(String key, String? value) {
    if (value == null) {
      _values.remove(key);
    } else {
      _values[key] = value;
    }
  }

  @override
  Future<String?> read(String key) async => _values[key];
}

/// LLM 失败码。
enum LlmFailureCode {
  missingKey('missingKey'),
  unauthorized('unauthorized'),
  timeout('timeout'),
  rateLimited('rateLimited'),
  invalidOutput('invalidOutput'),
  unavailable('unavailable');

  const LlmFailureCode(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// LLM 显式失败（零 Mock：调用方必须上抛，不得降级为模板）。
final class LlmFailure implements Exception {
  /// 创建失败。
  const LlmFailure({
    required this.code,
    required this.message,
    this.retryable = false,
    this.attempt = 1,
  });

  /// 失败码。
  final LlmFailureCode code;

  /// 中文说明（引导到设置页）。
  final String message;

  /// 是否可重试。
  final bool retryable;

  /// 尝试次数。
  final int attempt;

  @override
  String toString() => 'LlmFailure(${code.wire}): $message';
}

/// LLM 调用用量。
final class LlmUsage {
  /// 创建用量。
  const LlmUsage({this.prompt = 0, this.completion = 0});

  /// prompt token。
  final int prompt;

  /// completion token。
  final int completion;

  /// 合计。
  int get total => prompt + completion;
}

/// 一次生成的返回。
final class LlmResponse {
  /// 创建返回。
  const LlmResponse({
    required this.json,
    required this.usage,
    required this.latencyMs,
    required this.attempts,
  });

  /// 解析后的 JSON 对象。
  final Map<String, Object?> json;

  /// 用量。
  final LlmUsage usage;

  /// 延迟。
  final int latencyMs;

  /// 实际尝试次数。
  final int attempts;
}

/// 生成器接口（角色分析与合成共用）。
abstract interface class TextGenerator {
  /// 按 system/user 提示生成一个 JSON 对象。
  Future<LlmResponse> generateJson({
    required String system,
    required String user,
    required String purpose,
  });
}

/// DeepSeek（OpenAI 兼容）生成器。
final class DeepSeekGenerator implements TextGenerator {
  /// 创建生成器。
  DeepSeekGenerator({
    required SecretProvider secrets,
    Dio? dio,
    this.baseUrl = 'https://api.deepseek.com',
    this.model = 'deepseek-chat',
    this.temperature = 0.0,
    this.maxTokens = 2000,
    this.timeout = const Duration(seconds: 60),
    this.maxRetries = 2,
    this.secretKey = 'DEEPSEEK_API_KEY',
  }) : _secrets = secrets, // ignore: prefer_initializing_formals
       _dio =
           dio ??
           Dio(
             BaseOptions(
               connectTimeout: const Duration(seconds: 15),
               receiveTimeout: const Duration(seconds: 60),
             ),
           );

  final SecretProvider _secrets;
  final Dio _dio;

  /// 端点。
  final String baseUrl;

  /// 模型名。
  final String model;

  /// 温度。
  final double temperature;

  /// 最大生成 token。
  final int maxTokens;

  /// 单次超时。
  final Duration timeout;

  /// 重试次数。
  final int maxRetries;

  /// 密钥名。
  final String secretKey;

  @override
  Future<LlmResponse> generateJson({
    required String system,
    required String user,
    required String purpose,
  }) async {
    final key = await _secrets.read(secretKey);
    if (key == null || key.isEmpty) {
      throw const LlmFailure(
        code: LlmFailureCode.missingKey,
        message: '未配置 DeepSeek API 密钥。请到「设置 → 连接」填写密钥后重试。',
      );
    }

    final started = DateTime.now();
    LlmFailure? last;
    for (var attempt = 1; attempt <= maxRetries + 1; attempt++) {
      try {
        final response = await _dio
            .post<Map<String, Object?>>(
              '$baseUrl/chat/completions',
              options: Options(
                headers: {
                  'Authorization': 'Bearer $key',
                  'Content-Type': 'application/json',
                },
              ),
              data: {
                'model': model,
                'temperature': temperature,
                'max_tokens': maxTokens,
                'response_format': {'type': 'json_object'},
                'messages': [
                  {'role': 'system', 'content': system},
                  {'role': 'user', 'content': user},
                ],
              },
            )
            .timeout(timeout);
        return _parse(
          response.data,
          purpose: purpose,
          started: started,
          attempt: attempt,
        );
      } on LlmFailure catch (failure) {
        last = failure;
        if (!failure.retryable || attempt > maxRetries) {
          throw LlmFailure(
            code: failure.code,
            message: failure.message,
            retryable: false,
            attempt: attempt,
          );
        }
        await _backoff(attempt);
      } on TimeoutException {
        last = const LlmFailure(
          code: LlmFailureCode.timeout,
          message: '模型响应超时。请检查网络或稍后重试。',
          retryable: true,
        );
        if (attempt > maxRetries) {
          throw LlmFailure(
            code: last.code,
            message: last.message,
            attempt: attempt,
          );
        }
        await _backoff(attempt);
      } on DioException catch (error) {
        final status = error.response?.statusCode;
        final code = switch (status) {
          401 || 403 => LlmFailureCode.unauthorized,
          429 => LlmFailureCode.rateLimited,
          _ => LlmFailureCode.unavailable,
        };
        final message = switch (code) {
          LlmFailureCode.unauthorized => 'DeepSeek 密钥无效或已过期。请到「设置 → 连接」重新填写。',
          LlmFailureCode.rateLimited => '模型服务限流，请稍后重试。',
          _ => '模型服务不可达（${error.message ?? '网络错误'}）。请检查网络或在设置页测试连接。',
        };
        last = LlmFailure(
          code: code,
          message: message,
          retryable: code != LlmFailureCode.unauthorized,
        );
        if (!last.retryable || attempt > maxRetries) {
          throw LlmFailure(
            code: last.code,
            message: last.message,
            attempt: attempt,
          );
        }
        await _backoff(attempt);
      }
    }
    throw LlmFailure(
      code: last?.code ?? LlmFailureCode.unavailable,
      message: last?.message ?? '模型调用失败。',
      attempt: maxRetries + 1,
    );
  }

  LlmResponse _parse(
    Map<String, Object?>? data, {
    required String purpose,
    required DateTime started,
    required int attempt,
  }) {
    final choices = data?['choices'] as List<Object?>? ?? const [];
    if (choices.isEmpty) {
      throw const LlmFailure(
        code: LlmFailureCode.invalidOutput,
        message: '模型返回空结果。',
      );
    }
    final message =
        (choices.first as Map<String, Object?>)['message']
            as Map<String, Object?>?;
    final content = message?['content'] as String? ?? '';
    final Object? decoded;
    try {
      decoded = jsonDecode(_stripFence(content));
    } on FormatException {
      throw const LlmFailure(
        code: LlmFailureCode.invalidOutput,
        message: '模型输出不是合法 JSON，已按失败处理（不降级为模板）。',
      );
    }
    if (decoded is! Map<String, Object?>) {
      throw const LlmFailure(
        code: LlmFailureCode.invalidOutput,
        message: '模型输出不是 JSON 对象，已按失败处理（不降级为模板）。',
      );
    }
    final usage = data?['usage'] as Map<String, Object?>? ?? const {};
    return LlmResponse(
      json: decoded,
      usage: LlmUsage(
        prompt: (usage['prompt_tokens'] as num?)?.toInt() ?? 0,
        completion: (usage['completion_tokens'] as num?)?.toInt() ?? 0,
      ),
      latencyMs: DateTime.now().difference(started).inMilliseconds,
      attempts: attempt,
    );
  }

  String _stripFence(String content) {
    final trimmed = content.trim();
    if (!trimmed.startsWith('```')) {
      return trimmed;
    }
    final start = trimmed.indexOf('{');
    final end = trimmed.lastIndexOf('}');
    return start >= 0 && end > start
        ? trimmed.substring(start, end + 1)
        : trimmed;
  }

  Future<void> _backoff(int attempt) => Future<void>.delayed(
    Duration(milliseconds: 500 * pow(2, attempt - 1).toInt()),
  );
}

/// 裁判选项问题（JEV choice 类型）。
final class ChoiceQuestion {
  /// 创建问题。
  const ChoiceQuestion({required this.instructions, required this.criteria});

  /// 指令。
  final String instructions;

  /// 选项 → 说明。
  final Map<String, String?> criteria;

  /// 序列化。
  Map<String, Object?> toJson() => {
    'type': 'choice',
    'instructions': instructions,
    'criteria': criteria,
  };
}

/// 裁判回答。
final class JudgeAnswer {
  /// 创建回答。
  const JudgeAnswer({
    required this.choice,
    this.confidence,
    this.probabilities = const {},
  });

  /// 选项。
  final String choice;

  /// 置信度。
  final double? confidence;

  /// 各选项概率。
  final Map<String, double> probabilities;
}

/// 裁判接口（JEV / TypeSafe System One）。
abstract interface class Judge {
  /// 是否可用（只查配置，不发网络请求）。
  Future<bool> get available;

  /// 提一个问题。
  Future<JudgeAnswer> ask({
    required Object state,
    required ChoiceQuestion question,
  });
}

/// JEV 裁判（`jev-1.14.0`），**不是生成者**。
final class JevJudge implements Judge {
  /// 创建裁判。
  JevJudge({
    required SecretProvider secrets,
    Dio? dio,
    this.baseUrl = 'https://api.typesafe.ai',
    this.model = 'jev-1.14.0',
    this.timeout = const Duration(seconds: 30),
    this.maxRetries = 2,
    this.secretKey = 'TYPESAFE_API_KEY',
  }) : _secrets = secrets, // ignore: prefer_initializing_formals
       _dio =
           dio ??
           Dio(
             BaseOptions(
               connectTimeout: const Duration(seconds: 10),
               receiveTimeout: const Duration(seconds: 30),
             ),
           );

  final SecretProvider _secrets;
  final Dio _dio;

  /// 端点。
  final String baseUrl;

  /// 模型名。
  final String model;

  /// 超时。
  final Duration timeout;

  /// 重试。
  final int maxRetries;

  /// 密钥名。
  final String secretKey;

  @override
  Future<bool> get available async {
    final key = await _secrets.read(secretKey);
    return key != null && key.isNotEmpty;
  }

  @override
  Future<JudgeAnswer> ask({
    required Object state,
    required ChoiceQuestion question,
  }) async {
    final key = await _secrets.read(secretKey);
    if (key == null || key.isEmpty) {
      throw const LlmFailure(
        code: LlmFailureCode.missingKey,
        message: '未配置 TypeSafe 密钥，判断层不可用。请到「设置 → 连接」填写。',
      );
    }
    LlmFailure? last;
    for (var attempt = 1; attempt <= maxRetries + 1; attempt++) {
      try {
        final response = await _dio
            .post<Map<String, Object?>>(
              '$baseUrl/v1/systemone',
              options: Options(
                headers: {
                  'Authorization': 'Bearer $key',
                  'Content-Type': 'application/json',
                },
              ),
              data: {
                'model': model,
                'state': state,
                'questions': {'verdict': question.toJson()},
              },
            )
            .timeout(timeout);
        return _parse(response.data);
      } on LlmFailure catch (failure) {
        last = failure;
        if (!failure.retryable || attempt > maxRetries) {
          rethrow;
        }
      } on DioException catch (error) {
        last = LlmFailure(
          code: switch (error.response?.statusCode) {
            401 || 403 => LlmFailureCode.unauthorized,
            429 => LlmFailureCode.rateLimited,
            _ => LlmFailureCode.unavailable,
          },
          message: '判断层不可达：${error.message ?? '网络错误'}。',
          retryable: error.response?.statusCode != 401,
        );
        if (!last.retryable || attempt > maxRetries) {
          throw last;
        }
      }
      await Future<void>.delayed(
        Duration(milliseconds: 500 * pow(2, attempt - 1).toInt()),
      );
    }
    throw last ??
        const LlmFailure(code: LlmFailureCode.unavailable, message: '判断层不可用。');
  }

  JudgeAnswer _parse(Map<String, Object?>? data) {
    final answers = data?['answers'] as Map<String, Object?>? ?? const {};
    final verdict = answers['verdict'] as Map<String, Object?>?;
    final choice = verdict?['choice'] as String?;
    if (choice == null) {
      throw const LlmFailure(
        code: LlmFailureCode.invalidOutput,
        message: '判断层返回缺少 verdict.choice。',
      );
    }
    final rawProbabilities =
        verdict?['probabilities'] as Map<String, Object?>? ?? const {};
    return JudgeAnswer(
      choice: choice,
      confidence: (verdict?['confidence'] as num?)?.toDouble(),
      probabilities: {
        for (final entry in rawProbabilities.entries)
          entry.key: (entry.value as num).toDouble(),
      },
    );
  }
}

/// 规则门卫回退：JEV 不可用时使用，**不产出置信度**，并在 note 明说未使用模型判断。
final class RuleGate {
  /// 判断意图（探索 / 新决策 / 越界）。
  ({String choice, String note}) classify(String message) {
    final text = message.toLowerCase();
    final outOfScope = ['写代码', '入侵', '爆破', '绕过登录', '盗取'].any(text.contains);
    if (outOfScope) {
      return (choice: 'outOfScope', note: '规则门卫：命中越界关键词（未使用模型判断）。');
    }
    final explore = ['查看', '看看', '解释', '什么是', '背景'].any(text.contains);
    return (
      choice: explore ? 'explore' : 'newDecision',
      note: '规则门卫：按关键词分类，未使用模型判断（无置信度）。',
    );
  }
}
