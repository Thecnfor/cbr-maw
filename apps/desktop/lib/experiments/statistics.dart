/// 实验统计基元（docs/10 MT-07 / MT-08、docs/23 §4）。
///
/// 口径说明（自实现，理由见文件末尾）：
/// - Dart 生态没有轻量的统计检验包，`dart pub` 加重量级依赖不划算（工程约束）。
///   这里用最小实现覆盖 DM / 嵌套 F / Welch t / 置换检验所需的分布函数。
/// - 正态 CDF 用 Abramowitz & Stegun 7.1.26 误差函数近似（绝对误差 < 1.5e-7）。
/// - Student-t 与 F 的 CDF 走**正则化不完全 Beta 函数**（Lentz 连分数，
///   Numerical Recipes 口径），双精度下与 scipy 的偏差 < 1e-10。
/// - 所有「缺失」都用 `null` 表示，**不插补、不填 0**。
library;

import 'dart:math' as math;

/// 均值（空集返回 null，不返回 0）。
double? mean(List<double> values) {
  if (values.isEmpty) {
    return null;
  }
  var sum = 0.0;
  for (final v in values) {
    sum += v;
  }
  return sum / values.length;
}

/// 样本方差（ddof=1；样本量 < 2 返回 null）。
double? variance(List<double> values) {
  if (values.length < 2) {
    return null;
  }
  final m = mean(values)!;
  var acc = 0.0;
  for (final v in values) {
    final d = v - m;
    acc += d * d;
  }
  return acc / (values.length - 1);
}

/// 样本标准差（ddof=1）。
double? stdDev(List<double> values) {
  final v = variance(values);
  return v == null ? null : math.sqrt(v);
}

/// Pearson 相关（成对完整观测；样本 < 3 或方差为 0 返回 null）。
double? pearson(List<double> x, List<double> y) {
  if (x.length != y.length || x.length < 3) {
    return null;
  }
  final xs = <double>[];
  final ys = <double>[];
  for (var i = 0; i < x.length; i++) {
    if (x[i].isFinite && y[i].isFinite) {
      xs.add(x[i]);
      ys.add(y[i]);
    }
  }
  if (xs.length < 3) {
    return null;
  }
  final mx = mean(xs)!;
  final my = mean(ys)!;
  var sxy = 0.0;
  var sxx = 0.0;
  var syy = 0.0;
  for (var i = 0; i < xs.length; i++) {
    final dx = xs[i] - mx;
    final dy = ys[i] - my;
    sxy += dx * dy;
    sxx += dx * dx;
    syy += dy * dy;
  }
  if (sxx <= 0 || syy <= 0) {
    return null;
  }
  return sxy / math.sqrt(sxx * syy);
}

/// Spearman 秩相关（对称统计量；docs/17 §4.3 要求跨模态一致性只能用对称口径）。
double? spearman(List<double> x, List<double> y) {
  if (x.length != y.length || x.length < 3) {
    return null;
  }
  final xs = <double>[];
  final ys = <double>[];
  for (var i = 0; i < x.length; i++) {
    if (x[i].isFinite && y[i].isFinite) {
      xs.add(x[i]);
      ys.add(y[i]);
    }
  }
  if (xs.length < 3) {
    return null;
  }
  return pearson(_ranks(xs), _ranks(ys));
}

/// 平均秩（并列取平均）。
List<double> _ranks(List<double> values) {
  final indexed = List<int>.generate(values.length, (i) => i)
    ..sort((a, b) => values[a].compareTo(values[b]));
  final ranks = List<double>.filled(values.length, 0);
  var i = 0;
  while (i < indexed.length) {
    var j = i;
    while (j + 1 < indexed.length &&
        values[indexed[j + 1]] == values[indexed[i]]) {
      j++;
    }
    final avg = (i + j) / 2 + 1;
    for (var k = i; k <= j; k++) {
      ranks[indexed[k]] = avg;
    }
    i = j + 1;
  }
  return ranks;
}

/// 误差函数近似（Abramowitz & Stegun 7.1.26，绝对误差 < 1.5e-7）。
double erf(double x) {
  final sign = x < 0 ? -1.0 : 1.0;
  final ax = x.abs();
  final t = 1.0 / (1.0 + 0.3275911 * ax);
  final y =
      1.0 -
      (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t -
                      0.284496736) *
                  t +
              0.254829592) *
          t *
          math.exp(-ax * ax);
  return sign * y;
}

/// 正态分布 CDF。
double normalCdf(double x) => 0.5 * (1.0 + erf(x / math.sqrt(2.0)));

/// 正态分布双侧 p 值（|z|）。
double normalTwoSidedP(double z) => 2.0 * (1.0 - normalCdf(z.abs()));

/// 正则化不完全 Beta 函数 I_x(a, b)。
double regularizedIncompleteBeta(double a, double b, double x) {
  if (x <= 0) {
    return 0;
  }
  if (x >= 1) {
    return 1;
  }
  final logBeta = _logGamma(a + b) - _logGamma(a) - _logGamma(b);
  final front = math.exp(logBeta + a * math.log(x) + b * math.log(1 - x));
  if (x < (a + 1) / (a + b + 2)) {
    return front * _betaContinuedFraction(a, b, x) / a;
  }
  return 1 - front * _betaContinuedFraction(b, a, 1 - x) / b;
}

/// Beta 连分数（Lentz 算法）。
double _betaContinuedFraction(double a, double b, double x) {
  const maxIterations = 300;
  const epsilon = 3.0e-14;
  const tiny = 1.0e-30;
  final qab = a + b;
  final qap = a + 1;
  final qam = a - 1;
  var c = 1.0;
  var d = 1 - qab * x / qap;
  if (d.abs() < tiny) {
    d = tiny;
  }
  d = 1 / d;
  var h = d;
  for (var m = 1; m <= maxIterations; m++) {
    final m2 = 2 * m;
    var aa = m * (b - m) * x / ((qam + m2) * (a + m2));
    d = 1 + aa * d;
    if (d.abs() < tiny) {
      d = tiny;
    }
    c = 1 + aa / c;
    if (c.abs() < tiny) {
      c = tiny;
    }
    d = 1 / d;
    h *= d * c;
    aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2));
    d = 1 + aa * d;
    if (d.abs() < tiny) {
      d = tiny;
    }
    c = 1 + aa / c;
    if (c.abs() < tiny) {
      c = tiny;
    }
    d = 1 / d;
    final delta = d * c;
    h *= delta;
    if ((delta - 1).abs() < epsilon) {
      return h;
    }
  }
  return h;
}

/// Lanczos 近似 log Γ(x)。
double _logGamma(double x) {
  const coefficients = <double>[
    676.5203681218851,
    -1259.1392167224028,
    771.32342877765313,
    -176.61502916214059,
    12.507343278686905,
    -0.13857109526572012,
    9.9843695780195716e-6,
    1.5056327351493116e-7,
  ];
  if (x < 0.5) {
    return math.log(math.pi / math.sin(math.pi * x)) - _logGamma(1 - x);
  }
  final z = x - 1;
  var a = 0.99999999999980993;
  final t = z + 7.5;
  for (var i = 0; i < coefficients.length; i++) {
    a += coefficients[i] / (z + i + 1);
  }
  return 0.5 * math.log(2 * math.pi) +
      (z + 0.5) * math.log(t) -
      t +
      math.log(a);
}

/// Student-t 分布 CDF。
double studentTCdf(double t, double df) {
  if (df <= 0) {
    return double.nan;
  }
  final x = df / (df + t * t);
  final ib = regularizedIncompleteBeta(df / 2, 0.5, x);
  final p = 0.5 * ib;
  return t > 0 ? 1 - p : p;
}

/// Student-t 双侧 p 值。
double studentTwoSidedP(double t, double df) =>
    2.0 * (1.0 - studentTCdf(t.abs(), df));

/// F 分布 CDF。
double fCdf(double f, double df1, double df2) {
  if (df1 <= 0 || df2 <= 0 || f <= 0) {
    return f <= 0 ? 0 : 1;
  }
  final x = (df1 * f) / (df1 * f + df2);
  return regularizedIncompleteBeta(df1 / 2, df2 / 2, x);
}

/// F 分布上尾 p 值（1 - CDF）。
double fUpperTailP(double f, double df1, double df2) => 1.0 - fCdf(f, df1, df2);

/// Welch t 检验结果。
final class WelchTTest {
  /// 创建结果。
  const WelchTTest({
    required this.tStatistic,
    required this.pValue,
    required this.df,
    required this.meanA,
    required this.meanB,
    required this.nA,
    required this.nB,
  });

  /// t 统计量。
  final double tStatistic;

  /// 双侧 p 值。
  final double pValue;

  /// 自由度（Welch–Satterthwaite）。
  final double df;

  /// 组 A 均值。
  final double meanA;

  /// 组 B 均值。
  final double meanB;

  /// 组 A 样本量。
  final int nA;

  /// 组 B 样本量。
  final int nB;

  /// 是否显著（α=0.05）。
  bool get significant => pValue < 0.05;
}

/// Welch t 检验（两组均值差异，不假设等方差）。
WelchTTest? welchTTest(List<double> a, List<double> b) {
  if (a.length < 2 || b.length < 2) {
    return null;
  }
  final ma = mean(a)!;
  final mb = mean(b)!;
  final va = variance(a)!;
  final vb = variance(b)!;
  final se = math.sqrt(va / a.length + vb / b.length);
  if (se == 0) {
    return null;
  }
  final t = (ma - mb) / se;
  final df =
      (va / a.length + vb / b.length) *
      (va / a.length + vb / b.length) /
      ((va * va) / (a.length * a.length * (a.length - 1)) +
          (vb * vb) / (b.length * b.length * (b.length - 1)));
  return WelchTTest(
    tStatistic: t,
    pValue: studentTwoSidedP(t, df),
    df: df,
    meanA: ma,
    meanB: mb,
    nA: a.length,
    nB: b.length,
  );
}

/// 置换检验结果（随机打乱标签后的经验 p 值）。
final class PermutationTestResult {
  /// 创建结果。
  const PermutationTestResult({
    required this.observedDifference,
    required this.pValue,
    required this.permutations,
    required this.extremeCount,
  });

  /// 观测到的组间均值差。
  final double observedDifference;

  /// 经验 p 值（双侧）。
  final double pValue;

  /// 置换次数。
  final int permutations;

  /// 极端次数。
  final int extremeCount;

  /// 是否显著（α=0.05）。
  bool get significant => pValue < 0.05;
}

/// 置换检验（打乱组标签，比较组间均值差）。
///
/// [random] 必须由调用方注入，以便测试可复现（禁止用隐式全局随机源）。
PermutationTestResult permutationMeanTest(
  List<double> a,
  List<double> b, {
  required math.Random random,
  int permutations = 1000,
}) {
  final pooled = [...a, ...b];
  final observed = mean(a)! - mean(b)!;
  var extreme = 0;
  for (var i = 0; i < permutations; i++) {
    pooled.shuffle(random);
    final diff =
        mean(pooled.sublist(0, a.length))! - mean(pooled.sublist(a.length))!;
    if (diff.abs() >= observed.abs()) {
      extreme++;
    }
  }
  return PermutationTestResult(
    observedDifference: observed,
    pValue: (extreme + 1) / (permutations + 1),
    permutations: permutations,
    extremeCount: extreme,
  );
}

/// Holm 多重比较校正（docs/23 §4）。
///
/// 输入 p 值与对应的假设标签；输出调整后的 p 值与是否拒绝。
final class HolmResult {
  /// 创建结果。
  const HolmResult({
    required this.labels,
    required this.rawPValues,
    required this.adjustedPValues,
    required this.rejected,
  });

  /// 假设标签（与输入同序）。
  final List<String> labels;

  /// 原始 p 值。
  final List<double> rawPValues;

  /// 校正后 p 值（与输入同序）。
  final List<double> adjustedPValues;

  /// 是否被拒绝（按 α 逐步下调）。
  final List<bool> rejected;

  /// 校正后仍显著的标签集合。
  List<String> get significantLabels => <String>[
    for (var i = 0; i < labels.length; i++)
      if (rejected[i]) labels[i],
  ];
}

/// Holm 校正：按 p 值升序逐步比较 `p_(i) <= α / (m - i)`。
HolmResult holmCorrection(
  List<String> labels,
  List<double> pValues, {
  double alpha = 0.05,
}) {
  final m = pValues.length;
  final order = List<int>.generate(m, (i) => i)
    ..sort((a, b) => pValues[a].compareTo(pValues[b]));
  final adjusted = List<double>.filled(m, 0);
  final rejected = List<bool>.filled(m, false);
  var running = 0.0;
  var stillRejecting = true;
  for (var rank = 0; rank < m; rank++) {
    final idx = order[rank];
    final scaled = pValues[idx] * (m - rank);
    running = math.max(running, scaled);
    adjusted[idx] = math.min(1.0, running);
    if (stillRejecting && pValues[idx] <= alpha / (m - rank)) {
      rejected[idx] = true;
    } else {
      stillRejecting = false;
    }
  }
  return HolmResult(
    labels: labels,
    rawPValues: pValues,
    adjustedPValues: adjusted,
    rejected: rejected,
  );
}

// ---------------------------------------------------------------------------
// 回归与样本外评估（docs/23 §4，MT-07）
// ---------------------------------------------------------------------------

/// 带截距的最小二乘拟合；返回 `[b0, b1, ..., bp]`，奇异或样本不足返回 null。
///
/// 行数必须 > 特征数（否则完全拟合，自由度为零）。
List<double>? olsFit(List<List<double>> features, List<double> target) {
  final n = target.length;
  if (n < 2 || features.length != n) {
    return null;
  }
  final p = features.first.length + 1;
  if (n <= p) {
    return null;
  }
  final ata = List<List<double>>.generate(p, (_) => List<double>.filled(p, 0));
  final aty = List<double>.filled(p, 0);
  for (var i = 0; i < n; i++) {
    final row = features[i];
    final xi = <double>[1, ...row];
    for (var a = 0; a < p; a++) {
      aty[a] += xi[a] * target[i];
      for (var b = a; b < p; b++) {
        ata[a][b] += xi[a] * xi[b];
      }
    }
  }
  for (var a = 0; a < p; a++) {
    for (var b = 0; b < a; b++) {
      ata[a][b] = ata[b][a];
    }
  }
  return _solveLinearSystem(ata, aty);
}

/// 高斯消元（部分主元）；主元接近 0 视为奇异，返回 null。
List<double>? _solveLinearSystem(List<List<double>> a, List<double> b) {
  final n = b.length;
  final m = [
    for (var i = 0; i < n; i++) [...a[i], b[i]],
  ];
  for (var col = 0; col < n; col++) {
    var pivot = col;
    for (var r = col + 1; r < n; r++) {
      if (m[r][col].abs() > m[pivot][col].abs()) {
        pivot = r;
      }
    }
    if (m[pivot][col].abs() < 1e-12) {
      return null;
    }
    final tmp = m[col];
    m[col] = m[pivot];
    m[pivot] = tmp;
    final diag = m[col][col];
    for (var c = col; c <= n; c++) {
      m[col][c] /= diag;
    }
    for (var r = 0; r < n; r++) {
      if (r == col) {
        continue;
      }
      final factor = m[r][col];
      if (factor == 0) {
        continue;
      }
      for (var c = col; c <= n; c++) {
        m[r][c] -= factor * m[col][c];
      }
    }
  }
  return [for (var i = 0; i < n; i++) m[i][n]];
}

/// 用 `olsFit` 的系数预测一行。
double olsPredict(List<double> coefficients, List<double> features) {
  var y = coefficients[0];
  for (var i = 0; i < features.length; i++) {
    y += coefficients[i + 1] * features[i];
  }
  return y;
}

/// 扩展窗口样本外 R²（Campbell–Thompson）。
final class OosR2Result {
  /// 创建结果。
  const OosR2Result({
    required this.r2,
    required this.n,
    required this.sseModel,
    required this.sseBenchmark,
    required this.predictions,
    required this.benchmarkPredictions,
    required this.target,
  });

  /// `1 - SSE_model / SSE_benchmark`；可能为负（模型比历史均值还差）。
  final double r2;

  /// 有效样本外点数。
  final int n;

  /// 模型平方误差和。
  final double sseModel;

  /// 基准（扩展窗口均值）平方误差和。
  final double sseBenchmark;

  /// 逐点预测（只含有效点）。
  final List<double> predictions;

  /// 逐点基准预测。
  final List<double> benchmarkPredictions;

  /// 逐点真实值。
  final List<double> target;

  /// 逐点模型平方误差（DM 检验的 loss 序列）。
  List<double> get squaredErrors => <double>[
    for (var i = 0; i < n; i++) _sq(predictions[i] - target[i]),
  ];

  /// 逐点基准平方误差。
  List<double> get benchmarkSquaredErrors => <double>[
    for (var i = 0; i < n; i++) _sq(benchmarkPredictions[i] - target[i]),
  ];

  /// 序列化（bench 调用口径）。
  Map<String, Object?> toJson() => <String, Object?>{
    'r2': r2,
    'n': n,
    'sse_model': sseModel,
    'sse_benchmark': sseBenchmark,
  };
}

double _sq(double v) => v * v;

/// 扩展窗口样本外 R²：t 只用 `[0, t)` 的数据拟合与取基准均值，再预测 t。
///
/// 时间顺序由输入顺序决定，**调用方必须按日期升序传入**（PIT 纪律）。
/// 有效点 < 3 或拟合始终奇异时返回 null（不返回 0）。
///
/// shortcut: 每个点重拟合一次，O(n²)；日频序列 < 5k 行可接受，
/// 更大样本升级为递归最小二乘或增量 QR。
OosR2Result? expandingWindowOosR2({
  required List<List<double>> features,
  required List<double> target,
  int minTrain = 20,
}) {
  final n = target.length;
  if (features.length != n || n <= minTrain + 2) {
    return null;
  }
  final preds = <double>[];
  final benches = <double>[];
  final actuals = <double>[];
  for (var t = minTrain; t < n; t++) {
    final coeffs = olsFit(features.sublist(0, t), target.sublist(0, t));
    if (coeffs == null) {
      continue;
    }
    final trainMean = mean(target.sublist(0, t));
    if (trainMean == null) {
      continue;
    }
    preds.add(olsPredict(coeffs, features[t]));
    benches.add(trainMean);
    actuals.add(target[t]);
  }
  if (preds.length < 3) {
    return null;
  }
  var sseModel = 0.0;
  var sseBench = 0.0;
  for (var i = 0; i < preds.length; i++) {
    sseModel += _sq(preds[i] - actuals[i]);
    sseBench += _sq(benches[i] - actuals[i]);
  }
  if (sseBench <= 0) {
    return null;
  }
  return OosR2Result(
    r2: 1 - sseModel / sseBench,
    n: preds.length,
    sseModel: sseModel,
    sseBenchmark: sseBench,
    predictions: preds,
    benchmarkPredictions: benches,
    target: actuals,
  );
}

// ---------------------------------------------------------------------------
// Diebold–Mariano 与嵌套 F（docs/23 §4）
// ---------------------------------------------------------------------------

/// DM 检验结果。
final class DmResult {
  /// 创建结果。
  const DmResult({
    required this.statistic,
    required this.pValue,
    required this.meanLossDiff,
    required this.n,
  });

  /// DM 统计量（负值表示 A 的损失更小）。
  final double statistic;

  /// 双侧 p 值（t 分布，df = n−1）。
  final double pValue;

  /// 平均损失差 `mean(lossA − lossB)`。
  final double meanLossDiff;

  /// 有效点数。
  final int n;

  /// 是否显著（α=0.05）。
  bool get significant => pValue < 0.05;

  /// 序列化。
  Map<String, Object?> toJson() => <String, Object?>{
    'statistic': statistic,
    'p_value': pValue,
    'mean_loss_diff': meanLossDiff,
    'n': n,
    'significant': significant,
  };
}

/// Diebold–Mariano 检验（等预测精度）。
///
/// [lossA] / [lossB] 是逐点损失（通常为平方误差），等长。
/// shortcut: 仅做 h=1 的方差估计，未加 Newey–West HAC；重叠多步预测需升级。
DmResult? dieboldMariano({
  required List<double> lossA,
  required List<double> lossB,
}) {
  if (lossA.length != lossB.length || lossA.length < 3) {
    return null;
  }
  final diff = <double>[
    for (var i = 0; i < lossA.length; i++) lossA[i] - lossB[i],
  ];
  final m = mean(diff)!;
  final v = variance(diff)!;
  if (v <= 0) {
    return null;
  }
  final n = diff.length;
  final stat = m / math.sqrt(v / n);
  return DmResult(
    statistic: stat,
    pValue: studentTwoSidedP(stat, (n - 1).toDouble()),
    meanLossDiff: m,
    n: n,
  );
}

/// 嵌套 F 检验结果。
final class NestedFResult {
  /// 创建结果。
  const NestedFResult({
    required this.fStatistic,
    required this.pValue,
    required this.dfNumerator,
    required this.dfDenominator,
  });

  /// F 统计量。
  final double fStatistic;

  /// 上尾 p 值。
  final double pValue;

  /// 分子自由度（新增参数个数）。
  final int dfNumerator;

  /// 分母自由度。
  final int dfDenominator;

  /// 是否显著（α=0.05）。
  bool get significant => pValue < 0.05;

  /// 序列化。
  Map<String, Object?> toJson() => <String, Object?>{
    'f': fStatistic,
    'p_value': pValue,
    'df_numerator': dfNumerator,
    'df_denominator': dfDenominator,
    'significant': significant,
  };
}

/// 嵌套 F 检验：受限模型是否因新增参数显著改善。
///
/// `F = ((RSS_r − RSS_u) / q) / (RSS_u / df_u)`，`q = df_r − df_u`。
NestedFResult? nestedFTest({
  required double rssRestricted,
  required double rssUnrestricted,
  required int dfRestricted,
  required int dfUnrestricted,
}) {
  final q = dfRestricted - dfUnrestricted;
  if (q <= 0 || dfUnrestricted <= 0 || rssUnrestricted <= 0) {
    return null;
  }
  if (rssRestricted < rssUnrestricted) {
    return null;
  }
  final f =
      ((rssRestricted - rssUnrestricted) / q) /
      (rssUnrestricted / dfUnrestricted);
  return NestedFResult(
    fStatistic: f,
    pValue: fUpperTailP(f, q.toDouble(), dfUnrestricted.toDouble()),
    dfNumerator: q,
    dfDenominator: dfUnrestricted,
  );
}

// ---------------------------------------------------------------------------
// Kendall tau-b（含并列）
// ---------------------------------------------------------------------------

/// Kendall tau-b（含并列修正；样本 < 3 或分母为 0 返回 null）。
///
/// `tau_b = (C − D) / sqrt((C + D + T_x)(C + D + T_y))`，
/// `T_x` / `T_y` 分别是仅在 x / y 上并列的对数。
double? kendallTauB(List<double> x, List<double> y) {
  if (x.length != y.length || x.length < 3) {
    return null;
  }
  final xs = <double>[];
  final ys = <double>[];
  for (var i = 0; i < x.length; i++) {
    if (x[i].isFinite && y[i].isFinite) {
      xs.add(x[i]);
      ys.add(y[i]);
    }
  }
  if (xs.length < 3) {
    return null;
  }
  var concordant = 0;
  var discordant = 0;
  var tieX = 0;
  var tieY = 0;
  for (var i = 0; i < xs.length; i++) {
    for (var j = i + 1; j < xs.length; j++) {
      final sx = xs[i].compareTo(xs[j]);
      final sy = ys[i].compareTo(ys[j]);
      if (sx == 0 && sy == 0) {
        continue;
      } else if (sx == 0) {
        tieX++;
      } else if (sy == 0) {
        tieY++;
      } else if (sx == sy) {
        concordant++;
      } else {
        discordant++;
      }
    }
  }
  final denominator = math.sqrt(
    (concordant + discordant + tieX) * (concordant + discordant + tieY),
  );
  if (denominator == 0) {
    return null;
  }
  return (concordant - discordant) / denominator;
}

// ---------------------------------------------------------------------------
// Bootstrap 置信区间
// ---------------------------------------------------------------------------

/// Bootstrap 百分位置信区间。
final class BootstrapInterval {
  /// 创建结果。
  const BootstrapInterval({
    required this.lower,
    required this.upper,
    required this.confidence,
    required this.samples,
  });

  /// 下界。
  final double lower;

  /// 上界。
  final double upper;

  /// 置信水平。
  final double confidence;

  /// 重采样次数。
  final int samples;

  /// 是否覆盖给定值。
  bool covers(double value) => value >= lower && value <= upper;

  /// 序列化。
  Map<String, Object?> toJson() => <String, Object?>{
    'lower': lower,
    'upper': upper,
    'confidence': confidence,
    'samples': samples,
  };
}

/// 百分位 bootstrap 区间。
///
/// [random] 必须由调用方注入（可复现）。统计量在重采样上返回 null 时跳过该次。
BootstrapInterval? bootstrapConfidenceInterval(
  List<double> values,
  double? Function(List<double>) statistic, {
  required math.Random random,
  int samples = 1000,
  double confidence = 0.95,
}) {
  if (values.length < 3 || samples <= 0 || confidence <= 0 || confidence >= 1) {
    return null;
  }
  final stats = <double>[];
  for (var s = 0; s < samples; s++) {
    final resample = List<double>.generate(
      values.length,
      (_) => values[random.nextInt(values.length)],
    );
    final v = statistic(resample);
    if (v != null && v.isFinite) {
      stats.add(v);
    }
  }
  if (stats.length < 10) {
    return null;
  }
  stats.sort();
  final alpha = (1 - confidence) / 2;
  final lowerIndex = (alpha * (stats.length - 1)).round();
  final upperIndex = ((1 - alpha) * (stats.length - 1)).round();
  return BootstrapInterval(
    lower: stats[lowerIndex],
    upper: stats[upperIndex],
    confidence: confidence,
    samples: samples,
  );
}

// ---------------------------------------------------------------------------
// 安慰剂检验与防自欺门卫（docs/17 §4.3、docs/23 §7）
// ---------------------------------------------------------------------------

/// 安慰剂检验结果。
final class PlaceboResult {
  /// 创建结果。
  const PlaceboResult({
    required this.observed,
    required this.pValue,
    required this.permutations,
    required this.placeboStatistics,
  });

  /// 观测统计量。
  final double observed;

  /// 经验双侧 p 值（`(|placebo| >= |observed|)` 的比例，含 +1 校正）。
  final double pValue;

  /// 置换次数。
  final int permutations;

  /// 置换后的统计量（便于审计与作图）。
  final List<double> placeboStatistics;

  /// 安慰剂通过 = 观测效应**可**与置换分布区分（p<0.05）。
  ///
  /// 打乱后效应回落到基准附近 → 观测效应不在置换分布里 → p 小 → 通过。
  /// 若置换后仍与观测同样大（p 大），说明"信号"来自构造而非数据，结论作废。
  bool get passed => pValue < 0.05;

  /// 序列化。
  Map<String, Object?> toJson() => <String, Object?>{
    'observed': observed,
    'p_value': pValue,
    'permutations': permutations,
    'passed': passed,
  };
}

/// 由置换统计量计算经验 p 值（双侧）。
PlaceboResult placeboPValue({
  required double observed,
  required List<double> placeboStatistics,
}) {
  if (placeboStatistics.isEmpty) {
    return PlaceboResult(
      observed: observed,
      pValue: 1,
      permutations: 0,
      placeboStatistics: const [],
    );
  }
  var extreme = 0;
  for (final v in placeboStatistics) {
    if (v.abs() >= observed.abs()) {
      extreme++;
    }
  }
  return PlaceboResult(
    observed: observed,
    pValue: (extreme + 1) / (placeboStatistics.length + 1),
    permutations: placeboStatistics.length,
    placeboStatistics: placeboStatistics,
  );
}

/// 「有预测力」结论的凭证：**没有通过安慰剂检验就不存在**。
final class PredictiveClaim {
  const PredictiveClaim._({
    required this.effect,
    required this.pValue,
    required this.placebo,
  });

  /// 效应量（如 ΔR²_OS、lift−1）。
  final double effect;

  /// 原假设检验的 p 值。
  final double pValue;

  /// 配套安慰剂结果。
  final PlaceboResult placebo;

  /// 认证：安慰剂未通过（即打乱后失效）时返回 null，调用方不得据此下结论。
  static PredictiveClaim? certify({
    required double effect,
    required double pValue,
    required PlaceboResult placebo,
  }) {
    if (!placebo.passed) {
      return null;
    }
    return PredictiveClaim._(effect: effect, pValue: pValue, placebo: placebo);
  }
}

/// 跨模态一致性/背离的**唯一**允许口径：对称秩相关。
///
/// docs/17 §4.3：禁止用 `A − B` 构造背离指标再与下游量求相关（构造性负相关）。
/// 本库刻意**不提供**差值型背离 API；需要跨模态比较时用本函数或 [spearman]。
double? rankAgreement(List<double> a, List<double> b) => kendallTauB(a, b);
