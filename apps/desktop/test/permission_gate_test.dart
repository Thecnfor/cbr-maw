import 'dart:async';

import 'package:cbr_maw/data/gate/permission_gate.dart';
import 'package:cbr_maw/data/gate/tool_invoker.dart';
import 'package:cbr_maw/data/sidecar/sidecar_supervisor.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:flutter_test/flutter_test.dart';

/// 记录所有发往 sidecar 的调用，用来断言「越权不发 RPC」。
final class _RecordingClient implements SidecarClient {
  final calls = <String>[];

  @override
  Stream<Result<Object?>> send(String method, Map<String, Object?> params) {
    calls.add(method);
    return Stream.value(
      Success<Object?>({
        'evidence': {
          'evidence_id': 'ev_test',
          'tool': 'risk_measure',
          'version': '1.0.0',
          'inputs_hash': 'a' * 64,
          'hash': 'b' * 64,
          'as_of': '2026-11-25T18:00:00+08:00',
          'params': <String, Object?>{},
        },
      }),
    );
  }

  @override
  Stream<Result<T>> sendTyped<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) {
    calls.add(method);
    return Stream.value(
      Success<T>(
        parse({
          'evidence': {
            'evidence_id': 'ev_test',
            'tool': 'risk_measure',
            'version': '1.0.0',
            'inputs_hash': 'a' * 64,
            'hash': 'b' * 64,
            'as_of': '2026-11-25T18:00:00+08:00',
            'params': <String, Object?>{},
          },
        }),
      ),
    );
  }
}

void main() {
  group('权限门卫', () {
    final gate = PermissionGate(now: () => '2026-11-25T18:00:00+08:00');

    test('越权 → GateDenied 且 reason 明确', () {
      // financing 无权调用 systemic_risk（roles.yaml 的 tool_permissions）。
      final decision = gate.authorize(
        role: 'financing',
        tool: 'systemic_risk',
        params: const {},
      );
      expect(decision, isA<GateDenied>());
      final denied = decision as GateDenied;
      expect(denied.auditEvent.type, 'permission_denied');
      expect(denied.auditEvent.outcome, 'denied');
      expect(denied.reason, contains('无权'));
    });

    test('未登记工具 → 拒绝（default_deny）', () {
      final decision = gate.authorize(
        role: 'regulator',
        tool: 'drop_tables',
        params: const {},
      );
      expect(decision, isA<GateDenied>());
    });

    test('未知角色 → 拒绝', () {
      final decision = gate.authorize(
        role: 'intruder',
        tool: 'risk_measure',
        params: const {},
      );
      expect(decision, isA<GateDenied>());
    });

    test('授权角色 → GateAllowed 并记 tool_invoked', () {
      final decision = gate.authorize(
        role: 'regulator',
        tool: 'systemic_risk',
        params: const {},
      );
      expect(decision, isA<GateAllowed>());
      expect((decision as GateAllowed).auditEvent.type, 'tool_invoked');
    });

    test('L0 工具全部通过 risk_measure 的三个授权角色', () {
      for (final role in ['regulator', 'investor', 'financing']) {
        final decision = gate.authorize(
          role: role,
          tool: 'risk_measure',
          params: const {},
        );
        expect(decision, isA<GateAllowed>(), reason: role);
      }
    });
  });

  group('工具调用：越权不发 RPC', () {
    test('越权调用不产生任何 sidecar 请求', () async {
      final client = _RecordingClient();
      final audits = <AuditEvent>[];
      final invoker = GatedToolInvoker(
        client: client,
        gate: PermissionGate(now: () => '2026-11-25T18:00:00+08:00'),
        auditSink: audits.add,
      );

      final outcome = await invoker.invoke(
        role: 'financing',
        tool: 'systemic_risk',
        params: const {},
        idempotencyKey: 'k1',
      );

      expect(outcome, isA<ToolCallDenied>());
      expect(client.calls, isEmpty, reason: '越权绝不能发 RPC');
      expect(audits.single.type, 'permission_denied');
    });

    test('未登记工具同样不发 RPC', () async {
      final client = _RecordingClient();
      final invoker = GatedToolInvoker(
        client: client,
        gate: PermissionGate(now: () => '2026-11-25T18:00:00+08:00'),
        auditSink: (_) {},
      );

      final outcome = await invoker.invoke(
        role: 'regulator',
        tool: 'rm_rf',
        params: const {},
        idempotencyKey: 'k2',
      );

      expect(outcome, isA<ToolCallDenied>());
      expect(client.calls, isEmpty);
    });

    test('授权调用恰好发一次 tools.invoke', () async {
      final client = _RecordingClient();
      final invoker = GatedToolInvoker(
        client: client,
        gate: PermissionGate(now: () => '2026-11-25T18:00:00+08:00'),
        auditSink: (_) {},
      );

      final outcome = await invoker.invoke(
        role: 'regulator',
        tool: 'risk_measure',
        params: const {'series_id': 'market.cn_equity.csi300'},
        idempotencyKey: 'k3',
      );

      expect(outcome, isA<ToolCallSucceeded>());
      expect(client.calls, ['tools.invoke']);
    });
  });

  group('sidecar 生命周期状态', () {
    test('初始为未启动', () {
      final supervisor = SidecarSupervisor(
        transportFactory: () => throw UnimplementedError(),
        clientVersion: '0.1.0',
        contractVersion: '1.0.0',
        workspace: '/tmp/ws',
        dataHome: '/tmp/data',
        resourceHome: '/tmp/res',
      );
      expect(supervisor.state, SidecarState.idle);
      expect(supervisor.handshake, isNull);
    });
  });
}
