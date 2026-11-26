/// 领先期（lead-lag）分析（docs/10 MT-08、docs/18 §3.2、docs/23 §7 第 4 条）。
///
/// 口径：`corr(signal(t), target(t+h))`，h 为**前瞻交易日数**。
/// - 只看 h=0 会把领先信号误判为无效（docs/18：W=40 时 h=0 相关为负）；
/// - 峰值 h 是领先期的主判据，`peak_h == 0` 判为同期型。
///
/// 纯函数：输入两个等长序列（时间升序，缺失用 null），输出可序列化结构。
library;

import 'dart:math' as math;

import 'statistics.dart';

/// 默认前瞻期（与 `data/seed/score_signals.py` 及 docs/18 §3.2 一致）。
const List<int> defaultLeadHorizons = <int>[0, 5, 10, 20, 40, 60];

/// 单个 h 的交叉相关。
final class LeadPoint {
  /// 创建点。
  const LeadPoint({required this.h, required this.corr, required this.n});

  /// 前瞻交易日数。
  final int h;

  /// Pearson 相关（有效对 < 3 时为 null）。
  final double? corr;

  /// 有效观测对数。
  final int n;

  /// 序列化。
  Map<String, Object?> toJson() => <String, Object?>{
    'h': h,
    'corr': corr,
    'n': n,
  };
}

/// 领先性判定。
enum LeadVerdict {
  /// 峰值在 h=0。
  contemporaneous('contemporaneous'),

  /// 峰值在 h>0。
  leading('leading'),

  /// 无有效相关点。
  inconclusive('inconclusive');

  const LeadVerdict(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 领先期分析结果。
final class LeadLagProfile {
  /// 创建结果。
  const LeadLagProfile({
    required this.points,
    required this.peakH,
    required this.peakCorr,
    required this.verdict,
    required this.n,
  });

  /// 每个 h 的相关点。
  final List<LeadPoint> points;

  /// 峰值所在 h（无有效点时 null）。
  final int? peakH;

  /// 峰值相关。
  final double? peakCorr;

  /// 判定。
  final LeadVerdict verdict;

  /// 最长序列上的有效观测总数（用于样本量披露）。
  final int n;

  /// 序列化（bench 调用口径）。
  Map<String, Object?> toJson() => <String, Object?>{
    'points': [for (final p in points) p.toJson()],
    'peak_h': peakH,
    'peak_corr': peakCorr,
    'verdict': verdict.wire,
    'n': n,
    'note': '只看同期会把领先信号误判为无效；必须报整条 lead profile（docs/23 §7 第 4 条）',
  };
}

/// 计算 `corr(signal(t), target(t+h))` 曲线并判定领先/同期。
///
/// [signal] 与 [target] 必须等长且**已按同一交易日历对齐**（调用方负责）。
/// 缺失一律用 null；不插补。
LeadLagProfile leadLagProfile(
  List<double?> signal,
  List<double?> target, {
  List<int> horizons = defaultLeadHorizons,
}) {
  if (signal.length != target.length) {
    throw ArgumentError(
      'signal 与 target 长度必须一致（${signal.length} vs ${target.length}）',
    );
  }
  final points = <LeadPoint>[];
  var maxN = 0;
  for (final h in horizons) {
    if (h < 0) {
      throw ArgumentError('h 必须 >= 0（实际 $h）');
    }
    final xs = <double>[];
    final ys = <double>[];
    for (var i = 0; i + h < signal.length; i++) {
      final x = signal[i];
      final y = target[i + h];
      if (x != null && y != null && x.isFinite && y.isFinite) {
        xs.add(x);
        ys.add(y);
      }
    }
    maxN = math.max(maxN, xs.length);
    points.add(LeadPoint(h: h, corr: pearson(xs, ys), n: xs.length));
  }
  LeadPoint? peak;
  for (final p in points) {
    if (p.corr == null) {
      continue;
    }
    if (peak == null || p.corr!.abs() > peak.corr!.abs()) {
      peak = p;
    }
  }
  return LeadLagProfile(
    points: points,
    peakH: peak?.h,
    peakCorr: peak?.corr,
    verdict: peak == null
        ? LeadVerdict.inconclusive
        : (peak.h == 0 ? LeadVerdict.contemporaneous : LeadVerdict.leading),
    n: maxN,
  );
}
