import 'dart:math' as math;

import 'package:cbr_maw/experiments/incrementality.dart';
import 'package:cbr_maw/experiments/leadlag.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('leadLagProfile', () {
    test('领先信号：峰值在 h>0，判定 leading', () {
      final random = math.Random(9);
      final n = 400;
      final target = <double?>[for (var i = 0; i < n; i++) random.nextDouble()];
      // signal(t) = target(t+10) + 小噪声 → 峰值在 h=10。
      final signal = <double?>[
        for (var i = 0; i < n; i++)
          i + 10 < n
              ? target[i + 10]! + (random.nextDouble() - 0.5) * 0.1
              : null,
      ];
      final profile = leadLagProfile(signal, target);
      expect(profile.verdict, LeadVerdict.leading);
      expect(profile.peakH, 10);
      expect(profile.peakCorr, greaterThan(0.9));
      expect(profile.points.length, defaultLeadHorizons.length);
    });

    test('同期信号：峰值在 h=0，判定 contemporaneous', () {
      final random = math.Random(4);
      final n = 300;
      final target = <double?>[for (var i = 0; i < n; i++) random.nextDouble()];
      final signal = <double?>[
        for (var i = 0; i < n; i++)
          target[i]! + (random.nextDouble() - 0.5) * 0.1,
      ];
      final profile = leadLagProfile(signal, target);
      expect(profile.verdict, LeadVerdict.contemporaneous);
      expect(profile.peakH, 0);
    });

    test('全缺失 → inconclusive，且结果可序列化', () {
      final profile = leadLagProfile(
        List<double?>.filled(50, null),
        List<double?>.filled(50, null),
      );
      expect(profile.verdict, LeadVerdict.inconclusive);
      final json = profile.toJson();
      expect(json['peak_h'], isNull);
      expect(json['verdict'], 'inconclusive');
    });

    test('长度不一致抛错', () {
      expect(
        () => leadLagProfile(<double?>[1], <double?>[1, 2]),
        throwsArgumentError,
      );
    });
  });

  group('runIncrementality', () {
    test('真实增量特征：ΔR²>0、DM 显著、安慰剂通过 → accepted', () {
      final random = math.Random(21);
      final n = 160;
      final baseline = <List<double>>[];
      final target = <double>[];
      final extended = <List<double>>[];
      for (var i = 0; i < n; i++) {
        final x1 = random.nextDouble();
        final x2 = random.nextDouble();
        final y =
            1.0 + 2.0 * x1 + 3.0 * x2 + (random.nextDouble() - 0.5) * 0.05;
        baseline.add(<double>[x1]);
        extended.add(<double>[x1, x2]);
        target.add(y);
      }
      final report = runIncrementality(
        baseline: baseline,
        additions: <String, List<List<double>>>{'add_x2': extended},
        target: target,
        random: math.Random(1),
        minTrain: 40,
        placeboPermutations: 60,
      );
      final r = report.results.single;
      expect(r.deltaR2, greaterThan(0));
      expect(r.dm, isNotNull);
      expect(r.placebo.passed, isTrue);
      expect(r.accepted, isTrue, reason: r.rejectReason);
      expect(report.acceptedLabels, contains('add_x2'));
      expect(report.toJson()['accepted'], contains('add_x2'));
    });

    test('无增量特征（纯噪声）：ΔR² 不为正或安慰剂/显著性不过 → 拒绝', () {
      final random = math.Random(31);
      final n = 140;
      final baseline = <List<double>>[];
      final target = <double>[];
      final extended = <List<double>>[];
      for (var i = 0; i < n; i++) {
        final x1 = random.nextDouble();
        final x2 = random.nextDouble();
        final y = random.nextDouble();
        baseline.add(<double>[x1]);
        extended.add(<double>[x1, x2]);
        target.add(y);
      }
      final report = runIncrementality(
        baseline: baseline,
        additions: <String, List<List<double>>>{'noise_x2': extended},
        target: target,
        random: math.Random(2),
        minTrain: 40,
        placeboPermutations: 60,
      );
      final r = report.results.single;
      expect(r.accepted, isFalse);
      expect(r.rejectReason, isNotNull);
    });

    test('多候选 Holm 校正：校正后 p 值 >= 原始 p 值', () {
      final random = math.Random(51);
      final n = 150;
      final baseline = <List<double>>[];
      final target = <double>[];
      final ext1 = <List<double>>[];
      final ext2 = <List<double>>[];
      for (var i = 0; i < n; i++) {
        final x1 = random.nextDouble();
        final x2 = random.nextDouble();
        final x3 = random.nextDouble();
        final y =
            1.0 + 2.0 * x1 + 1.5 * x2 + (random.nextDouble() - 0.5) * 0.05;
        baseline.add(<double>[x1]);
        ext1.add(<double>[x1, x2]);
        ext2.add(<double>[x1, x3]);
        target.add(y);
      }
      final report = runIncrementality(
        baseline: baseline,
        additions: <String, List<List<double>>>{'real': ext1, 'fake': ext2},
        target: target,
        random: math.Random(3),
        minTrain: 40,
        placeboPermutations: 40,
      );
      for (final r in report.results) {
        expect(r.adjustedPValue, greaterThanOrEqualTo(r.rawPValue - 1e-12));
      }
    });
  });
}
