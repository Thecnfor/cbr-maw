// 完整链路集成测试（桌面端，跑在 flutter-tester 上，不需要真实窗口/内核）。
//
// 覆盖：
//   1. 设置密钥（内存桩 + 临时目录文件存储，**不碰 secrets/ 真实密钥**）；
//   2. 触发一次研判 → 拿到 RunSummary；
//   3. 校验 claim 绑定 evidence（每条 claim 的证据都在本次 run 的证据集合内）；
//   4. 校验权限越权被拒（工具未执行、不发 RPC）；
//   5. 校验审计事件可落盘并回读（JSONL）。
//
// 运行：
//   cd apps/desktop
//   flutter test -d flutter-tester integration_test/full_chain_test.dart
//   （Linux 桌面设备需先装 gstreamer-1.0 等插件依赖，见 integration_test/README.md）
//
// 桩数据一律显式标注 SYNTHETIC；本测试不读取、不写入真实行情或真实密钥。
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:cbr_maw/agents/investigation_controller.dart';
import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:cbr_maw/agents/run_events.dart';
import 'package:cbr_maw/core/secret_store.dart';
import 'package:cbr_maw/data/gate/permission_gate.dart';
import 'package:cbr_maw/data/gate/tool_invoker.dart' as gate_layer;
import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;

import '../test/agents/fixtures.dart';

/// 桩数据的显式标记：任何进入结论文本的桩数值都必须带这个标记。
const _synthetic = 'SYNTHETIC';

/// 记录所有发往 sidecar 的调用，用来断言「越权不发 RPC」。
final class _RecordingClient implements SidecarClient {
  final calls = <String>[];

  Map<String, Object?> _evidence(String tool) => {
    'evidence': {
      'evidence_id': 'ev_${tool}_synthetic',
      'tool': tool,
      'version': '1.0.0',
      'inputs_hash': 'a' * 64,
      'hash': 'b' * 64,
      'value': 0.42,
      'unit': 'ratio',
      'as_of': '2024-08-05',
      'params': <String, Object?>{'synthetic': true},
    },
  };

  @override
  Stream<Result<Object?>> send(String method, Map<String, Object?> params) {
    calls.add(method);
    return Stream.value(Success<Object?>(_evidence('risk_measure')));
  }

  @override
  Stream<Result<T>> sendTyped<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) {
    calls.add(method);
    return Stream.value(Success<T>(parse(_evidence('risk_measure'))));
  }
}

/// JSONL 审计落盘：把 AuditEvent 按行写入临时文件。
final class _JsonlAuditSink {
  _JsonlAuditSink(this.file) {
    file.parent.createSync(recursive: true);
    file.writeAsStringSync('');
  }

  final File file;
  final events = <AuditEvent>[];

  void add(AuditEvent event) {
    events.add(event);
    file.writeAsStringSync(
      '${jsonEncode(event.toJson())}\n',
      mode: FileMode.append,
    );
  }

  List<Map<String, Object?>> readBack() => [
    for (final line in file.readAsLinesSync())
      if (line.trim().isNotEmpty) jsonDecode(line) as Map<String, Object?>,
  ];
}

/// 与单元测试同一套桩：确定性工具 + 按证据回填的脚本化生成器。
///
/// 桩数值在 claim 主题里带 SYNTHETIC 标记，确保"桩响应显式标注 synthetic"。
AgentSettings _settings() => settingsFor(
  generator: ScriptedGenerator((purpose, user) {
    final id = RegExp(r'"evidence_id":"(ev_[^"]+)"').firstMatch(user)?.group(1);
    return {
      'headline': '压力上升（$_synthetic 测试桩）',
      'claims': [
        if (id != null)
          {
            'claim_type': 'numeric',
            'subject': '系统外溢指数（$_synthetic 测试桩）',
            'text': '外溢指数上升',
            'value': 0.62,
            'unit': 'ratio',
            'evidence_ids': [id],
          },
        // 无证据的 claim 必须被回填层丢弃（不得进入结论）。
        {
          'claim_type': 'numeric',
          'subject': '凭空指标',
          'text': '没有证据的数值',
          'value': 0.5,
          'evidence_ids': ['ev_fabricated'],
        },
      ],
      'recommendation': '关注跨市场外溢。',
      'limitations': <String>['$_synthetic：桩响应，仅用于集成测试'],
    };
  }),
  invoker: FakeInvoker(
    values: {
      'systemic_risk': 0.62,
      'risk_measure': 0.11,
      'capital_flow': 0.2,
      'scenario': 0.05,
      'forecast': 0.4,
      'funding_cost': 60.0,
    },
  ),
);

void main() {
  late Directory tempRoot;

  setUp(() {
    tempRoot = Directory.systemTemp.createTempSync('cbr_it_');
  });

  tearDown(() {
    if (tempRoot.existsSync()) {
      tempRoot.deleteSync(recursive: true);
    }
  });

  test('1) 密钥：内存桩 + 临时目录文件存储，不触碰真实密钥', () async {
    // 真实 secrets/ 目录不得被读写：断言仓库 secrets/deepseek.key 的路径不在本次操作里。
    final repoSecret = File(
      p.join(Directory.current.path, '..', '..', 'secrets', 'deepseek.key'),
    );
    final repoSecretBefore = repoSecret.existsSync()
        ? repoSecret.lastModifiedSync()
        : null;

    final provider = InMemorySecretProvider({
      'DEEPSEEK_API_KEY': 'sk-test-SYNTHETIC-0000abcd',
    });
    expect(
      await provider.read('DEEPSEEK_API_KEY'),
      'sk-test-SYNTHETIC-0000abcd',
    );
    expect(maskSecret('sk-test-SYNTHETIC-0000abcd'), 'sk-****abcd');

    final store = await openSecretStore(p.join(tempRoot.path, 'secrets'));
    await store.write('deepseek', 'sk-test-SYNTHETIC-0000abcd');
    expect(await store.read('deepseek'), 'sk-test-SYNTHETIC-0000abcd');
    expect(store.osEncrypted, isFalse, reason: '受限权限文件不是系统级加密，UI 必须提示降级');
    expect(await store.read('missing'), isNull);

    final repoSecretAfter = repoSecret.existsSync()
        ? repoSecret.lastModifiedSync()
        : null;
    expect(repoSecretAfter, repoSecretBefore, reason: '测试不得触碰真实密钥文件');
  });

  test('2) 一次研判 → RunSummary，claim 绑定 evidence', () async {
    final settings = _settings();
    final runtime = AgentRuntime(settings);
    final events = await runtime
        .run(
          question: '评估 2024-08-05 的跨境风险',
          runId: 'run_it',
          asOf: DateTime.utc(2024, 8, 5),
          mode: settings.defaultMode,
        )
        .toList();

    expect(events.whereType<RunStarted>(), hasLength(1));
    final summary = events.whereType<RunFinished>().single.summary;
    expect(summary.runId, 'run_it');
    expect(summary.mode, 'collaborative');
    expect(summary.riskLevel, isIn(['low', 'medium', 'high', 'critical']));
    expect(summary.claimIds, isNotEmpty);
    expect(summary.evidenceIds, isNotEmpty);
    expect(summary.partial, isFalse);

    // claim → evidence 强制绑定：每条 claim 至少一条证据，且都在本次 run 的证据集合内。
    final produced = events.whereType<ClaimProduced>().toList();
    expect(produced, isNotEmpty);
    final known = summary.evidenceIds.toSet();
    for (final claim in produced) {
      expect(
        claim.evidenceIds,
        isNotEmpty,
        reason: 'claim ${claim.claimId} 没有绑定证据',
      );
      for (final id in claim.evidenceIds) {
        expect(
          known.contains(id),
          isTrue,
          reason: 'claim ${claim.claimId} 引用了本次 run 之外的证据 $id',
        );
      }
      // 桩响应显式标注 synthetic（数值 claim 的文本来自桩的 subject）。
      expect(claim.text, contains(_synthetic), reason: '桩响应必须显式标注 SYNTHETIC');
    }
    // 无证据的草稿不得进入结论。
    expect(produced.any((c) => c.text.contains('没有证据的数值')), isFalse);

    // 证据必须带可重算的哈希（三级哈希中的 evidence.hash）。
    final toolEvents = events.whereType<ToolInvoked>().toList();
    expect(toolEvents, isNotEmpty);
  });

  test('3) 权限越权被拒：工具未执行、不发 RPC、审计留痕', () async {
    final client = _RecordingClient();
    final sink = _JsonlAuditSink(
      File(p.join(tempRoot.path, 'traces', 'audit.jsonl')),
    );
    final gate = PermissionGate(now: () => '2024-08-05T18:00:00+08:00');
    final invoker = gate_layer.GatedToolInvoker(
      client: client,
      gate: gate,
      auditSink: sink.add,
      now: () => '2024-08-05T18:00:00+08:00',
    );

    // financing 不在 systemic_risk 的 allowed_roles 内（契约注册表）。
    final denied = await invoker.invoke(
      role: 'financing',
      tool: 'systemic_risk',
      params: const {},
      idempotencyKey: 'idem_denied',
    );
    expect(denied, isA<gate_layer.ToolCallDenied>());
    expect(client.calls, isEmpty, reason: '越权必须不发 RPC');

    // 未登记工具同样拒绝。
    final unknown = await invoker.invoke(
      role: 'regulator',
      tool: 'no_such_tool',
      params: const {},
      idempotencyKey: 'idem_unknown',
    );
    expect(unknown, isA<gate_layer.ToolCallDenied>());
    expect(client.calls, isEmpty);

    // 合法调用才发 RPC，并带回证据。
    final allowed = await invoker.invoke(
      role: 'regulator',
      tool: 'risk_measure',
      params: const {'lookback': 252},
      idempotencyKey: 'idem_ok',
    );
    expect(allowed, isA<gate_layer.ToolCallSucceeded>());
    expect(client.calls, ['tools.invoke']);
    final evidence = (allowed as gate_layer.ToolCallSucceeded).evidence;
    expect(evidence.evidenceId, 'ev_risk_measure_synthetic');
    expect(evidence.hash, 'b' * 64);

    // 审计事件落盘：JSONL 可回读，类型与结果正确。
    final written = sink.readBack();
    expect(written, hasLength(3));
    final denial = written.first;
    expect(denial['type'], 'permission_denied');
    expect(denial['outcome'], 'denied');
    expect(denial['actor'], 'financing');
    expect(denial['tool'], 'systemic_risk');
    expect(denial['risk_level'], isA<String>());
    expect(denial['reason'], isA<String>());
    expect((denial['detail'] as Map).containsKey('allowed_roles'), isTrue);
    expect(written[2]['type'], 'tool_invoked');
    expect(written[2]['outcome'], 'allowed');
  });

  test('4) 审计事件落盘：文件在可写根下，仓库目录不被写入', () async {
    final sink = _JsonlAuditSink(
      File(p.join(tempRoot.path, 'traces', 'audit.jsonl')),
    );
    final gate = PermissionGate(now: () => '2024-08-05T18:00:00+08:00');
    final invoker = gate_layer.GatedToolInvoker(
      client: _RecordingClient(),
      gate: gate,
      auditSink: sink.add,
      now: () => '2024-08-05T18:00:00+08:00',
    );
    await invoker.invoke(
      role: 'investor',
      tool: 'funding_cost',
      params: const {},
      idempotencyKey: 'idem_audit',
    );

    expect(
      File(p.join(tempRoot.path, 'traces', 'audit.jsonl')).existsSync(),
      isTrue,
    );
    final lines = sink.readBack();
    expect(lines, hasLength(1));
    expect(lines.single['tool'], 'funding_cost');
    expect(p.isWithin(tempRoot.path, sink.file.path), isTrue);
  });
}
