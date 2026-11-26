// 真实链路研判集成测试：真实 Rust kernel（工具 + 信号）+ 真实生成端（OpenAI 兼容）。
//
// 覆盖 docs/23 的过程类指标（A/B 组没有的那些）：
//   - 证据可溯源率：每条 claim 的 evidence_id 都在本次 run 的证据集合内；
//   - 数值不一致率：numeric claim 的 value 必须等于工具/信号证据的值（容差 0）；
//   - 泄漏检出数：证据 as_of 不得晚于决策时点；
//   - 分歧分类计数：fact / directional / preference / modality_conflict；
//   - 成本与延迟：token、端到端毫秒。
//
// 运行（仓库根）：
//   CBR_BENCH_DAYS=6 CBR_BENCH_OUT=artifacts/bench/live.json \
//   flutter test -d flutter-tester apps/desktop/integration_test/live_bench_test.dart
//
// 依赖：kernel 可执行体（CBR_KERNEL_BIN，缺省 target/release/cbr-kernel）、
//       ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN（OpenAI 兼容生成端）、
//       真实 PIT 库（CBR_PIT_DB）。任一缺失 → 整组 skip，绝不伪造结果。
import 'dart:convert';
import 'dart:io';

import 'package:cbr_maw/agents/investigation_controller.dart';
import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw/agents/orchestrator/mode_flags.dart';
import 'package:cbr_maw/agents/roles/prompt_builder.dart';
import 'package:cbr_maw/agents/roles/role_config.dart';
import 'package:cbr_maw/agents/run_events.dart';
import 'package:cbr_maw/agents/tools/tool_registry.dart';
import 'package:cbr_maw/data/gate/permission_gate.dart';
import 'package:cbr_maw/data/gate/tool_invoker.dart';
import 'package:cbr_maw/data/sidecar/sidecar_supervisor.dart';
import 'package:cbr_maw/data/sidecar/stdio_transport.dart';
import 'package:cbr_maw/agents/signals/kernel_signal_source.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;


/// 环境变量密钥源（bench 专用；产品内走 OS 安全存储）。
final class _EnvSecrets implements SecretProvider {
  _EnvSecrets(this.values);

  final Map<String, String> values;

  @override
  Future<String?> read(String key) async => values[key];
}

/// 确定性但形状正确的裁判桩（bench 不依赖 JEV；不伪造判断结果）。
final class _NoJudge implements Judge {
  @override
  Future<bool> get available async => false;

  @override
  Future<JudgeAnswer> ask({
    required Object state,
    required ChoiceQuestion question,
  }) => throw UnsupportedError('bench 不调用裁判');
}

void main() {
  final root = _repoRoot();
  final kernelBin =
      Platform.environment['CBR_KERNEL_BIN'] ??
      p.join(root, 'services/kernel/target/release/cbr-kernel');
  final pitDb =
      Platform.environment['CBR_PIT_DB'] ??
      '/mnt/shared/recently/commorcial/data/pit_real.duckdb';
  final baseUrl = Platform.environment['ANTHROPIC_BASE_URL'];
  final token = Platform.environment['ANTHROPIC_AUTH_TOKEN'];
  final days = int.parse(Platform.environment['CBR_BENCH_DAYS'] ?? '4');
  final mode = CollaborationMode.parse(
    Platform.environment['CBR_BENCH_MODE'] ?? 'collaborative',
  );
  final outPath =
      Platform.environment['CBR_BENCH_OUT'] ?? 'artifacts/bench/live.json';

  final missing = <String>[
    if (!File(kernelBin).existsSync()) 'kernel=$kernelBin',
    if (!File(pitDb).existsSync()) 'pit_db=$pitDb',
    if (baseUrl == null || token == null) 'ANTHROPIC_BASE_URL/TOKEN',
  ];
  if (missing.isNotEmpty) {
    test('真实链路 bench（环境缺失，跳过）', () {
      markTestSkipped('缺少：${missing.join(', ')}');
    });
    return;
  }

  test('真实链路：kernel 工具 + LLM 三角色 + R0–R5，$days 个时点（$mode）', () async {
    final workspace = p.join(Directory.systemTemp.path, 'cbr_live_bench.duckdb');
    final ws = File(workspace);
    if (ws.existsSync()) ws.deleteSync();
    File(pitDb).copySync(workspace);

    final prompts = PromptBuilder.fromTemplates({
      for (final name in const [
        'common_rules',
        'regulator',
        'investor',
        'financing',
        'cross_validation',
        'single_agent',
      ])
        name: File(
          p.join(root, 'apps/desktop/lib/agents/prompts/$name.md'),
        ).readAsStringSync(),
    });
    final catalog = RoleCatalog.parse(
      File(
        p.join(root, 'apps/desktop/lib/agents/roles/roles.json'),
      ).readAsStringSync(),
    );

    final supervisor = SidecarSupervisor(
      transportFactory: () => StdioSidecarTransport(
        executable: kernelBin,
        arguments: [
          '--workspace',
          workspace,
          '--data-home',
          Directory.systemTemp.path,
          '--resource-home',
          root,
          '--log-level',
          'warn',
        ],
      ),
      clientVersion: 'bench',
      contractVersion: '1.0.0',
      workspace: workspace,
      dataHome: Directory.systemTemp.path,
      resourceHome: root,
    );
    final audit = <AuditEvent>[];
    final invoker = GatedToolInvoker(
      client: supervisor,
      gate: PermissionGate(now: () => '2026-11-27T18:00:00+08:00'),
      auditSink: audit.add,
    );
    final registry = ToolRegistry(
      specs: catalog.specs,
      invoker: _GatedInvoker(invoker),
    );
    final signalSource = KernelSignalSource(supervisor);
    final generator = DeepSeekGenerator(
      secrets: _EnvSecrets({'DEEPSEEK_API_KEY': token!}),
      baseUrl: baseUrl!,
      model:
          Platform.environment['CBR_BENCH_MODEL'] ?? 'deepseek-v4.1-flash',
      // 推理型模型先烧 reasoning tokens；1200 会在出结论前耗尽。
      maxTokens: int.parse(
        Platform.environment['CBR_BENCH_MAX_TOKENS'] ?? '4000',
      ),
      // 思维链预算由厂商参数控制（各家字段名不同，故做成可注入映射）。
      extraBody: const {'reasoning_effort': 'low'},
    );

    final decisions = <DecisionCard>[];
    final settings = AgentSettings(
      catalog: catalog,
      prompts: prompts,
      registry: registry,
      generator: generator,
      judge: _NoJudge(),
      signalSource: signalSource.read,
      runHooks: RunHooks(onDecision: decisions.add),
    );
    final runtime = AgentRuntime(settings);

    final dates = _sampleDates(
      p.join(root, 'contracts/golden-vectors/cfsi_stress_pca_q90_reference.json'),
      days,
    );
    final records = <Map<String, Object?>>[];
    for (final date in dates) {
      final started = DateTime.now();
      RunSummary? summary;
      String? failure;
      final claims = <Map<String, Object?>>[];
      final conflicts = <String>[];
      await for (final event in runtime.run(
        question: '基于证据包评估 $date 的跨境金融压力，并给出三主体行动建议。',
        runId: 'bench-$date',
        asOf: DateTime.parse('${date}T10:00:00Z'),
        mode: mode,
      )) {
        switch (event) {
          case RunFinished(summary: final finished):
            summary = finished;
          case RunFailed(:final code, :final message):
            failure = '$code: $message';
          case ClaimProduced(
            :final kind,
            :final evidenceIds,
            :final claimId,
          ):
            claims.add({
              'claim_id': claimId,
              'kind': kind,
              'evidence_ids': evidenceIds,
            });
          case ConflictFound(:final category):
            conflicts.add(category);
          default:
            break;
        }
      }
      final decision = decisions.isEmpty ? null : decisions.last;
      records.add({
        'as_of': date,
        'ms': DateTime.now().difference(started).inMilliseconds,
        'risk': summary?.riskLevel,
        'failure': failure,
        'claims': claims,
        'conflicts': conflicts,
        'degraded': summary?.degradedRoles ?? const <String>[],
        'tokens': summary?.tokensUsed ?? 0,
        'partial': summary?.partial ?? true,
        'cost_usd': summary?.costUsd,
        'limitations': summary?.limitations ?? const <String>[],
        'evidence_ids': summary?.evidenceIds ?? const <String>[],
        'verification': decision == null
            ? null
            : {
                'passed': decision.verification.passed,
                'numeric_error_rate': decision.verification.numericErrorRate,
                'leakage_events': decision.verification.leakageEvents,
                'permission_violations':
                    decision.verification.permissionViolations,
                'claims_total': decision.verification.citationChecksTotal,
                'unsupported_claims': decision.verification.unsupportedClaims,
                'schema_errors': decision.verification.schemaErrors,
              },
        'evidence_kinds': decision == null
            ? const <String>[]
            : [
                for (final e in decision.evidence)
                  {'id': e.evidenceId, 'kind': e.kind.wire, 'as_of': e.asOf.toIso8601String().substring(0, 10), 'value': e.value, 'tool': e.tool?.name},
              ],
        'final_advice': decision?.finalAdvice,
      });
      // ignore: avoid_print
      print(
        '[${records.length}/${dates.length}] $date risk=${summary?.riskLevel ?? "-"} '
        'claims=${claims.length} ev=${summary?.evidenceIds.length ?? 0} '
        'degraded=${(summary?.degradedRoles ?? const []).join(",")} '
        '${DateTime.now().difference(started).inMilliseconds}ms'
        '${failure == null ? "" : " FAILED $failure"}',
      );
    }

    await supervisor.shutdown();

    final file = File(p.join(root, outPath));
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(
      const JsonEncoder.withIndent('  ').convert({
        'generated_at': DateTime.now().toUtc().toIso8601String(),
        'mode': mode.wire,
        'model': Platform.environment['CBR_BENCH_MODEL'] ?? 'deepseek-v4.1-flash',
        'kernel': kernelBin,
        'pit_db': pitDb,
        'n_runs': records.length,
        'records': records,
        'audit': [for (final e in audit) e.toJson()],
      }),
    );

    // 断言：至少一次成功研判，且没有任何泄漏事件。
    expect(records.where((r) => r['risk'] != null), isNotEmpty);
    for (final record in records) {
      final v = record['verification'] as Map<String, Object?>?;
      if (v != null) {
        expect(v['leakage_events'], 0, reason: '${record['as_of']} 出现 PIT 泄漏');
      }
    }
    // ignore: avoid_print
    print('已写入 $outPath');
  }, timeout: const Timeout(Duration(minutes: 30)));
}

/// 把 [GatedToolInvoker] 适配成 Agent 层 [ToolInvoker]。
final class _GatedInvoker implements ToolInvoker {
  _GatedInvoker(this._invoker);

  final GatedToolInvoker _invoker;

  @override
  Future<ToolInvocation> invoke({
    required String tool,
    required String asOf,
    required Map<String, Object?> params,
  }) async {
    final spec = ToolRegistry.specOf(tool);
    final role = (spec == null || spec.allowedRoles.isEmpty)
        ? 'unknown'
        : spec.allowedRoles.first;
    final outcome = await _invoker.invoke(
      role: role,
      tool: tool,
      params: params,
      asOf: asOf,
      idempotencyKey: '$tool-$asOf',
      confirmed: true,
    );
    return switch (outcome) {
      ToolCallSucceeded(:final evidence) => ToolInvocation(
        tool: evidence.tool,
        version: evidence.version,
        value: evidence.value,
        unit: evidence.unit,
        payload: evidence.params,
        title: evidence.title,
        summary: evidence.summary ?? '',
        data: evidence.data ?? const {},
        evidenceId: evidence.evidenceId,
        inputsHash: evidence.inputsHash,
        hash: evidence.hash,
      ),
      ToolCallDenied() => throw ToolUnavailable(tool, '角色越权，工具未执行'),
      ToolCallNeedsConfirmation() => throw ToolUnavailable(tool, '需要人工确认'),
      ToolCallFailed(:final message) => throw ToolUnavailable(tool, message),
    };
  }
}

/// 仓库根：`flutter test` 的 cwd 是 apps/desktop，向上找含 contracts/ 的目录。
String _repoRoot() {
  var dir = Directory.current;
  while (true) {
    if (Directory(p.join(dir.path, 'contracts')).existsSync()) {
      return dir.path;
    }
    final parent = dir.parent;
    if (parent.path == dir.path) {
      return Directory.current.path;
    }
    dir = parent;
  }
}

/// 从黄金向量取真实交易日（均匀抽样；与 docs/23 的真实 PIT 日历口径一致）。
List<String> _sampleDates(String goldenPath, int count) {
  final golden =
      jsonDecode(File(goldenPath).readAsStringSync()) as Map<String, Object?>;
  final dates = [
    for (final row in (golden['rows'] as List).cast<Map<String, Object?>>())
      if (row['cfsi'] != null) row['date'] as String,
  ];
  if (count >= dates.length) {
    return dates;
  }
  // 默认取最近 [count] 个交易日（早期年份多条序列无观测，工具会如实报「无证据」）。
  final offset = int.parse(Platform.environment['CBR_BENCH_OFFSET'] ?? '0');
  final end = dates.length - offset;
  return dates.sublist((end - count).clamp(0, dates.length), end);
}
