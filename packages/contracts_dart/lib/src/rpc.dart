/// JSON-RPC 2.0 契约类型层（信封、错误码、方法参数与结果、工具注册表）。
///
/// `methods.dart` 与 `tools.dart` 是本库�� part（生成物），
/// 因此 `sealed` 基类可在同库内被扩展。
library;

import 'contract_format_exception.dart';
import 'json_reader.dart';

part 'methods.dart';
part 'tools.dart';

/// JSON-RPC 2.0 错误码（contracts/README.md §2）。
enum RpcErrorKind {
  /// 行不是合法 JSON。
  parse(-32700, 'E_PARSE'),

  /// 缺 method/id 等。
  invalidRequest(-32600, 'E_INVALID_REQUEST'),

  /// 未知方法。
  methodNotFound(-32601, 'E_METHOD_NOT_FOUND'),

  /// 参数不合法（不重试）。
  invalidParams(-32602, 'E_INVALID_PARAMS'),

  /// 内部异常（带 stack 摘要）。
  internal(-32603, 'E_INTERNAL'),

  /// 该平台不支持（如 Android 无 sidecar）。
  platformUnsupported(-32001, 'E_PLATFORM_UNSUPPORTED'),

  /// 来源需授权/需登录。
  notAuthorized(-32002, 'E_NOT_AUTHORIZED'),

  /// 不可达/反爬受限/已过期。
  sourceUnavailable(-32003, 'E_SOURCE_UNAVAILABLE'),

  /// 必需数据缺失（缺失 ≠ 零值）。
  dataMissing(-32004, 'E_DATA_MISSING'),

  /// 契约或 schema 版本不匹配。
  contractMismatch(-32005, 'E_CONTRACT_MISMATCH'),

  /// 被限流。
  rateLimited(-32006, 'E_RATE_LIMITED'),

  /// 超时。
  timeout(-32007, 'E_TIMEOUT'),

  /// 未握手。
  notInitialized(-32008, 'E_NOT_INITIALIZED'),

  /// 角色越权（工具未执行）。
  permissionDenied(-32009, 'E_PERMISSION_DENIED');

  const RpcErrorKind(this.code, this.kind);

  /// JSON-RPC 数值错误码。
  final int code;

  /// 稳定的机器可读标识（`E_XXX`）。
  final String kind;

  /// 按数值错误码查找。
  static RpcErrorKind fromCode(int code) {
    for (final value in values) {
      if (value.code == code) {
        return value;
      }
    }
    throw ContractFormatException('未知错误码：$code');
  }

  /// 按 kind 标识查找。
  static RpcErrorKind fromKind(String kind) {
    for (final value in values) {
      if (value.kind == kind) {
        return value;
      }
    }
    throw ContractFormatException('未知错误标识：$kind');
  }
}

/// JSON-RPC 2.0 错误对象。
final class RpcError {
  const RpcError({
    required this.code,
    required this.message,
    required this.kind,
    required this.retryable,
    required this.detail,
  });

  /// 从 `error` 对象解析（解析即校验）。
  factory RpcError.parse(Object? json) {
    final r = JsonReader(json, 'error');
    final code = r.integer('code');
    final data = r.obj('data');
    final dataReader = JsonReader(data, 'error.data');
    final kind = dataReader.str('kind');
    return RpcError(
      code: code,
      message: r.str('message'),
      kind: RpcErrorKind.fromKind(kind),
      retryable: dataReader.boolean('retryable'),
      detail: dataReader.objOpt('detail') ?? const {},
    );
  }

  /// JSON-RPC 数值错误码。
  final int code;

  /// 人类可读描述。
  final String message;

  /// 机器可读错误标识。
  final RpcErrorKind kind;

  /// 是否可重试。
  final bool retryable;

  /// 明细（至少含 `reason`）。
  final Map<String, Object?> detail;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson() => {
    'code': code,
    'message': message,
    'data': {'kind': kind.kind, 'retryable': retryable, 'detail': detail},
  };
}

/// JSON-RPC 2.0 消息基类（sealed：只允许 request / success / error 三种）。
sealed class RpcMessage {
  const RpcMessage();

  /// 关联的请求 ID。
  String get id;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson();
}

/// JSON-RPC 2.0 请求信封。
final class RpcRequest extends RpcMessage {
  const RpcRequest({
    required this.id,
    required this.method,
    required this.params,
  });

  /// 从 JSON 对象解析（解析即校验）。
  factory RpcRequest.parse(Object? json) {
    final r = JsonReader(json, 'request');
    return RpcRequest(
      id: r.str('id'),
      method: r.str('method'),
      params: r.obj('params'),
    );
  }

  @override
  final String id;

  /// 目标方法名（如 `tools.invoke`）。
  final String method;

  /// 方法参数。
  final Map<String, Object?> params;

  @override
  Map<String, Object?> toJson() => {
    'jsonrpc': '2.0',
    'id': id,
    'method': method,
    'params': params,
  };
}

/// JSON-RPC 2.0 响应信封基类（sealed：成功或失败）。
sealed class RpcResponse extends RpcMessage {
  const RpcResponse(this.id);

  /// 从 JSON 对象解析：按 `error` 是否存在分流。
  factory RpcResponse.parse(Object? json) {
    final r = JsonReader(json, 'response');
    final id = r.str('id');
    if (r.has('error')) {
      return RpcErrorResponse(id, RpcError.parse(r.obj('error')));
    }
    final result = r.objOpt('result');
    return RpcSuccessResponse(id, result);
  }

  @override
  final String id;
}

/// 成功响应。
final class RpcSuccessResponse extends RpcResponse {
  const RpcSuccessResponse(super.id, this.result);

  /// 原始 `result` 载荷；按方法解析请用对应的 `*Result.parse`。
  final Object? result;

  @override
  Map<String, Object?> toJson() => {
    'jsonrpc': '2.0',
    'id': id,
    'result': result,
  };
}

/// 失败响应。
final class RpcErrorResponse extends RpcResponse {
  const RpcErrorResponse(super.id, this.error);

  /// 错误对象。
  final RpcError error;

  @override
  Map<String, Object?> toJson() => {
    'jsonrpc': '2.0',
    'id': id,
    'error': error.toJson(),
  };
}

/// 方法参数的公共基类：带方法名与 JSON 序列化。
sealed class RpcParams {
  const RpcParams();

  /// 目标方法名。
  String get method;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson();
}

/// 方法结果的公共基类。
sealed class RpcResult {
  const RpcResult();

  /// 来源方法名。
  String get method;

  /// 回写为 JSON 对象。
  Map<String, Object?> toJson();
}

/// 一次调用的结果（成功或失败）。
///
/// 进程内实现与 sidecar 实现共用同一套语义：失败一律走 [Failure]，
/// 不抛异常（除非协议本身被破坏）。
sealed class Result<T> {
  const Result();

  /// 是否成功。
  bool get isSuccess => this is Success<T>;

  /// 成功时的取值；失败时抛 [StateError]。
  T get valueOrThrow => switch (this) {
    Success<T>(:final value) => value,
    Failure<T>(:final error) => throw StateError('调用失败：${error.kind.kind}'),
  };
}

/// 成功结果。
final class Success<T> extends Result<T> {
  const Success(this.value);

  /// 取值。
  final T value;
}

/// 失败结果。
final class Failure<T> extends Result<T> {
  const Failure(this.error);

  /// 错误对象。
  final RpcError error;
}
