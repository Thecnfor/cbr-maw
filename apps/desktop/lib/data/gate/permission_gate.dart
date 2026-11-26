import 'package:cbr_maw_contracts/contracts_dart.dart';

/// 审计事件（Dart 层产出，不依赖 sidecar）。
///
/// 字段固定，便于时间线与诊断统一消费。
final class AuditEvent {
  const AuditEvent({
    required this.ts,
    required this.type,
    required this.actor,
    required this.tool,
    required this.riskLevel,
    required this.outcome,
    required this.reason,
    this.detail = const {},
  });

  /// 产生时刻（ISO 8601，+08:00）。
  final String ts;

  /// 事件类型：`tool_invoked` / `permission_denied` / `tool_failed` / `hitl_required`。
  final String type;

  /// 发起角色。
  final String actor;

  /// 工具名。
  final String tool;

  /// 动作风险级。
  final ToolRiskLevel riskLevel;

  /// 结果：`allowed` / `denied` / `failed` / `pending_hitl`。
  final String outcome;

  /// 中文原因（一句话）。
  final String reason;

  /// 明细（参数摘要等；不得含凭证）。
  final Map<String, Object?> detail;

  /// 回写为 JSON 对象（与 contracts 的 audit_events 视图同口径）。
  Map<String, Object?> toJson() => {
    'ts': ts,
    'type': type,
    'actor': actor,
    'tool': tool,
    'risk_level': riskLevel.wire,
    'outcome': outcome,
    'reason': reason,
    'detail': detail,
  };
}

/// 门卫判定结果。
sealed class GateDecision {
  const GateDecision();
}

/// 允许执行。
final class GateAllowed extends GateDecision {
  const GateAllowed({required this.spec, required this.auditEvent});

  /// 工具规格。
  final ToolSpec spec;

  /// 放行审计事件。
  final AuditEvent auditEvent;
}

/// 需要人工确认（L2）。
final class GateNeedsConfirmation extends GateDecision {
  const GateNeedsConfirmation({required this.spec, required this.auditEvent});

  /// 工具规格。
  final ToolSpec spec;

  /// 待确认审计事件。
  final AuditEvent auditEvent;
}

/// 拒绝执行（越权或未登记工具）。
final class GateDenied extends GateDecision {
  const GateDenied({required this.reason, required this.auditEvent});

  /// 中文原因。
  final String reason;

  /// 拒绝审计事件（`permission_denied`）。
  final AuditEvent auditEvent;
}

/// 工具调用门卫（docs/11 §5.5）。
///
/// **权限与审计在 Dart，执行在 Rust**：越权时只产出 `permission_denied`
/// 审计事件，**不发 RPC、工具绝不执行**。`default_deny=true`。
final class PermissionGate {
  /// 创建门卫。
  PermissionGate({
    required this.now,
    this.registry = toolRegistry,
    this.requireConfirmationForL2 = true,
  });

  /// 时钟（注入便于测试）。
  final String Function() now;

  /// 工具注册表（真源：contracts/tools/tools.json）。
  final List<ToolSpec> registry;

  /// L2 是否必须 HITL。
  final bool requireConfirmationForL2;

  /// 鉴权。
  ///
  /// 未登记工具、角色不在 `allowed_roles` 内 → [GateDenied]，且调用方
  /// **不得**再发起 RPC。
  GateDecision authorize({
    required String role,
    required String tool,
    required Map<String, Object?> params,
  }) {
    final spec = _find(tool);
    if (spec == null) {
      return GateDenied(
        reason: '工具 $tool 未在注册表中登记',
        auditEvent: AuditEvent(
          ts: now(),
          type: 'permission_denied',
          actor: role,
          tool: tool,
          riskLevel: ToolRiskLevel.l2,
          outcome: 'denied',
          reason: '未登记的工具一律拒绝执行',
          detail: {'params_keys': params.keys.toList()},
        ),
      );
    }
    if (!spec.allowsRole(role)) {
      return GateDenied(
        reason: '$role 无权调用 ${spec.tool}',
        auditEvent: AuditEvent(
          ts: now(),
          type: 'permission_denied',
          actor: role,
          tool: spec.tool,
          riskLevel: spec.riskLevel,
          outcome: 'denied',
          reason: '角色权限矩阵未授予该工具，工具未执行',
          detail: {'allowed_roles': spec.allowedRoles},
        ),
      );
    }
    final event = AuditEvent(
      ts: now(),
      type: spec.riskLevel == ToolRiskLevel.l2 && requireConfirmationForL2
          ? 'hitl_required'
          : 'tool_invoked',
      actor: role,
      tool: spec.tool,
      riskLevel: spec.riskLevel,
      outcome: spec.riskLevel == ToolRiskLevel.l2 && requireConfirmationForL2
          ? 'pending_hitl'
          : 'allowed',
      reason: '已通过角色权限校验',
      detail: {'params_keys': params.keys.toList()},
    );
    if (spec.riskLevel == ToolRiskLevel.l2 && requireConfirmationForL2) {
      return GateNeedsConfirmation(spec: spec, auditEvent: event);
    }
    return GateAllowed(spec: spec, auditEvent: event);
  }

  ToolSpec? _find(String tool) {
    for (final spec in registry) {
      if (spec.tool == tool) {
        return spec;
      }
    }
    return null;
  }
}
