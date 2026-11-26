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

/// 认知与证据消融开关（ADR-010 §1、docs/01 §2.3）。
///
/// 与 [CollaborationMode] 正交：协作模式决定「几个主体怎么配合」，
/// 消融开关决定「认知增强模块开不开」。论文的三情景对照与消融实验
/// 都靠这两组开关的笛卡尔积跑出来，保证对照组之间无实现偏差。
final class AblationFlags {
  /// 创建消融开关（默认全开 = 完整 CBR-MAW）。
  const AblationFlags({
    this.miMemory = true,
    this.llrReflection = true,
    this.hlrReflection = true,
    this.multimodalAux = true,
    this.evidenceStrength = EvidenceStrength.full,
    this.extraTools = const {},
  });

  /// 全部关闭（纯工具基线）。
  static const AblationFlags none = AblationFlags(
    miMemory: false,
    llrReflection: false,
    hlrReflection: false,
    multimodalAux: false,
  );

  /// MI 库（市场情报记忆）。
  final bool miMemory;

  /// 浅层反思（LLR：相似历史案例）。
  final bool llrReflection;

  /// 深层反思（HLR：预警效能复盘）。
  final bool hlrReflection;

  /// 多模态辅助证据。
  final bool multimodalAux;

  /// 证据强度：`weak` 用于在不触发权限拦截的前提下测量幻觉率。
  final EvidenceStrength evidenceStrength;

  /// 额外启用的工具（消融臂 D 用：去掉某些工具后看增量）。
  final Set<String> extraTools;

  /// 是否需要跨时点反思（任一反思开关打开）。
  bool get usesReflection => llrReflection || hlrReflection;

  /// 序列化（写进实验产物，便于复现）。
  Map<String, Object?> toJson() => {
    'mi_memory': miMemory,
    'llr_reflection': llrReflection,
    'hlr_reflection': hlrReflection,
    'multimodal_aux': multimodalAux,
    'evidence_strength': evidenceStrength.wire,
    'extra_tools': extraTools.toList()..sort(),
  };
}

/// 证据强度（docs/01 §2.3）。
enum EvidenceStrength {
  /// 完整证据包。
  full('full'),

  /// 弱证据：用于测量模型在证据不足时的幻觉率。
  weak('weak');

  const EvidenceStrength(this.wire);

  /// JSON 字面量。
  final String wire;
}
