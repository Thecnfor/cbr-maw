// 多臂对照 bench：同一批真实时点上跑多种协作模式 + A 组（纯 LLM 直答）。
//
// 目的（docs/23 §2、§4、§6）：让「多智能体协同到底比单模型好在哪」可被证伪。
// 四组对照在**同一批时点**上运行，配对比较可用 McNemar。
//
//   A  · 纯 LLM 直答：只给数值面板 + 问题，无工具、无证据链、无多角色、
//       **无 PIT 过滤**（按用户实际可得的最新数据回答）→ 模拟「别人怎么做」
//   S  · single：单通用 agent 依次完成三主体任务
//   I  · independent：三主体独立决策，不共享证据、不交叉验证、不协调
//   C  · collaborative：完整 R0–R5 协同核验
//
// 运行（仓库根）：
//   CBR_BENCH_DAYS=12 CBR_BENCH_OUT=artifacts/bench/arms_live.json \
//   flutter test -d flutter-tester apps/desktop/integration_test/live_arms_test.dart
//
// 环境依赖（缺一即整组 skip，绝不伪造）：
//   kernel 可执行体（CBR_KERNEL_BIN）、真实 PIT 库（CBR_PIT_DB）、
//   生成端（ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN）。
import 'dart:convert';
import 'dart:io';

import 'package:cbr_maw/agents/investigation_controller.dart';
import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw/agents/orchestrator/mode_flags.dart';
import 'package:cbr_maw/agents/roles/prompt_builder.dart';
import 'package:cbr_maw/agents/roles/role_config.dart';
import 'package:cbr_maw/agents/run_events.dart';
import 'package:cbr_maw/agents/signals/kernel_signal_source.dart';
import 'package:cbr_maw/agents/tools/tool_registry.dart';
import 'package:cbr_maw/data/gate/permission_gate.dart';
import 'package:cbr_maw/data/gate/tool_invoker.dart';
import 'package:cbr_maw/data/sidecar/sidecar_supervisor.dart';
import 'package:cbr_maw/data/sidecar/stdio_transport.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;

final class _EnvSecrets implements SecretProvider {
  _EnvSecrets(this.values);

  final Map<String, String> values;

  @override
  Future<String?> read(String key) async => values[key];
}

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
  final days = int.parse(Platform.environment['CBR_BENCH_DAYS'] ?? '8');
  final outPath =
      Platform.environment['CBR_BENCH_OUT'] ?? 'artifacts/bench/arms_live.json';

  final missing = <String>[
    if (!File(kernelBin).existsSync()) 'kernel=$kernelBin',
    if (!File(pitDb).existsSync()) 'pit_db=$pitDb',
    if (baseUrl == null || token == null) 'ANTHROPIC_BASE_URL/TOKEN',
  ];
  if (missing.isNotEmpty) {
    test('多臂对照 bench（环境缺失，跳过）', () {
      markTestSkipped('缺少：${missing.join(', ')}');
    });
    return;
  }

  test('多臂对照：$days 个真实时点 × {A, S, I, C}', () async {
    final workspace = p.join(Directory.systemTemp.path, 'cbr_arms_bench.duckdb');
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
      File(p.join(root, 'apps/desktop/lib/agents/roles/roles.json'))
          .readAsStringSync(),
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
    final generator = DeepSeekGenerator(
      secrets: _EnvSecrets({'DEEPSEEK_API_KEY': token!}),
      baseUrl: baseUrl!,
      model: Platform.environment['CBR_BENCH_MODEL'] ?? 'deepseek-v4.1-flash',
      maxTokens: int.parse(
        Platform.environment['CBR_BENCH_MAX_TOKENS'] ?? '4000',
      ),
      extraBody: const {'reasoning_effort': 'low'},
    );

    final decisions = <DecisionCard>[];
    final settings = AgentSettings(
      catalog: catalog,
      prompts: prompts,
      registry: registry,
      generator: generator,
      judge: _NoJudge(),
      signalSource: KernelSignalSource(supervisor).read,
      runHooks: RunHooks(onDecision: decisions.add),
    );
    final runtime = AgentRuntime(settings);

    final dates = _sampleDates(
      p.join(
        root,
        'contracts/golden-vectors/cfsi_stress_pca_q90_reference.json',
      ),
      days,
    );
    final records = <Map<String, Object?>>[];
    for (final date in dates) {
      final asOf = DateTime.parse('${date}T10:00:00Z');
      final arms = <String, Map<String, Object?>>{};

      // A 组：纯 LLM 直答（无工具 / 无证据链 / 无 PIT 过滤）。
      arms['A'] = await _runArmA(
        generator: generator,
        supervisor: supervisor,
        date: date,
        asOf: asOf,
      );

      for (final mode in const [
        CollaborationMode.single,
        CollaborationMode.independent,
        CollaborationMode.collaborative,
      ]) {
        decisions.clear();
        final started = DateTime.now();
        RunSummary? summary;
        String? failure;
        var conflicts = 0;
        await for (final event in runtime.run(
          question: '基于证据包评估 $date 的跨境金融压力，并给出三主体行动建议。',
          runId: 'bench-${mode.wire}-$date',
          asOf: asOf,
          mode: mode,
        )) {
          switch (event) {
            case RunFinished(summary: final finished):
              summary = finished;
            case RunFailed(:final code, :final message):
              failure = '$code: $message';
            case ConflictFound():
              conflicts++;
            default:
              break;
          }
        }
        final decision = decisions.isEmpty ? null : decisions.last;
        arms[mode.wire] = {
          'risk': summary?.riskLevel,
          'failure': failure,
          'ms': DateTime.now().difference(started).inMilliseconds,
          'tokens': summary?.tokensUsed ?? 0,
          'claims': decision?.cards.fold<int>(
                0,
                (a, c) => a + c.claims.length,
              ) ??
              0,
          'conflicts': conflicts,
          'degraded': summary?.degradedRoles ?? const <String>[],
          'partial': summary?.partial ?? true,
          'numeric_mismatches': decision?.numericMismatches ?? 0,
          'llm_assessments': decision == null
              ? const <String, Object?>{}
              : {
                  for (final entry in decision.llmAssessments.entries)
                    entry.key.wire: entry.value.wire,
                },
          'leakage_events':
              decision?.verification.leakageEvents ?? 0,
          'permission_violations':
              decision?.verification.permissionViolations ?? 0,
          'unsupported_claims':
              decision?.verification.unsupportedClaims ?? 0,
        };
      }
      records.add({'as_of': date, 'arms': arms});
      // ignore: avoid_print
      print(
        '[${records.length}/${dates.length}] $date '
        '${arms.entries.map((e) => '${e.key}=${e.value['risk'] ?? '-'}').join(' ')}',
      );
    }

    await supervisor.shutdown();
    final file = File(p.join(root, outPath));
    file.parent.createSync(recursive: true);
    file.writeAsStringSync(
      const JsonEncoder.withIndent('  ').convert({
        'generated_at': DateTime.now().toUtc().toIso8601String(),
        'model': Platform.environment['CBR_BENCH_MODEL'] ?? 'deepseek-v4.1-flash',
        'kernel': kernelBin,
        'pit_db': pitDb,
        'n_days': records.length,
        'records': records,
      }),
    );
    // ignore: avoid_print
    print('已写入 $outPath');
  }, timeout: const Timeout(Duration(minutes: 120)));
}

/// A 组：只把数值面板 + 问题给 LLM，无工具、无证据链、无多角色。
///
/// **无 PIT 过滤**是这一组的定义性特征：按用户实际可得的「最新数据」回答。
/// 回放历史时点时会用上未来数据——这正是要量化的泄漏量（docs/23 §2）。
///
/// 面板直接取 PIT 序列的原始读数（不做任何工具计算）：对照组若拿到工具
/// 读数，就等于白送了我们的确定性计算能力，比较不再公平。
Future<Map<String, Object?>> _runArmA({
  required TextGenerator generator,
  required SidecarClient supervisor,
  required String date,
  required DateTime asOf,
}) async {
  final started = DateTime.now();
  final panel = <String, Object?>{};
  final stale = <String, String>{};
  for (final series in _panelSeries) {
    // 故意不带 as_of 约束 + 降序：取该序列「最新」读数（A 组的定义性特征）。
    final results = await supervisor
        .send('db.query', {
          'view': 'pit_observations',
          'as_of': '2099-12-31',
          'filters': {'series_id': series},
          'limit': 1,
          'order': 'desc',
        })
        .toList();
    final result = results.single;
    if (result case Success(:final value)) {
      final rows = value is Map<String, Object?>
          ? (value['rows'] as List?) ?? const []
          : const [];
      if (rows.isNotEmpty && rows.first is Map) {
        final row = (rows.first as Map).cast<String, Object?>();
        panel[series] = row['value'];
        final day = row['obs_date']?.toString() ?? '';
        if (day.isNotEmpty && day.compareTo(date) > 0) {
          stale[series] = day; // 晚于评估时点 → 未来数据
        }
      }
    }
  }
  try {
    final response = await generator.generateJson(
      system: '你是一个跨境金融风险分析师。只输出 JSON。',
      user:
          '以下是当前的跨境金融市场数据面板（序列 → 最新读数）：\n'
          '${jsonEncode(panel)}\n\n'
          '问题：$date 这一天之后 20 个交易日内，跨境金融压力是否进入高压力区'
          '（high_stress）？请只输出 JSON：'
          '{"risk_level_assessment":"low|medium|high|critical",'
          '"high_stress_probability":0.0-1.0,"reason":"一句话依据"}',
      purpose: 'arm:A',
    );
    return {
      'risk': response.json['risk_level_assessment'],
      'probability': response.json['high_stress_probability'],
      'reason': response.json['reason'],
      'ms': DateTime.now().difference(started).inMilliseconds,
      'tokens': response.usage.total,
      'panel_series': panel.length,
      // A 组在历史时点上拿到晚于该时点的数据 = 结构性泄漏。
      'future_data_series': stale,
    };
  } on LlmFailure catch (failure) {
    return {
      'risk': null,
      'failure': '${failure.code.wire}: ${failure.message}',
      'ms': DateTime.now().difference(started).inMilliseconds,
    };
  }
}

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

/// 仓库根：向上找含 contracts/ 的目录。
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

/// 取**压力/平静配对**的可评分时点（docs/23 §4、ADR-010 评估闭环）。
///
/// - 只取 `y_20 != null` 的日期：y_20 是「未来 20 交易日」标签，末尾 19 行
///   天然为空；用末尾时点评分会把所有臂都算成负例，整张主表失去意义。
/// - 压力/平静各半：只测平静期会让所有臂都「正确」，只测压力期会让所有臂
///   都「过警」，都无法区分协同与不协同。
/// - 配对后再按时间均匀抽取，保证两组的日历分布相近。
List<String> _sampleDates(String goldenPath, int count) {
  final golden =
      jsonDecode(File(goldenPath).readAsStringSync()) as Map<String, Object?>;
  final stress = <String>[];
  final calm = <String>[];
  for (final row in (golden['rows'] as List).cast<Map<String, Object?>>()) {
    if (row['cfsi'] == null || row['y_20'] == null) continue;
    final date = row['date'] as String;
    if (row['y_20'] == 1) {
      stress.add(date);
    } else {
      calm.add(date);
    }
  }
  final half = (count / 2).ceil();
  return [
    ..._evenly(stress, half),
    ..._evenly(calm, count - half),
  ]..sort();
}

/// 从升序列表里均匀取 [count] 个（取尾部：越近的样本越贴近当前市场结构）。
List<String> _evenly(List<String> sorted, int count) {
  if (count <= 0) return const [];
  if (count >= sorted.length) return sorted;
  final step = sorted.length / count;
  return [
    for (var i = 0; i < count; i++)
      sorted[sorted.length - 1 - ((count - 1 - i) * step).round()],
  ];
}

/// A 组面板的序列集合（只取原始行情/资金序列，不含任何派生指标）。
const List<String> _panelSeries = <String>[
  'market.cn_equity.csi300',
  'market.cn_equity.csi500',
  'market.global.sp500',
  'market.global.vix',
  'market.global.us10y',
  'market.cn_bond.cgb_10y',
  'market.cn_bond.term_spread',
  'market.global.cn_us_spread',
  'market.fx.usdcny',
  'crossborder.flows.northbound_net',
  'crossborder.flows.ah_premium',
];
