/// 编排模式开关（docs/03 §2.4）：同一代码路径仅 4 个开关 + 伪分工。
library;

/// 四种模式。
enum CollaborationMode {
  single('single'),
  independent('independent'),
  collaborative('collaborative'),
  demo('demo');

  const CollaborationMode(this.wire);

  /// JSON 字面量。
  final String wire;

  /// 从字面量解析。
  static CollaborationMode parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ArgumentError('未知协作模式：$raw');
  }
}

/// 模式开关。
final class ModeFlags {
  /// 创建开关。
  const ModeFlags({
    required this.mode,
    required this.useSingleAgent,
    required this.shareEvidence,
    required this.crossValidate,
    required this.coordinate,
    this.pseudoSpecialize = false,
  });

  /// 模式。
  final CollaborationMode mode;

  /// 用一个通用 agent 依次完成三主体任务。
  final bool useSingleAgent;

  /// R1 证据共享。
  final bool shareEvidence;

  /// R2 交叉验证。
  final bool crossValidate;

  /// R3/R4 分歧与协调。
  final bool coordinate;

  /// 伪分工对照（E8）。
  final bool pseudoSpecialize;

  /// 按模式取开关。
  static ModeFlags of(CollaborationMode mode) => switch (mode) {
    CollaborationMode.single => const ModeFlags(
      mode: CollaborationMode.single,
      useSingleAgent: true,
      shareEvidence: false,
      crossValidate: false,
      coordinate: false,
    ),
    CollaborationMode.independent => const ModeFlags(
      mode: CollaborationMode.independent,
      useSingleAgent: false,
      shareEvidence: false,
      crossValidate: false,
      coordinate: false,
    ),
    CollaborationMode.collaborative => const ModeFlags(
      mode: CollaborationMode.collaborative,
      useSingleAgent: false,
      shareEvidence: true,
      crossValidate: true,
      coordinate: true,
    ),
    CollaborationMode.demo => const ModeFlags(
      mode: CollaborationMode.demo,
      useSingleAgent: false,
      shareEvidence: true,
      crossValidate: true,
      coordinate: true,
    ),
  };
}
