/// 增量信息检验（docs/10 MT-07、docs/23 §4/§7、docs/17 §4.3）。
///
/// 回答一个**可证伪**的问题：在已有特征之上加一组新特征，样本外预测是否真的变好。
/// 三道关：
/// 1. `ΔR²_OS > 0`（Campbell–Thompson 扩展窗口，扩展模型的 OOS R² 高于基线）；
/// 2. Diebold–Mariano 检验基线/扩展的逐点平方误差差异，再经 Holm 多重比较校正；
/// 3. **强制安慰剂**：把新增特征按时间打乱后重算，若仍显著则结论作废
///    （docs/23 §7 第 3 条；docs/17 §4.3 的构造性负相关教训）。
///
/// 纯函数 + 显式注入随机源；输入输出均可序列化，供 bench 调用。
library;

import 'dart:math' as math;

import 'statistics.dart';

/// 一条候选新增特征块的检验结果。
final class IncrementalityResult {
  /// 创建结果。
  const IncrementalityResult({
    required this.label,
    required this.deltaR2,
    required this.baselineOosR2,
    required this.extendedOosR2,
    required this.dm,
    required this.placebo,
    required this.rawPValue,
    required this.adjustedPValue,
    required this.accepted,
    required this.rejectReason,
  });

  /// 候选名称。
  final String label;

  /// 扩展模型 OOS R² − 基线模型 OOS R²。
  final double deltaR2;

  /// 基线模型 OOS R²（相对历史均值）。
  final double baselineOosR2;

  /// 扩展模型 OOS R²。
  final double extendedOosR2;

  /// DM 检验（基线 vs 扩展的平方误差）。
  final DmResult? dm;

  /// 安慰剂结果。
  final PlaceboResult placebo;

  /// DM 原始 p 值（无效时为 1）。
  final double rawPValue;

  /// Holm 校正后的 p 值。
  final double adjustedPValue;

  /// 是否通过全部三道关。
  final bool accepted;

  /// 未通过的原因（中文短句；通过时为 null）。
  final String? rejectReason;

  /// 序列化。
  Map<String, Object?> toJson() => <String, Object?>{
    'label': label,
    'delta_r2_oos': deltaR2,
    'baseline_oos_r2': baselineOosR2,
    'extended_oos_r2': extendedOosR2,
    'dm': dm?.toJson(),
    'placebo': placebo.toJson(),
    'raw_p_value': rawPValue,
    'adjusted_p_value': adjustedPValue,
    'accepted': accepted,
    'reject_reason': rejectReason,
  };
}

/// 增量检验报告。
final class IncrementalityReport {
  /// 创建报告。
  const IncrementalityReport({
    required this.results,
    required this.oosPoints,
    required this.minTrain,
    required this.placeboPermutations,
    required this.alpha,
  });

  /// 每个候选的结果（与输入同序）。
  final List<IncrementalityResult> results;

  /// 有效样本外点数。
  final int oosPoints;

  /// 训练期最少点数。
  final int minTrain;

  /// 安慰剂置换次数。
  final int placeboPermutations;

  /// 显著性水平。
  final double alpha;

  /// 通过全部关卡的候选。
  List<String> get acceptedLabels => <String>[
    for (final r in results)
      if (r.accepted) r.label,
  ];

  /// 序列化。
  Map<String, Object?> toJson() => <String, Object?>{
    'oos_points': oosPoints,
    'min_train': minTrain,
    'placebo_permutations': placeboPermutations,
    'alpha': alpha,
    'results': [for (final r in results) r.toJson()],
    'accepted': acceptedLabels,
    'note': '未通过安慰剂的候选不得进入最终判定（docs/23 §7）',
  };
}

/// 一次成对的样本外预测（扩展窗口均值 / 基线 / 扩展 / 真实值）。
final class _PairedOos {
  const _PairedOos(this.mean, this.baseline, this.extended, this.actual);

  /// 扩展窗口均值（OOS R² 的共同基准）。
  final List<double> mean;
  final List<double> baseline;
  final List<double> extended;
  final List<double> actual;

  int get n => actual.length;

  List<double> get baselineLoss => <double>[
    for (var i = 0; i < n; i++) _sq(baseline[i] - actual[i]),
  ];

  List<double> get extendedLoss => <double>[
    for (var i = 0; i < n; i++) _sq(extended[i] - actual[i]),
  ];

  double get sseBaseline => baselineLoss.reduce((a, b) => a + b);

  double get sseExtended => extendedLoss.reduce((a, b) => a + b);

  /// 基准 SSE（历史均值预测）。
  double get sseMeanBenchmark {
    var sse = 0.0;
    for (var i = 0; i < n; i++) {
      sse += _sq(mean[i] - actual[i]);
    }
    return sse;
  }
}

double _sq(double v) => v * v;

_PairedOos? _pairedExpandingWindow({
  required List<List<double>> baseline,
  required List<List<double>> extended,
  required List<double> target,
  required int minTrain,
}) {
  final n = target.length;
  if (baseline.length != n || extended.length != n || n <= minTrain + 2) {
    return null;
  }
  final means = <double>[];
  final basePreds = <double>[];
  final extPreds = <double>[];
  final actuals = <double>[];
  for (var t = minTrain; t < n; t++) {
    final meanTrain = mean(target.sublist(0, t));
    final baseFit = olsFit(baseline.sublist(0, t), target.sublist(0, t));
    final extFit = olsFit(extended.sublist(0, t), target.sublist(0, t));
    if (meanTrain == null || baseFit == null || extFit == null) {
      continue;
    }
    means.add(meanTrain);
    basePreds.add(olsPredict(baseFit, baseline[t]));
    extPreds.add(olsPredict(extFit, extended[t]));
    actuals.add(target[t]);
  }
  if (basePreds.length < 3) {
    return null;
  }
  return _PairedOos(means, basePreds, extPreds, actuals);
}

/// 跑增量检验：每个候选新增特征块独立对比基线，再统一 Holm 校正并逐条过安慰剂。
///
/// [baseline] / [extended] 的行必须与 [target] 按同一时间轴对齐（升序，PIT 纪律）。
/// [additions] 的每一块是"基线 + 该候选"的完整特征矩阵（便于调用方控制交互项）。
IncrementalityReport runIncrementality({
  required List<List<double>> baseline,
  required Map<String, List<List<double>>> additions,
  required List<double> target,
  required math.Random random,
  int minTrain = 20,
  int placeboPermutations = 200,
  double alpha = 0.05,
}) {
  final labels = additions.keys.toList(growable: false);
  final drafts = <_Draft>[];

  for (final label in labels) {
    final extended = additions[label]!;
    final paired = _pairedExpandingWindow(
      baseline: baseline,
      extended: extended,
      target: target,
      minTrain: minTrain,
    );
    if (paired == null) {
      drafts.add(
        _Draft(
          label: label,
          deltaR2: 0,
          baselineOosR2: 0,
          extendedOosR2: 0,
          dm: null,
          placebo: _emptyPlacebo,
          rejectReason: '样本不足或设计矩阵奇异，无法做样本外评估',
        ),
      );
      continue;
    }
    final sseMean = paired.sseMeanBenchmark;
    final baseR2 = 1 - paired.sseBaseline / sseMean;
    final extR2 = 1 - paired.sseExtended / sseMean;
    final delta = extR2 - baseR2;
    final dm = dieboldMariano(
      lossA: paired.baselineLoss,
      lossB: paired.extendedLoss,
    );

    // 安慰剂：按时间打乱新增特征块的行，破坏与目标的对应关系。
    final addedWidth = extended.first.length - baseline.first.length;
    final placeboStats = <double>[];
    if (addedWidth > 0) {
      for (var p = 0; p < placeboPermutations; p++) {
        final shuffled = _shuffleAddition(
          baseline: baseline,
          extended: extended,
          random: random,
        );
        final placeboPaired = _pairedExpandingWindow(
          baseline: baseline,
          extended: shuffled,
          target: target,
          minTrain: minTrain,
        );
        if (placeboPaired == null) {
          continue;
        }
        final placeboBaseR2 = 1 - placeboPaired.sseBaseline / sseMean;
        final placeboExtR2 = 1 - placeboPaired.sseExtended / sseMean;
        placeboStats.add(placeboExtR2 - placeboBaseR2);
      }
    }
    drafts.add(
      _Draft(
        label: label,
        deltaR2: delta,
        baselineOosR2: baseR2,
        extendedOosR2: extR2,
        dm: dm,
        placebo: placeboPValue(
          observed: delta,
          placeboStatistics: placeboStats,
        ),
        rejectReason: null,
      ),
    );
  }

  // Holm 校正：只对有效的 DM p 值排序，无效候选保留 p=1。
  final validIndexes = <int>[
    for (var i = 0; i < drafts.length; i++)
      if (drafts[i].dm != null) i,
  ];
  final rawP = <double>[for (final i in validIndexes) drafts[i].dm!.pValue];
  final holm = holmCorrection(
    <String>[for (final i in validIndexes) drafts[i].label],
    rawP,
    alpha: alpha,
  );
  final adjustedByLabel = <String, double>{
    for (var i = 0; i < validIndexes.length; i++)
      drafts[validIndexes[i]].label: holm.adjustedPValues[i],
  };

  final results = <IncrementalityResult>[];
  for (final d in drafts) {
    final adjusted = adjustedByLabel[d.label] ?? 1.0;
    String? reason;
    if (d.dm == null) {
      reason = d.rejectReason ?? '无法完成 DM 检验';
    } else if (!(d.deltaR2 > 0)) {
      reason = 'ΔR²_OS ≤ 0：样本外未改善';
    } else if (adjusted >= alpha) {
      reason = 'Holm 校正后不显著（p=${adjusted.toStringAsFixed(4)}）';
    } else if (!d.placebo.passed) {
      reason = '安慰剂也显著（p=${d.placebo.pValue.toStringAsFixed(4)}）：打乱后仍"有效"，结论作废';
    }
    results.add(
      IncrementalityResult(
        label: d.label,
        deltaR2: d.deltaR2,
        baselineOosR2: d.baselineOosR2,
        extendedOosR2: d.extendedOosR2,
        dm: d.dm,
        placebo: d.placebo,
        rawPValue: d.dm?.pValue ?? 1,
        adjustedPValue: adjusted,
        accepted: reason == null,
        rejectReason: reason,
      ),
    );
  }

  final oosPoints = results.isEmpty
      ? 0
      : (target.length - minTrain).clamp(0, target.length);
  return IncrementalityReport(
    results: results,
    oosPoints: oosPoints,
    minTrain: minTrain,
    placeboPermutations: placeboPermutations,
    alpha: alpha,
  );
}

/// 打乱新增列的行顺序（基线列与目标保持不动）。
List<List<double>> _shuffleAddition({
  required List<List<double>> baseline,
  required List<List<double>> extended,
  required math.Random random,
}) {
  final width = baseline.first.length;
  final added = <List<double>>[for (final row in extended) row.sublist(width)];
  final order = List<int>.generate(added.length, (i) => i)..shuffle(random);
  return <List<double>>[
    for (var i = 0; i < extended.length; i++)
      <double>[...baseline[i], ...added[order[i]]],
  ];
}

final class _Draft {
  _Draft({
    required this.label,
    required this.deltaR2,
    required this.baselineOosR2,
    required this.extendedOosR2,
    required this.dm,
    required this.placebo,
    required this.rejectReason,
  });

  final String label;
  final double deltaR2;
  final double baselineOosR2;
  final double extendedOosR2;
  final DmResult? dm;
  final PlaceboResult placebo;
  final String? rejectReason;
}

const PlaceboResult _emptyPlacebo = PlaceboResult(
  observed: 0,
  pValue: 1,
  permutations: 0,
  placeboStatistics: <double>[],
);
