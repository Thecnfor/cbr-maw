/// CBR-MAW 跨语言契约的 Dart 类型层。
///
/// 真源是 `contracts/` 下的 JSON Schema 与工具注册表；本包提供
/// 与之对应的强类型 Dart 视图：**解析即校验**，不使用 `dynamic`。
///
/// - 信封与错误码：[RpcRequest] / [RpcSuccessResponse] / [RpcErrorResponse] / [RpcErrorKind]
/// - 方法参数与结果：`contracts_dart.dart` 导出的各 `*Params` / `*Result`
/// - 工具注册表：[toolRegistry]
/// - 三级证据哈希：[EvidenceHash]
library;

export 'src/canonical_json.dart';
export 'src/contract_format_exception.dart';
export 'src/evidence_hash.dart';
export 'src/json_reader.dart';
export 'src/rpc.dart';
export 'src/sidecar_client.dart';
