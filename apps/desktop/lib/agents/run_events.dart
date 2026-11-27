/// 应用外壳唯一依赖的事件契约（跨 agent 固定接口）。
///
/// 字段与方法签名不得改动；实现内部结构变化不影响外壳。
library;

/// 一次研判的事件流单元。
sealed class RunEvent {
  /// 创建事件。
  const RunEvent();
}

/// 研判开始。
final class RunStarted extends RunEvent {
  /// 创建事件。
  const RunStarted(this.runId, this.mode);

  /// run id。
  final String runId;

  /// 模式：single | independent | collaborative | demo。
  final String mode;
}

/// 角色活动（R0 分析、R2 复核等）。
final class AgentActivity extends RunEvent {
  /// 创建事件。
  const AgentActivity(this.runId, this.agentRole, this.action, this.detail);

  /// run id。
  final String runId;

  /// 角色 id。
  final String agentRole;

  /// 动作（如 role_start / role_done / peer_review）。
  final String action;

  /// 结构化细节。
  final Map<String, Object?> detail;
}

/// 工具调用（含被拒）。
final class ToolInvoked extends RunEvent {
  /// 创建事件。
  const ToolInvoked(
    this.runId,
    this.tool,
    this.params,
    this.result,
    this.denied,
  );

  /// run id。
  final String runId;

  /// 工具名。
  final String tool;

  /// 参数。
  final Map<String, Object?> params;

  /// 结果摘要（被拒时为 null）。
  final Object? result;

  /// 是否越权被拒。
  final bool denied;
}

/// 产出一条通过自检回填的 claim。
final class ClaimProduced extends RunEvent {
  /// 创建事件。
  const ClaimProduced(
    this.runId,
    this.claimId,
    this.text,
    this.kind,
    this.evidenceIds,
    this.confidence,
  );

  /// run id。
  final String runId;

  /// claim id。
  final String claimId;

  /// 文本。
  final String text;

  /// 类型：numeric | text | directional。
  final String kind;

  /// 绑定证据。
  final List<String> evidenceIds;

  /// 置信度。
  final String? confidence;
}

/// 检出冲突。
final class ConflictFound extends RunEvent {
  /// 创建事件。
  const ConflictFound(
    this.runId,
    this.conflictId,
    this.category,
    this.details,
    this.escalated,
  );

  /// run id。
  final String runId;

  /// 冲突 id。
  final String conflictId;

  /// 分类：fact | directional | preference。
  final String category;

  /// 详情。
  final Map<String, Object?> details;

  /// 是否升级人工。
  final bool escalated;
}

/// 研判失败（零 Mock：显式失败，不产出模板结论）。
final class RunFailed extends RunEvent {
  /// 创建事件。
  const RunFailed(
    this.runId,
    this.code,
    this.message,
    this.degraded,
    this.limitations,
  );

  /// run id。
  final String runId;

  /// 错误码。
  final String code;

  /// 中文说明。
  final String message;

  /// 是否已降级（部分结论）。
  final bool degraded;

  /// 局限。
  final List<String> limitations;
}

/// 研判结束。
final class RunFinished extends RunEvent {
  /// 创建事件。
  const RunFinished(this.runId, this.summary);

  /// run id。
  final String runId;

  /// 摘要。
  final RunSummary summary;
}

/// 一次研判的摘要。
final class RunSummary {
  /// 创建摘要。
  const RunSummary({
    required this.runId,
    required this.mode,
    required this.riskLevel,
    required this.claimIds,
    required this.evidenceIds,
    required this.conflictIds,
    required this.degradedRoles,
    required this.limitations,
    required this.tokensUsed,
    required this.costUsd,
    required this.partial,
    this.verification,
    this.roles = const [],
  });

  /// run id。
  final String runId;

  /// 模式。
  final String mode;

  /// 最终风险等级（low | medium | high | critical）。
  final String riskLevel;

  /// 保留的 claim id。
  final List<String> claimIds;

  /// 证据 id。
  final List<String> evidenceIds;

  /// 冲突 id。
  final List<String> conflictIds;

  /// 降级角色。
  final List<String> degradedRoles;

  /// 局限。
  final List<String> limitations;

  /// 消耗 token。
  final int tokensUsed;

  /// 估算成本（美元，按配置成本模型）。
  final double costUsd;

  /// 是否部分结论。
  final bool partial;

  /// 六类核验摘要（界面与导出都要能看见；null = 未核验）。
  final Map<String, Object?>? verification;

  /// 三主体子卡摘要（角色 / 等级 / 标题 / 证据数 / 是否降级）。
  ///
  /// 三主体是本产品的核心卖点，但此前界面只显示"最终等级"，看不到
  /// 「三个主体各自怎么看」——那正是多主体相对单模型的可解释性所在。
  final List<Map<String, Object?>> roles;
}
