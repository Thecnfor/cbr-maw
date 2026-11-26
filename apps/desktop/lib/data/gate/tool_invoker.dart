import 'dart:async';

import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../../core/clock.dart';
import '../gate/permission_gate.dart';

/// 工具调用的最终结果（Dart 层语义）。
sealed class ToolCallOutcome {
  const ToolCallOutcome();
}

/// 执行成功，带回证据。
final class ToolCallSucceeded extends ToolCallOutcome {
  const ToolCallSucceeded({required this.evidence, required this.audit});

  /// 工具证据。
  final ToolEvidence evidence;

  /// 审计事件。
  final AuditEvent audit;
}

/// 被门卫拒绝（**未发 RPC**）。
final class ToolCallDenied extends ToolCallOutcome {
  const ToolCallDenied({required this.audit});

  /// `permission_denied` 审计事件。
  final AuditEvent audit;
}

/// 需要人工确认（**未发 RPC**）。
final class ToolCallNeedsConfirmation extends ToolCallOutcome {
  const ToolCallNeedsConfirmation({required this.audit});

  /// `hitl_required` 审计事件。
  final AuditEvent audit;
}

/// 执行失败（已发 RPC，但内核返回错误）。
final class ToolCallFailed extends ToolCallOutcome {
  const ToolCallFailed({required this.message, required this.audit});

  /// 三段式中文文案。
  final String message;

  /// 失败审计事件。
  final AuditEvent audit;
}

/// 工具调用服务：门卫先行，通过后才发 RPC。
///
/// 这是全应用**唯一**允许调用 `tools.invoke` 的入口。
final class GatedToolInvoker {
  /// 创建调用器。
  GatedToolInvoker({
    required this.client,
    required this.gate,
    required this.auditSink,
    String Function()? now,
  }) : _now = now ?? Clock.asOfNow;

  /// sidecar 客户端。
  final SidecarClient client;

  /// 权限门卫。
  final PermissionGate gate;

  /// 审计接收（UI 时间线消费）。
  final void Function(AuditEvent event) auditSink;

  final String Function() _now;

  /// 以 [role] 身份调用 [tool]。
  ///
  /// 门卫拒绝时**不产生任何网络/进程调用**。
  Future<ToolCallOutcome> invoke({
    required String role,
    required String tool,
    required Map<String, Object?> params,
    required String idempotencyKey,
    bool confirmed = false,
  }) async {
    final decision = gate.authorize(role: role, tool: tool, params: params);
    final AuditEvent event;
    final ToolRiskLevel riskLevel;
    switch (decision) {
      case GateDenied(:final auditEvent):
        auditSink(auditEvent);
        return ToolCallDenied(audit: auditEvent);
      case GateNeedsConfirmation(:final auditEvent) when !confirmed:
        auditSink(auditEvent);
        return ToolCallNeedsConfirmation(audit: auditEvent);
      case GateAllowed(:final spec, :final auditEvent):
        event = auditEvent;
        riskLevel = spec.riskLevel;
      case GateNeedsConfirmation(:final spec, :final auditEvent):
        event = auditEvent;
        riskLevel = spec.riskLevel;
    }
    auditSink(event);
    final results = await client
        .sendTyped<ToolsInvokeResult>(
          'tools.invoke',
          ToolsInvokeParams(
            tool: ToolName.parse(tool),
            params: params,
            idempotencyKey: idempotencyKey,
          ).toJson(),
          ToolsInvokeResult.parse,
        )
        .toList();
    final result = results.single;
    switch (result) {
      case Success(:final value):
        return ToolCallSucceeded(evidence: value.evidence, audit: event);
      case Failure(:final error):
        final failure = AuditEvent(
          ts: _now(),
          type: 'tool_failed',
          actor: role,
          tool: tool,
          riskLevel: riskLevel,
          outcome: 'failed',
          reason: error.message,
          detail: error.detail,
        );
        auditSink(failure);
        return ToolCallFailed(
          message: '工具调用失败。${error.message}。可重试，或查看诊断信息。',
          audit: failure,
        );
    }
  }
}
