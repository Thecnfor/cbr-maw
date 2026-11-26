/// 契约解析失败：字段缺失、类型不符、枚举越界或取值越界。
///
/// 契约层坚持「解析即校验」：任何不符合 schema 的载荷在解析处即失败，
/// 不允许把非法数据带进业务层。
final class ContractFormatException implements Exception {
  const ContractFormatException(this.message, {this.path});

  /// 人类可读的中文短句。
  final String message;

  /// 出错位置（如 `params.sources[0].id`）；根节点为 null。
  final String? path;

  @override
  String toString() => path == null
      ? 'ContractFormatException: $message'
      : 'ContractFormatException: $message (at $path)';
}
