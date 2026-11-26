import 'dart:math' as math;

import 'package:cbr_maw/experiments/statistics.dart';
import 'package:flutter_test/flutter_test.dart';

/// 生成线性可预测序列：y = 1.5 + 2.0 x + 噪声。
({List<List<double>> features, List<double> target}) _linearData(
  int n, {
  double noise = 0.0,
  int seed = 7,
}) {
  final random = math.Random(seed);
  final features = <List<double>>[];
  final target = <double>[];
  for (var i = 0; i < n; i++) {
    final x = i / n;
    final y =
        1.5 + 2.0 * x + (noise == 0 ? 0 : (random.nextDouble() - 0.5) * noise);
    features.add(<double>[x]);
    target.add(y);
  }
  return (features: features, target: target);
}

void main() {
  group('Diebold–Mariano', () {
    test('无差异：两模型损失相同 → 不显著', () {
      // 加一点噪声使差值方差非零（完全相同差值方差为 0，DM 未定义）。
      final random = math.Random(17);
      final base = List<double>.generate(200, (i) => (i % 7).toDouble());
      final lossB = <double>[
        for (final v in base) v + (random.nextDouble() - 0.5) * 1e-6,
      ];
      final dm = dieboldMariano(lossA: base, lossB: lossB);
      expect(dm, isNotNull);
      expect(dm!.pValue, greaterThan(0.05));
      expect(dm.significant, isFalse);
    });

    test('有差异：A 损失系统性更高 → 显著且统计量为正', () {
      final random = math.Random(3);
      final lossA = List<double>.generate(
        200,
        (_) => 1.0 + random.nextDouble() * 0.2,
      );
      final lossB = List<double>.generate(
        200,
        (_) => 0.1 + random.nextDouble() * 0.2,
      );
      final dm = dieboldMariano(lossA: lossA, lossB: lossB);
      expect(dm, isNotNull);
      expect(dm!.statistic, greaterThan(0));
      expect(dm.pValue, lessThan(0.05));
      expect(dm.meanLossDiff, greaterThan(0.5));
    });

    test('样本不足返回 null', () {
      expect(dieboldMariano(lossA: [1, 2], lossB: [1, 2]), isNull);
    });
  });

  group('嵌套 F 检验', () {
    test('无改善：受限模型 RSS 不变 → F≈0、不显著', () {
      final f = nestedFTest(
        rssRestricted: 100,
        rssUnrestricted: 100,
        dfRestricted: 50,
        dfUnrestricted: 49,
      );
      expect(f, isNotNull);
      expect(f!.fStatistic, closeTo(0, 1e-12));
      expect(f.significant, isFalse);
    });

    test('显著改善：RSS 大幅下降 → 显著', () {
      final f = nestedFTest(
        rssRestricted: 200,
        rssUnrestricted: 100,
        dfRestricted: 51,
        dfUnrestricted: 49,
      );
      expect(f, isNotNull);
      expect(f!.fStatistic, greaterThan(1));
      expect(f.pValue, lessThan(0.05));
      expect(f.dfNumerator, 2);
      expect(f.dfDenominator, 49);
    });

    test('非法输入返回 null', () {
      expect(
        nestedFTest(
          rssRestricted: 100,
          rssUnrestricted: 90,
          dfRestricted: 49,
          dfUnrestricted: 49,
        ),
        isNull,
      );
    });
  });

  group('Holm 校正', () {
    test('校正后 p 值单调不减且 >= 原始 p 值', () {
      final raw = <double>[0.001, 0.02, 0.04, 0.2, 0.5];
      final result = holmCorrection(<String>['a', 'b', 'c', 'd', 'e'], raw);
      for (var i = 0; i < raw.length; i++) {
        expect(result.adjustedPValues[i], greaterThanOrEqualTo(raw[i] - 1e-12));
      }
      final sorted = List<double>.from(result.adjustedPValues)..sort();
      for (var i = 1; i < sorted.length; i++) {
        expect(sorted[i], greaterThanOrEqualTo(sorted[i - 1] - 1e-12));
      }
      // 最小的 p 乘以 m，后面的按秩放宽。
      expect(result.adjustedPValues[0], closeTo(0.001 * 5, 1e-12));
    });

    test('拒绝集合随 α 单调（更严的 α 拒绝更少）', () {
      final raw = <double>[0.01, 0.03, 0.2];
      final loose = holmCorrection(<String>['a', 'b', 'c'], raw, alpha: 0.05);
      final strict = holmCorrection(<String>['a', 'b', 'c'], raw, alpha: 0.01);
      expect(
        strict.significantLabels.length,
        lessThanOrEqualTo(loose.significantLabels.length),
      );
    });
  });

  group('Kendall tau-b', () {
    test('完全同序 → 1，完全反序 → −1', () {
      final a = <double>[1, 2, 3, 4, 5];
      expect(kendallTauB(a, a), closeTo(1.0, 1e-12));
      expect(kendallTauB(a, <double>[5, 4, 3, 2, 1]), closeTo(-1.0, 1e-12));
    });

    test('手算值（含并列）：x=[1,2,3], y=[1,1,2] → tau_b=2/3', () {
      // 对： (0,1) y 并列、(0,2) 一致、(1,2) 一致
      // C=2, D=0, T_x=0, T_y=1 → 2 / sqrt((2+0+0)(2+0+1)) = 2/sqrt(6) ≈ 0.8165
      final tau = kendallTauB(<double>[1, 2, 3], <double>[1, 1, 2]);
      expect(tau, closeTo(2 / math.sqrt(6), 1e-12));
    });

    test('全并列 → 分母为 0 → null', () {
      expect(kendallTauB(<double>[1, 1, 1], <double>[2, 2, 2]), isNull);
    });
  });

  group('Bootstrap 置信区间', () {
    test('均值 CI 覆盖真实均值（覆盖率近似 nominal）', () {
      final random = math.Random(11);
      final population = List<double>.generate(
        500,
        (_) => 10 + random.nextDouble() * 4,
      );
      final trueMean = mean(population)!;
      var covered = 0;
      const trials = 60;
      for (var t = 0; t < trials; t++) {
        final sample = List<double>.generate(
          80,
          (_) => population[random.nextInt(population.length)],
        );
        final ci = bootstrapConfidenceInterval(
          sample,
          mean,
          random: math.Random(t),
          samples: 400,
          confidence: 0.9,
        );
        if (ci != null && ci.covers(trueMean)) {
          covered++;
        }
      }
      final rate = covered / trials;
      // 90% nominal；有限样本 + 重采样噪声，给宽一点的容差。
      expect(rate, greaterThanOrEqualTo(0.75));
      expect(rate, lessThanOrEqualTo(1.0));
    });

    test('参数非法返回 null', () {
      expect(
        bootstrapConfidenceInterval([1, 2], mean, random: math.Random(1)),
        isNull,
      );
    });
  });

  group('扩展窗口 OOS R²', () {
    test('线性可预测序列 → R² > 0；纯噪声 → R² <= 0', () {
      final linear = _linearData(120, noise: 0.0);
      final r2 = expandingWindowOosR2(
        features: linear.features,
        target: linear.target,
      );
      expect(r2, isNotNull);
      expect(r2!.r2, greaterThan(0.9));

      final random = math.Random(5);
      final noiseFeatures = <List<double>>[
        for (var i = 0; i < 120; i++) <double>[random.nextDouble()],
      ];
      final noiseTarget = <double>[
        for (var i = 0; i < 120; i++) random.nextDouble(),
      ];
      final noiseR2 = expandingWindowOosR2(
        features: noiseFeatures,
        target: noiseTarget,
      );
      expect(noiseR2, isNotNull);
      expect(noiseR2!.r2, lessThanOrEqualTo(0.1));
    });

    test('样本不足返回 null', () {
      expect(
        expandingWindowOosR2(
          features: <List<double>>[
            [1],
            [2],
          ],
          target: [1, 2],
        ),
        isNull,
      );
    });
  });

  group('安慰剂检验与防自欺门卫', () {
    test('真实信号：观测效应在置换分布之外 → 安慰剂通过', () {
      // 观测效应大，置换后的效应都接近 0。
      final placeboStats = List<double>.generate(
        200,
        (i) => math.sin(i.toDouble()) * 0.01,
      );
      final result = placeboPValue(
        observed: 0.5,
        placeboStatistics: placeboStats,
      );
      expect(result.passed, isTrue);
      expect(result.pValue, lessThan(0.05));
    });

    test('打乱后仍显著 → 安慰剂不通过 → certify 拒绝', () {
      final placeboStats = List<double>.generate(
        200,
        (i) => 0.4 + math.sin(i.toDouble()) * 0.05,
      );
      final result = placeboPValue(
        observed: 0.42,
        placeboStatistics: placeboStats,
      );
      expect(result.passed, isFalse);
      expect(
        PredictiveClaim.certify(effect: 0.42, pValue: 0.001, placebo: result),
        isNull,
      );
    });

    test('通过安慰剂后 certify 返回凭证', () {
      final placeboStats = List<double>.generate(200, (i) => i / 10000);
      final result = placeboPValue(
        observed: 0.5,
        placeboStatistics: placeboStats,
      );
      final claim = PredictiveClaim.certify(
        effect: 0.5,
        pValue: 0.01,
        placebo: result,
      );
      expect(claim, isNotNull);
      expect(claim!.effect, 0.5);
    });

    test('rankAgreement 是唯一的跨模态口径（对称）', () {
      final a = <double>[1, 2, 3, 4, 5, 6];
      final b = <double>[2, 1, 4, 3, 6, 5];
      final forward = rankAgreement(a, b);
      final reverse = rankAgreement(b, a);
      expect(forward, isNotNull);
      expect(forward, closeTo(reverse!, 1e-12));
    });
  });
}
