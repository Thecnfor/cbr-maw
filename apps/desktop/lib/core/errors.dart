/// 错误类型三分层与中文三段式文案（docs/08 §1.3）。
///
/// - 预期错误（expected）：用户可修正，如缺密钥、来源需授权；
/// - 编程错误（programming）：代码缺陷，不引导用户重试；
/// - 外部失败（external）：进程、网络、平台能力失败。
library;

/// 错误分层。
enum ErrorLayer {
  /// 用户可修正的预期错误。
  expected('预期错误'),

  /// 代码缺陷。
  programming('编程错误'),

  /// 外部失败（进程/网络/平台）。
  external('外部失败');

  const ErrorLayer(this.label);

  /// 中文标签。
  final String label;
}

/// 应用错误：固定三段式「错在哪 / 为什么 / 影响或下一步」。
final class AppError implements Exception {
  const AppError({
    required this.layer,
    required this.code,
    required this.what,
    required this.why,
    required this.next,
    this.detail = const {},
  });

  /// 配置缺失或非法。
  factory AppError.config({
    required String why,
    String next = '可检查配置目录下的 app.json 后重启',
    Map<String, Object?> detail = const {},
  }) => AppError(
    layer: ErrorLayer.expected,
    code: 'E_CONFIG',
    what: '配置加载失败',
    why: why,
    next: next,
    detail: detail,
  );

  /// 能力当前不可用（内核未就绪、平台不支持）。
  factory AppError.unavailable({
    required String code,
    required String what,
    required String why,
    required String next,
    Map<String, Object?> detail = const {},
  }) => AppError(
    layer: ErrorLayer.external,
    code: code,
    what: what,
    why: why,
    next: next,
    detail: detail,
  );

  /// 编程错误。
  factory AppError.programming(String why) => AppError(
    layer: ErrorLayer.programming,
    code: 'E_PROGRAMMING',
    what: '内部状态异常',
    why: why,
    next: '请复制诊断信息并反馈',
  );

  /// 分层。
  final ErrorLayer layer;

  /// 稳定错误码。
  final String code;

  /// 发生了什么。
  final String what;

  /// 为什么。
  final String why;

  /// 下一步能做什么（或影响）。
  final String next;

  /// 明细。
  final Map<String, Object?> detail;

  /// 三段式文案。
  String get message => '$what。$why。$next。';

  @override
  String toString() => '[$code] $message';
}
