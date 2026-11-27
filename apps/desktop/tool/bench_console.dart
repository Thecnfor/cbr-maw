/// 终端基准控制台：真跑四臂，并把 R0–R5 的每一步流式打到终端。
///
/// 用法（仓库根）：
/// ```
/// dart run apps/desktop/tool/bench_console.dart \
///   --pairs 30 --arms collaborative,single,independent \
///   --out artifacts/bench/console.json
/// ```
///
/// 设计约束（docs/24 §D15）：
/// - **不伪造**：缺 kernel / 生成端点 / PIT 库时直接退出并说明缺什么；
/// - **可复现**：日期抽样按压力/平静配对 + 固定种子，种子与抽样结果写入产物；
/// - **可评分**：产物结构对齐 `tools/bench/analysis/score_arms.py`
///   （`records[].arms.<arm>.{risk,ms,tokens}`）。
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:cbr_maw/agents/investigation_controller.dart';
import 'package:cbr_maw/agents/llm/llm_channel.dart';
import 'package:cbr_maw/agents/memory/memory_store.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw/agents/orchestrator/mode_flags.dart';
import 'package:cbr_maw/agents/roles/asset_source.dart';
import 'package:cbr_maw/agents/roles/prompt_builder.dart';
import 'package:cbr_maw/agents/roles/role_config.dart';
import 'package:cbr_maw/agents/run_events.dart';
import 'package:cbr_maw/agents/signals/kernel_signal_source.dart';
import 'package:cbr_maw/agents/tools/tool_registry.dart';
import 'package:cbr_maw/data/gate/permission_gate.dart';
import 'package:cbr_maw/data/gate/tool_invoker.dart';
import 'package:cbr_maw/data/sidecar/sidecar_supervisor.dart';
import 'package:cbr_maw/data/sidecar/stdio_transport.dart';
import 'package:path/path.dart' as p;

Future<void> main(List<String> argv) async {
  final args = _Args.parse(argv);
  final root = args.root;
  final kernelBin =
      args.kernel ?? p.join(root, 'services/kernel/target/debug/cbr-kernel');
  final pitDb =
      args.pitDb ?? '/mnt/shared/recently/commorcial/data/pit_real.duckdb';
  final missing = <String>[
    if (!File(kernelBin).existsSync()) 'kernel=$kernelBin（先跑 cargo build）',
    if (!File(pitDb).existsSync()) 'pit_db=$pitDb',
    if (args.baseUrl == null || args.key == null)
      '--base-url/--key 或 CBR_API_BASE/DEEPSEEK_API_KEY',
  ];
  if (missing.isNotEmpty) {
    stderr.writeln('无法开跑，缺少：\n  - ${missing.join('\n  - ')}');
    exit(2);
  }

  final styles = _Style(useColor: args.color && stdout.hasTerminal);
  var dates = _samplePairedDates(
    p.join(root, 'contracts/golden-vectors/cfsi_stress_pca_q90_reference.json'),
    pairs: args.pairs,
    seed: args.seed,
  );
  // 抽样完整性先校验（分片之前）：分片只是切分同一份抽样。
  if (dates.length < args.pairs * 2) {
    stderr.writeln('可评分时点不足：需要 ${args.pairs * 2}，实得 ${dates.length}');
    exit(2);
  }
  if (args.shards > 1) {
    dates = [
      for (var i = 0; i < dates.length; i++)
        if (i % args.shards == args.shard) dates[i],
    ];
    if (dates.isEmpty) {
      stderr.writeln('分片 ${args.shard}/${args.shards} 没有得到任何时点');
      exit(2);
    }
  }

  final workspace = p.join(
    Directory.systemTemp.path,
    'cbr_console_${DateTime.now().millisecondsSinceEpoch}.duckdb',
  );
  File(pitDb).copySync(workspace);

  // agents 的资源路径按应用包根解析（lib/agents/...）。
  final assets = FileAssetSource(p.join(root, 'apps/desktop'));
  final catalog = await RoleCatalog.load(assets);
  final prompts = await PromptBuilder.load(assets);
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
        '--model-dir',
        args.modelDir,
        '--log-level',
        'warn',
      ],
    ),
    clientVersion: 'bench-console',
    contractVersion: '1.0.0',
    workspace: workspace,
    dataHome: Directory.systemTemp.path,
    resourceHome: root,
  );
  final invoker = GatedToolInvoker(
    client: supervisor,
    gate: PermissionGate(now: () => DateTime.now().toUtc().toIso8601String()),
    auditSink: (_) {},
  );
  final registry = ToolRegistry(
    specs: catalog.specs,
    invoker: _GatedInvoker(invoker),
  );
  final generator = DeepSeekGenerator(
    secrets: _EnvSecrets({'DEEPSEEK_API_KEY': args.key!}),
    baseUrl: args.baseUrl!,
    model: args.model,
    maxTokens: args.maxTokens,
    extraBody: const {'reasoning_effort': 'low'},
  );

  stdout.writeln(styles.title('CBR-MAW bench console'));
  stdout.writeln('  端点   ${args.baseUrl}  model=${args.model}');
  stdout.writeln('  kernel $kernelBin');
  stdout.writeln(
    '  时点   ${dates.length}（压力 ${dates.where((d) => d.pressure).length} / 平静 ${dates.where((d) => !d.pressure).length}，seed=${args.seed}）',
  );
  stdout.writeln('  臂     ${args.arms.join(', ')}\n');

  final records = <Map<String, Object?>>[];
  final startedAll = DateTime.now();
  var index = 0;
  for (final day in dates) {
    index++;
    final armResults = <String, Object?>{};
    for (final arm in args.arms) {
      final started = DateTime.now();
      final decisions = <DecisionCard>[];
      final settings = AgentSettings(
        catalog: catalog,
        prompts: prompts,
        registry: registry,
        generator: generator,
        judge: _NoJudge(),
        signalSource: KernelSignalSource(supervisor).read,
        memory: args.memory ? SidecarMemoryStore(supervisor) : null,
        runHooks: RunHooks(onDecision: decisions.add),
      );
      final runtime = AgentRuntime(settings);
      RunSummary? summary;
      String? failure;
      final claims = <Map<String, Object?>>[];
      final conflicts = <String>[];

      stdout.writeln(
        styles.header(
          '━ [$index/${dates.length}] ${day.date} '
          '${day.pressure ? "压力" : "平静"} · 臂 $arm',
        ),
      );
      await for (final event in runtime.run(
        question: '基于证据包评估 ${day.date} 的跨境金融压力，并给出三主体行动建议。',
        runId: 'bench-${day.date}-$arm',
        asOf: DateTime.parse('${day.date}T10:00:00Z'),
        mode: CollaborationMode.parse(arm),
      )) {
        switch (event) {
          case RunFinished(summary: final finished):
            summary = finished;
          case RunFailed(:final code, :final message):
            failure = '$code: $message';
            stdout.writeln(styles.warn('  ✗ 失败 $failure'));
          case ClaimProduced(
            :final kind,
            :final text,
            :final claimId,
            :final evidenceIds,
          ):
            claims.add({
              'claim_id': claimId,
              'kind': kind,
              'evidence_ids': evidenceIds,
            });
            stdout.writeln(
              '  ├ 主张[$kind] ${_clip(text)}  ← 证据 ${evidenceIds.length}',
            );
          case ConflictFound(:final category, :final details, :final escalated):
            conflicts.add(category);
            stdout.writeln(
              '  ├ 冲突[$category]${escalated ? " ⚠升级人工" : ""} ${_clip(jsonEncode(details))}',
            );
          case ToolInvoked(:final tool, :final denied, :final result):
            stdout.writeln(
              denied
                  ? styles.warn('  ├ 工具 $tool 被拒（越权/未确认）')
                  : '  ├ 工具 $tool → ${_clip(jsonEncode(result))}',
            );
          case AgentActivity(:final agentRole, :final action, :final detail):
            stdout.writeln(
              '  ├ [$agentRole] $action ${_clip(jsonEncode(detail))}',
            );
          case RunStarted():
            break;
        }
      }
      final ms = DateTime.now().difference(started).inMilliseconds;
      final decision = decisions.isEmpty ? null : decisions.last;
      armResults[arm] = {
        'risk': summary?.riskLevel,
        'ms': ms,
        'tokens': summary?.tokensUsed ?? 0,
        'partial': summary?.partial ?? true,
        'claims': claims,
        'conflicts': conflicts,
        'degraded': summary?.degradedRoles ?? const <String>[],
        'failure': failure,
        'verification': decision == null
            ? null
            : {
                'passed': decision.verification.passed,
                'numeric_error_rate': decision.verification.numericErrorRate,
                'leakage_events': decision.verification.leakageEvents,
                'unsupported_claims': decision.verification.unsupportedClaims,
              },
      };
      stdout.writeln(
        styles.result(
          '  └ → ${summary?.riskLevel ?? "-"}  ${(ms / 1000).toStringAsFixed(1)}s  '
          'token=${summary?.tokensUsed ?? 0}  '
          '核验=${decision?.verification.passed ?? false ? "通过" : "未通过"}',
        ),
      );
    }
    records.add({'as_of': day.date, 'y20': day.label, 'arms': armResults});
    _writeOut(args.out, records, args, dates, startedAll);
  }

  await supervisor.shutdown();
  _writeOut(args.out, records, args, dates, startedAll);
  stdout.writeln(
    styles.title(
      '\n完成 ${records.length} 个时点 × ${args.arms.length} 臂 → ${args.out}',
    ),
  );
  stdout.writeln(
    '评分：~/.cache/cbr-venv/bin/python tools/bench/analysis/score_arms.py ${args.out}',
  );
}

void _writeOut(
  String path,
  List<Map<String, Object?>> records,
  _Args args,
  List<_Day> dates,
  DateTime started,
) {
  final file = File(path);
  file.parent.createSync(recursive: true);
  file.writeAsStringSync(
    const JsonEncoder.withIndent('  ').convert({
      'generated_at': DateTime.now().toUtc().toIso8601String(),
      'elapsed_s': DateTime.now().difference(started).inSeconds,
      'model': args.model,
      'base_url': args.baseUrl,
      'arms': args.arms,
      'sampling': {
        'seed': args.seed,
        'pairs': args.pairs,
        'dates': [
          for (final d in dates)
            {'as_of': d.date, 'pressure': d.pressure, 'y20': d.label},
        ],
      },
      'n_runs': records.length,
      'records': records,
    }),
  );
}

/// 压力/平静配对抽样：各自内部按时间均匀取，种子固定。
List<_Day> _samplePairedDates(
  String goldenPath, {
  required int pairs,
  required int seed,
}) {
  final golden =
      jsonDecode(File(goldenPath).readAsStringSync()) as Map<String, Object?>;
  final rows = (golden['rows'] as List).cast<Map<String, Object?>>();
  final scored = <_Day>[
    for (final row in rows)
      if (row['y_20'] != null)
        _Day(
          date: row['date']! as String,
          pressure: row['y_20'] == 1,
          label: row['y_20']! as int,
        ),
  ];
  final pressure = scored.where((d) => d.pressure).toList();
  final calm = scored.where((d) => !d.pressure).toList();
  final rng = Random(seed);
  List<_Day> pick(List<_Day> pool, int n) {
    if (pool.length <= n) {
      return [...pool];
    }
    // 均匀分桶后每桶随机取一个，避免抽样扎堆。
    final out = <_Day>[];
    final bucket = pool.length / n;
    for (var i = 0; i < n; i++) {
      final lo = (i * bucket).floor();
      final hi = min(pool.length, ((i + 1) * bucket).ceil());
      out.add(pool[lo + rng.nextInt(hi - lo)]);
    }
    return out;
  }

  final picked = [...pick(pressure, pairs), ...pick(calm, pairs)]
    ..sort((a, b) => a.date.compareTo(b.date));
  return picked;
}

String _clip(String text, [int max = 120]) {
  final oneLine = text.replaceAll('\n', ' ');
  return oneLine.length <= max ? oneLine : '${oneLine.substring(0, max)}…';
}

final class _Day {
  const _Day({required this.date, required this.pressure, required this.label});
  final String date;
  final bool pressure;
  final int label;
}

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
  }) => throw UnsupportedError('bench console 不调用裁判');
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

final class _Args {
  _Args({
    required this.root,
    required this.arms,
    required this.pairs,
    required this.out,
    required this.model,
    required this.baseUrl,
    required this.key,
    required this.seed,
    required this.maxTokens,
    required this.kernel,
    required this.pitDb,
    required this.color,
    required this.modelDir,
    required this.memory,
    required this.shard,
    required this.shards,
  });

  final String root;
  final List<String> arms;
  final int pairs;
  final String out;
  final String model;
  final String? baseUrl;
  final String? key;
  final int seed;
  final int maxTokens;
  final String? kernel;
  final String? pitDb;
  final bool color;
  final String modelDir;
  final bool memory;
  final int shard;
  final int shards;

  static _Args parse(List<String> argv) {
    final opts = <String, String>{};
    for (var i = 0; i < argv.length; i++) {
      final arg = argv[i];
      if (!arg.startsWith('--')) {
        continue;
      }
      final key = arg.substring(2);
      final value = (i + 1 < argv.length && !argv[i + 1].startsWith('--'))
          ? argv[++i]
          : 'true';
      opts[key] = value;
    }
    final env = Platform.environment;
    return _Args(
      root: opts['root'] ?? _repoRoot(),
      arms: (opts['arms'] ?? 'collaborative,single,independent').split(','),
      pairs: int.parse(opts['pairs'] ?? '30'),
      out: opts['out'] ?? 'artifacts/bench/console.json',
      model: opts['model'] ?? env['DEEPSEEK_MODEL'] ?? 'deepseek-v4.1-flash',
      baseUrl:
          opts['base-url'] ?? env['CBR_API_BASE'] ?? env['DEEPSEEK_BASE_URL'],
      key: opts['key'] ?? env['DEEPSEEK_API_KEY'],
      seed: int.parse(opts['seed'] ?? '11'),
      maxTokens: int.parse(opts['max-tokens'] ?? '8000'),
      kernel: opts['kernel'],
      pitDb: opts['pit-db'],
      color: opts['no-color'] == null,
      modelDir:
          opts['model-dir'] ??
          p.join(opts['root'] ?? _repoRoot(), '.cache/models'),
      memory: opts['no-memory'] == null,
      shard: int.parse(opts['shard'] ?? '0'),
      shards: int.parse(opts['shards'] ?? '1'),
    );
  }

  static String _repoRoot() {
    var dir = Directory.current;
    for (var i = 0; i < 6; i++) {
      if (Directory(p.join(dir.path, 'contracts')).existsSync()) {
        return dir.path;
      }
      final parent = dir.parent;
      if (parent.path == dir.path) {
        break;
      }
      dir = parent;
    }
    return Directory.current.path;
  }
}

final class _Style {
  const _Style({required this.useColor});
  final bool useColor;

  String _wrap(String code, String text) =>
      useColor ? '\x1b[${code}m$text\x1b[0m' : text;

  String title(String text) => _wrap('1;36', text);
  String header(String text) => _wrap('1;33', text);
  String result(String text) => _wrap('1;32', text);
  String warn(String text) => _wrap('1;31', text);
}
