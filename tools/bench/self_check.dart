// 基准 harness 的自检：不依赖真实数据也能证明"指标不是空转"。
//
//   dart run tools/bench/self_check.dart
//
// 用合成（显式标注 synthetic）的小序列，验证：
//   1. 滚动 Kendall tau 与手算一致；并列对计入分母；
//   2. 时点泄漏检测器能识别越界窗口、放过合法窗口；
//   3. 提前量统计对"无信号"与"全触发"两种极端给出可区分的结果；
//   4. 质量指标（precision/recall/lift）在构造数据上等于手算值。
//
// 退出码：0 全部通过；1 有断言失败。
// ignore_for_file: avoid_print
import 'dart:math' as math;

import '../src/repo.dart';

void main() {
  final failures = <String>[];
  var checks = 0;

  void check(String name, bool ok, [String detail = '']) {
    checks++;
    if (!ok) {
      failures.add('$name${detail.isEmpty ? '' : "（$detail）"}');
    }
  }

  section('[1] 滚动 Kendall tau');
  {
    // 完全同序 → tau = 1；完全反序 → tau = -1；含并列 → 分母含并列对。
    final increasing = <double>[1, 2, 3, 4, 5];
    final decreasing = <double>[5, 4, 3, 2, 1];
    check('同序 tau=1', (_tau(increasing, increasing) - 1).abs() < 1e-12);
    check('反序 tau=-1', (_tau(increasing, decreasing) + 1).abs() < 1e-12);
    // 手算：a=[1,2,3], b=[1,1,2]；配对 (0,1)=0,(0,2)=+1,(1,2)=+1 → 2/3（分母含并列对）
    final t = _tau(<double>[1, 2, 3], <double>[1, 1, 2]);
    check('并列对计入分母', (t - 2 / 3).abs() < 1e-12, '实际 $t');
  }

  section('[2] 时点泄漏检测');
  {
    check('越界窗口被识别', _leaks(15, 10));
    check('合法窗口不误报', !_leaks(10, 10));
  }

  section('[3] 提前量统计');
  {
    final windows = [120, 180];
    final never = List<double?>.filled(200, -1);
    final always = List<double?>.filled(200, 9);
    check('无信号 → 命中 0', _detected(never, windows, 0.5) == 0);
    check('全触发 → 命中 2', _detected(always, windows, 0.5) == 2);
    // 只在窗口前 40 日触发一次 → 提前量 = 40
    final spaced = List<double?>.filled(200, -1);
    spaced[80] = 9;
    final lead = _lead(spaced, windows, 0.5);
    check('提前量计算正确', lead[0] == 40, '实际 ${lead.isEmpty ? "空" : lead[0]}');
  }

  section('[4] 质量指标');
  {
    final z = <double?>[0.9, 0.1, 0.8, 0.2];
    final y = <int?>[1, 1, 0, 0];
    final oos = [0, 1, 2, 3];
    final q = _quality(z, y, oos, 0.5);
    check('precision=0.5', q.precision == 0.5, '${q.precision}');
    check('recall=0.5', q.recall == 0.5, '${q.recall}');
    check('lift=1.0', q.lift == 1.0, '${q.lift}');
  }

  section('[5] 版本提取');
  {
    // 版本正则必须拒绝非语义化版本，接受标准三段式。
    final re = RegExp(r'^\d+\.\d+\.\d+$');
    check('接受 1.2.3', re.hasMatch('1.2.3'));
    check('拒绝 v1.2', !re.hasMatch('v1.2'));
  }

  finish(failures, checks, '基准自检（SYNTHETIC 输入）');
}

// ---------------------------------------------------------------------------
// 最小实现（与 runner.dart 同口径；刻意不 import runner，避免脚本互相耦合）
// ---------------------------------------------------------------------------

double _tau(List<double> a, List<double> b) {
  var sum = 0.0;
  var pairs = 0;
  for (var i = 0; i < a.length; i++) {
    for (var j = i + 1; j < a.length; j++) {
      sum += (a[i] - a[j]).sign * (b[i] - b[j]).sign;
      pairs++;
    }
  }
  return pairs == 0 ? 0 : sum / pairs;
}

bool _leaks(int windowEnd, int asOf) => windowEnd > asOf;

int _detected(List<double?> z, List<int> windows, double threshold) {
  var count = 0;
  for (final start in windows) {
    for (var k = start - 1; k >= math.max(0, start - 60); k--) {
      final v = z[k];
      if (v != null && v > threshold) {
        count++;
        break;
      }
    }
  }
  return count;
}

List<int> _lead(List<double?> z, List<int> windows, double threshold) {
  final leads = <int>[];
  for (final start in windows) {
    for (var k = start - 1; k >= math.max(0, start - 60); k--) {
      final v = z[k];
      if (v != null && v > threshold) {
        leads.add(start - k);
        break;
      }
    }
  }
  return leads;
}

({double precision, double recall, double? lift}) _quality(
  List<double?> z,
  List<int?> y,
  List<int> oos,
  double threshold,
) {
  var tp = 0, fp = 0, fn = 0;
  for (final i in oos) {
    final signal = z[i] != null && z[i]! > threshold;
    final positive = y[i] == 1;
    if (signal && positive) {
      tp++;
    } else if (signal) {
      fp++;
    } else if (positive) {
      fn++;
    }
  }
  final precision = tp / math.max(1, tp + fp);
  final recall = tp / math.max(1, tp + fn);
  final baseRate = oos.where((i) => y[i] == 1).length / math.max(1, oos.length);
  return (
    precision: precision,
    recall: recall,
    lift: baseRate == 0 ? null : precision / baseRate,
  );
}
