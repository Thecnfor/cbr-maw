import 'rpc.dart';

/// sidecar 客户端抽象：进程内实现与 stdio sidecar 实现共用同一接口。
///
/// 约定：
/// - [send] 每次调用返回一条结果流（**单条**）；失败走 [Failure]，不抛异常；
/// - 传输与握手细节由实现方负责，契约层只关心方法名 + 参数 + 结果；
/// - 参数用具体方法的 `*Params`（自带 `toJson()`），结果用 `*Result.parse`。
abstract interface class SidecarClient {
  /// 发送一次调用，返回结果流。
  ///
  /// [params] 必须是具体方法参数对象的 `toJson()` 结果。
  Stream<Result<Object?>> send(String method, Map<String, Object?> params);

  /// 发送一次调用并按方法解析结果。
  ///
  /// 解析失败（不符合契约）同样以 [Failure] 形式返回，不抛异常。
  Stream<Result<T>> sendTyped<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  );
}
