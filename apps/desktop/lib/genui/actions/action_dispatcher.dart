/// 动作白名单、风险分级、确认、幂等与审计（docs/03 §5）。
///
/// fail-closed：L1/L2 缺确认处理器 → 拒绝执行，绝不降级放行。
library;

import 'dart:convert';

import 'package:crypto/crypto.dart';

import '../catalog/cbr_catalog.dart';

/// 动作执行结果。
final class DispatchResult {
  const DispatchResult._({required this.outcome, this.reason, this.resultRef});

  /// 已执行。
  const DispatchResult.succeeded({String? resultRef})
    : this._(outcome: 'succeeded', resultRef: resultRef);

  /// 幂等命中：返回上次结果。
  const DispatchResult.replayed({String? resultRef})
    : this._(outcome: 'succeeded', resultRef: resultRef);

  /// 被拒。
  const DispatchResult.rejected({required String reason})
    : this._(outcome: 'rejected', reason: reason);

  /// 待确认。
  const DispatchResult.needsConfirmation({required String reason})
    : this._(outcome: 'needsConfirmation', reason: reason);

  /// 执行失败。
  const DispatchResult.failed({required String reason})
    : this._(outcome: 'failed', reason: reason);

  /// 结果：succeeded | rejected | needsConfirmation | failed。
  final String outcome;

  /// 原因。
  final String? reason;

  /// 产物引用。
  final String? resultRef;

  /// 是否已成功（含重放）。
  bool get ok => outcome == 'succeeded';
}

/// 动作注册条目（白名单即安全边界）。
final class ActionSpec {
  /// 创建条目。
  const ActionSpec({
    required this.actionId,
    required this.risk,
    this.idempotent = false,
    this.handler,
  });

  /// 动作 id。
  final String actionId;

  /// 风险级（必须显式声明，缺省不注册）。
  final ActionRisk risk;

  /// 是否写操作（需幂等键）。
  final bool idempotent;

  /// 执行器（null → 仅校验）。
  final Future<Object?> Function(Map<String, Object?> payload)? handler;
}

/// 动作账本条目。
final class ActionLedgerEntry {
  /// 创建条目。
  const ActionLedgerEntry({
    required this.idempotencyKey,
    required this.actionId,
    required this.risk,
    required this.payloadHash,
    this.outcome = 'pending',
    this.resultRef,
  });

  /// 幂等键。
  final String idempotencyKey;

  /// 动作 id。
  final String actionId;

  /// 风险级。
  final ActionRisk risk;

  /// 参数指纹。
  final String payloadHash;

  /// 结果。
  final String outcome;

  /// 产物引用。
  final String? resultRef;

  /// 复制并替换结果。
  ActionLedgerEntry copyWith({String? outcome, String? resultRef}) =>
      ActionLedgerEntry(
        idempotencyKey: idempotencyKey,
        actionId: actionId,
        risk: risk,
        payloadHash: payloadHash,
        outcome: outcome ?? this.outcome,
        resultRef: resultRef ?? this.resultRef,
      );
}

/// 审计事件。
final class AuditEvent {
  /// 创建事件。
  const AuditEvent({
    required this.actionId,
    required this.risk,
    required this.outcome,
    this.idempotencyKey,
    this.detail = const {},
  });

  /// 动作 id。
  final String actionId;

  /// 风险级。
  final ActionRisk risk;

  /// 结果。
  final String outcome;

  /// 幂等键。
  final String? idempotencyKey;

  /// 详情。
  final Map<String, Object?> detail;
}

/// 确认处理器：返回 true 表示用户确认。
typedef ConfirmHandler = Future<bool> Function(
  ActionSpec spec,
  Map<String, Object?> payload,
);

/// 动作分发器。
final class ActionDispatcher {
  /// 创建分发器。
  ActionDispatcher({
    required List<ActionSpec> actions,
    required this.confirm,
    this.auditSink,
  }) : _actions = {
         for (final action in actions)
           // 未显式声明风险的动作在注册时即失败（不进入 registry）。
           if (action.risk.wire.isNotEmpty) action.actionId: action,
       };

  final Map<String, ActionSpec> _actions;
  final Map<String, ActionLedgerEntry> _ledger = {};

  /// 确认处理器（L1/L2 必需）。
  final ConfirmHandler? confirm;

  /// 审计落点。
  final void Function(AuditEvent event)? auditSink;

  /// 已注册动作。
  Iterable<String> get actionIds => _actions.keys;

  /// 分发一次组件动作。
  Future<DispatchResult> dispatch({
    required String actionId,
    required Map<String, Object?> payload,
    ActionRisk? componentRisk,
    String? idempotencyKey,
  }) async {
    final spec = _actions[actionId];
    if (spec == null) {
      _record(
        AuditEvent(
          actionId: actionId,
          risk: componentRisk ?? ActionRisk.l1,
          outcome: 'rejectedUnregistered',
        ),
      );
      return const DispatchResult.rejected(reason: '动作未在白名单内');
    }

    // 组件未声明风险时只取注册表声明；声明了才取更强（strongerRisk 的
    // ?? L1 缺省仅作防御性兜底，不应命中正常路径）。
    final effectiveRisk = componentRisk == null
        ? spec.risk
        : strongerRisk(spec.risk, componentRisk);
    final payloadHash = sha256
        .convert(utf8.encode(jsonEncode(payload)))
        .toString();

    // 幂等：同 key 同 hash 且已成功 → 直接返回上次结果。
    if (idempotencyKey != null) {
      final existing = _ledger[idempotencyKey];
      if (existing != null) {
        if (existing.payloadHash != payloadHash) {
          _record(
            AuditEvent(
              actionId: actionId,
              risk: effectiveRisk,
              outcome: 'rejectedKeyCollision',
              idempotencyKey: idempotencyKey,
            ),
          );
          return const DispatchResult.rejected(reason: '幂等键参数漂移，拒绝执行');
        }
        if (existing.outcome == 'succeeded') {
          return DispatchResult.replayed(resultRef: existing.resultRef);
        }
      }
    }

    // fail-closed：L1/L2 缺确认处理器 → 拒绝执行，不降级为 L0。
    if (effectiveRisk != ActionRisk.l0) {
      final confirmer = confirm;
      if (confirmer == null) {
        _record(
          AuditEvent(
            actionId: actionId,
            risk: effectiveRisk,
            outcome: 'rejectedMissingConfirmer',
            idempotencyKey: idempotencyKey,
          ),
        );
        return const DispatchResult.rejected(reason: '缺少确认处理器');
      }
      final approved = await confirmer(spec, payload);
      if (!approved) {
        _record(
          AuditEvent(
            actionId: actionId,
            risk: effectiveRisk,
            outcome: 'cancelled',
            idempotencyKey: idempotencyKey,
          ),
        );
        return const DispatchResult.rejected(reason: '用户取消');
      }
    }

    if (idempotencyKey != null) {
      _ledger[idempotencyKey] = ActionLedgerEntry(
        idempotencyKey: idempotencyKey,
        actionId: actionId,
        risk: effectiveRisk,
        payloadHash: payloadHash,
      );
    }

    try {
      final result = await spec.handler?.call(payload);
      final resultRef = result?.toString();
      if (idempotencyKey != null) {
        _ledger[idempotencyKey] = _ledger[idempotencyKey]!.copyWith(
          outcome: 'succeeded',
          resultRef: resultRef,
        );
      }
      _record(
        AuditEvent(
          actionId: actionId,
          risk: effectiveRisk,
          outcome: 'succeeded',
          idempotencyKey: idempotencyKey,
          detail: {'payloadHash': payloadHash},
        ),
      );
      return DispatchResult.succeeded(resultRef: resultRef);
    } catch (error) {
      if (idempotencyKey != null) {
        _ledger[idempotencyKey] = _ledger[idempotencyKey]!.copyWith(
          outcome: 'failed',
        );
      }
      _record(
        AuditEvent(
          actionId: actionId,
          risk: effectiveRisk,
          outcome: 'failed',
          idempotencyKey: idempotencyKey,
          detail: {'error': error.toString()},
        ),
      );
      return DispatchResult.failed(reason: error.toString());
    }
  }

  /// 查询账本。
  ActionLedgerEntry? ledger(String idempotencyKey) => _ledger[idempotencyKey];

  void _record(AuditEvent event) => auditSink?.call(event);
}
