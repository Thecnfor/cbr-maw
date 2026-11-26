// CBR-MAW 基准测试入口（docs/23 协议）。
//
//   dart run tools/bench/run.dart                              # 全量
//   dart run tools/bench/run.dart --as-of 2026-10-28 --windows 40,60,90
//   dart run tools/bench/run.dart --out artifacts/bench/run.json
//   dart run tools/bench/run.dart --skip-jev --skip-b          # 只跑确定性臂
//
// 职责：解析参数 → 调 Python 分析层（统计用现成库）→ 汇总成一份 JSON →
// 打印人类可读摘要。所有数字来自真实 PIT 库，脚本不做任何补数。
//
// 依赖：Python 解释器（默认 ~/.cache/cbr-venv/bin/python，可用 CBR_PYTHON 覆盖）。
// 退出码：0 = 主流程跑通；2 = 数据/解释器缺失；3 = 自检失败。
// ignore_for_file: avoid_print
import 'dart:io';

import 'package:path/path.dart' as p;

import '../src/repo.dart';

Future<void> main(List<String> args) async {
  final root = repoRoot();
  final python =
      Platform.environment['CBR_PYTHON'] ??
      p.join(Platform.environment['HOME'] ?? '', '.cache/cbr-venv/bin/python');
  if (!File(python).existsSync()) {
    stderr.writeln('找不到 Python 解释器：$python（用 CBR_PYTHON 覆盖）');
    exit(2);
  }
  final script = p.join(root.path, 'tools/bench/analysis/arms.py');
  if (!File(script).existsSync()) {
    stderr.writeln('缺少分析脚本：$script');
    exit(2);
  }
  final out = _arg(args, '--out');
  final tmp = out ?? p.join(Directory.systemTemp.path, 'cbr_bench_run.json');

  final cmd = <String>[
    python,
    script,
    if (_arg(args, '--as-of') != null) ...['--as-of', _arg(args, '--as-of')!],
    if (_arg(args, '--windows') != null) ...[
      '--windows',
      _arg(args, '--windows')!,
    ],
    if (_arg(args, '--jev-days') != null) ...[
      '--jev-days',
      _arg(args, '--jev-days')!,
    ],
    if (args.contains('--skip-jev')) '--skip-jev',
    if (args.contains('--skip-b')) '--skip-b',
    '--out',
    tmp,
  ];

  final proc = await Process.start(
    cmd.first,
    cmd.sublist(1),
    workingDirectory: root.path,
    environment: {'CBR_PYTHON': python},
    mode: ProcessStartMode.inheritStdio,
  );
  final code = await proc.exitCode;
  if (code != 0) {
    stderr.writeln('分析层退出码 $code');
    exit(code == 3 ? 3 : 2);
  }

  final report = readJsonObject(tmp);
  final selfOk = _selfCheck(report);
  if (!selfOk) {
    stderr.writeln('自检失败：安慰剂未回落到 1.0±0.2，或确定性臂缺少 walk-forward。');
    exit(3);
  }
  _print(report);
  if (out == null) {
    File(tmp).deleteSync();
  } else {
    print('\n报告已写入 $tmp');
  }
  exit(0);
}

String? _arg(List<String> args, String name) {
  final i = args.indexOf(name);
  if (i < 0 || i + 1 >= args.length) {
    return null;
  }
  return args[i + 1];
}

/// 自检：检测器本身不能空转。
bool _selfCheck(Map<String, Object?> report) {
  final arms = report['arms'] as Map<String, Object?>?;
  if (arms == null) {
    return false;
  }
  for (final key in ['C', 'D']) {
    final arm = arms[key] as Map<String, Object?>?;
    if (arm == null || arm['status'] != 'ok') {
      return false;
    }
    final placebo = arm['placebo'] as Map<String, Object?>?;
    if (placebo == null || placebo['pass'] != true) {
      return false;
    }
    final wf = arm['walk_forward'] as Map<String, Object?>?;
    if (wf == null || wf['rows'] == null) {
      return false;
    }
  }
  return true;
}

String _f(Object? v, [int digits = 4]) {
  if (v == null) {
    return 'n/a';
  }
  if (v is double) {
    return v.toStringAsFixed(digits);
  }
  return v.toString();
}

void _print(Map<String, Object?> report) {
  final data = report['data'] as Map<String, Object?>;
  print('CBR-MAW 基准（真实 PIT 库，无合成数值）');
  print(
    '  as_of=${report['as_of']}  日历 ${data['calendar_start']}→'
    '${data['calendar_end']}（${data['n_days']} 天）',
  );
  print(
    '  序列 ${data['n_series']} / 高压日 ${data['n_high_stress_days']} / '
    '压力窗口 ${data['n_stress_windows']} / train_end=${data['train_end']}',
  );
  print('');

  final arms = report['arms'] as Map<String, Object?>;
  for (final key in ['A', 'A_prime_jev', 'B', 'C', 'D']) {
    final arm = arms[key] as Map<String, Object?>?;
    if (arm == null) {
      continue;
    }
    if (arm['status'] == 'blocked') {
      print('  $key: BLOCKED — ${arm['reason']}');
      continue;
    }
    if (key == 'A_prime_jev') {
      print(
        '  A′ JEV 裁判：n=${arm['n']} precision=${_f(arm['precision'])} '
        'recall=${_f(arm['recall'])} lift=${_f(arm['lift'])} '
        '（${_f(arm['latency_s_total'], 1)}s / ${arm['tokens']}）',
      );
      continue;
    }
    final oos = arm['oos'] as Map<String, Object?>;
    print(
      '  $key ${arm['name'] ?? ''}: precision=${_f(oos['precision'])} '
      'recall=${_f(oos['recall'])} f1=${_f(oos['f1'])} '
      'lift=${_f(oos['lift'])} 触发率=${_f(oos['trigger_rate'], 3)} '
      '(tp=${oos['tp']} fp=${oos['fp']} fn=${oos['fn']} n=${oos['n']})',
    );
    final wf = arm['walk_forward'] as Map<String, Object?>?;
    if (wf != null) {
      final rows = (wf['rows'] as List).cast<Map<String, Object?>>();
      print(
        '     walk-forward: '
        '${rows.map((r) => "${r['year']}:${_f(r['lift'], 2)}").join(' ')}',
      );
      print(
        '     逐年平均 lift=${_f(wf['mean_lift'])} '
        '有效 ${wf['valid_years']}/${wf['evaluable_years']}',
      );
    }
    final placebo = arm['placebo'] as Map<String, Object?>?;
    if (placebo != null) {
      print(
        '     安慰剂 mean=${_f(placebo['placebo_mean_lift'], 3)} '
        'p=${_f(placebo['p_value_one_sided'], 4)}',
      );
    }
    final lp = arm['lead_profile'] as Map<String, Object?>?;
    if (lp != null) {
      print('     lead_profile 峰值 h=${lp['peak_h']}（${lp['type']}）');
    }
  }

  final abl = report['ablation'] as Map<String, Object?>?;
  if (abl != null) {
    print('');
    print(
      '  消融 C−D：Δprecision=${_f(abl['delta_precision'])} '
      'Δlift=${_f(abl['delta_lift'])} Δf1=${_f(abl['delta_f1'])} '
      'McNemar p=${_f((abl['mcnemar'] as Map)['p_value'])} '
      '→ ${abl['verdict']}',
    );
  }

  final lv = report['level_vs_returns'] as Map<String, Object?>?;
  if (lv != null) {
    final r = lv['returns'] as Map<String, Object?>;
    final l = lv['levels'] as Map<String, Object?>;
    print(
      '  水平 vs 变化率：变化率 ratio=${_f(r['ratio'], 3)} '
      '(p=${_f(r['perm_p_one_sided'], 4)}) / '
      '水平 ratio=${_f(l['ratio'], 3)} (p=${_f(l['perm_p_one_sided'], 4)})',
    );
  }

  final lc = report['label_circularity'] as Map<String, Object?>?;
  if (lc != null) {
    final loose = lc['cfsi_rule_on_y20'] as Map<String, Object?>;
    final strict = lc['cfsi_rule_on_y_strict'] as Map<String, Object?>;
    print(
      '  标签循环性：CFSI 规则 lift 含当日=${_f(loose['lift'], 3)} / '
      '严格未来=${_f(strict['lift'], 3)}',
    );
  }

  final st = report['structure'] as Map<String, Object?>?;
  if (st != null) {
    final dom = st['dominant_dim'] as Map<String, Object?>;
    final stage = st['stage_signal'] as Map<String, Object?>;
    print(
      '  结构：dominant_dim 命中 ${dom['hits']}/${dom['n_windows']}'
      '（随机 1/6）; 阶段信号 ${_f(stage['conditional_rate'], 3)} vs '
      '无条件 ${_f(stage['unconditional_rate'], 3)}',
    );
  }
}
