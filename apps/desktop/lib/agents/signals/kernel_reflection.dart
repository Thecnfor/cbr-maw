import 'package:cbr_maw_contracts/contracts_dart.dart'
    show Failure, SidecarClient, Success;

/// 浅层反思（`X-AlertAgent` 外环）：kernel `reflection.shallow`。
///
/// 把「历史上结构相似的时点之后发生了什么」作为**证据**喂给角色，
/// 让结论带跨时点归因，而不是只看当日快照。
///
/// 反思失败**不得**阻断研判：返回 null，调用方按「无反思」继续，
/// 并把原因写进 limitations（零 Mock：不编造相似案例）。
final class KernelReflection {
  /// 创建反思源。
  const KernelReflection(this.client);

  /// sidecar 客户端。
  final SidecarClient client;

  /// 取 [asOf] 时点的相似案例。
  Future<ReflectionEvidence?> read(
    DateTime asOf, {
    int topK = 3,
    int horizon = 20,
  }) async {
    final day = asOf.toUtc().toIso8601String().substring(0, 10);
    final results = await client
        .send('reflection.shallow', {
          'as_of': day,
          'top_k': topK,
          'horizon': horizon,
        })
        .toList();
    final result = results.single;
    return switch (result) {
      Success(:final value) => _parse(day, value),
      Failure() => null,
    };
  }

  /// 边界解析即校验：结构不符 → null（不猜值）。
  static ReflectionEvidence? _parse(String day, Object? payload) {
    if (payload is! Map<String, Object?>) {
      return null;
    }
    final cases = payload['similar_cases'];
    if (cases is! List || cases.isEmpty) {
      return null;
    }
    final parsed = <ReflectionCase>[];
    for (final item in cases.whereType<Map<String, Object?>>()) {
      final date = item['as_of'];
      final outcome = item['outcome'];
      if (date is! String || outcome is! Map<String, Object?>) {
        continue;
      }
      parsed.add(
        ReflectionCase(
          asOf: date,
          level: item['level']?.toString() ?? '',
          distance: (item['distance'] as num?)?.toDouble(),
          peak: (outcome['peak'] as num?)?.toDouble(),
          last: (outcome['last'] as num?)?.toDouble(),
          delta: (outcome['delta'] as num?)?.toDouble(),
        ),
      );
    }
    if (parsed.isEmpty) {
      return null;
    }
    return ReflectionEvidence(
      asOf: day,
      historySize: (payload['history_size'] as num?)?.toInt() ?? 0,
      cases: parsed,
    );
  }
}

/// 深层反思（HLR）：预警效能复盘的**真实来源**。
///
/// 浅层反思回答「现在像历史上哪天」，深层反思回答「我们过去报得准不准」。
/// 两者都是**参考**而非证据：没有 evidence_id，不得作为 claim 依据。
final class KernelDeepReflection {
  /// 创建来源。
  const KernelDeepReflection(this.client);

  /// sidecar 客户端。
  final SidecarClient client;

  /// 取 [asOf] 时点的效能复盘。
  Future<ReflectionPerformance?> read(
    DateTime asOf, {
    int lookbackDays = 120,
    int horizon = 20,
  }) async {
    final day = asOf.toUtc().toIso8601String().substring(0, 10);
    final results = await client
        .send('reflection.deep', {
          'as_of': day,
          'lookback_days': lookbackDays,
          'horizon': horizon,
        })
        .toList();
    final result = results.single;
    return switch (result) {
      Success(:final value) => _parse(value),
      Failure() => null,
    };
  }

  static ReflectionPerformance? _parse(Object? payload) {
    if (payload is! Map<String, Object?>) {
      return null;
    }
    final perf = payload['performance'];
    final window = payload['window'];
    if (perf is! Map<String, Object?> || window is! Map<String, Object?>) {
      return null;
    }
    double? d(Map<String, Object?> map, String key) =>
        (map[key] as num?)?.toDouble();
    int? i(Map<String, Object?> map, String key) =>
        (map[key] as num?)?.toInt();
    return ReflectionPerformance(
      evaluableDays: i(window, 'evaluable_days') ?? 0,
      horizon: i(window, 'horizon') ?? 0,
      alarms: i(perf, 'alarms') ?? 0,
      hits: i(perf, 'hits') ?? 0,
      falseAlarms: i(perf, 'false_alarms') ?? 0,
      missed: i(perf, 'missed') ?? 0,
      precision: d(perf, 'precision'),
      recall: d(perf, 'recall'),
      baseRate: d(perf, 'base_rate'),
      lift: d(perf, 'lift'),
    );
  }
}

/// 预警效能复盘结果。
final class ReflectionPerformance {
  /// 创建结果。
  const ReflectionPerformance({
    required this.evaluableDays,
    required this.horizon,
    required this.alarms,
    required this.hits,
    required this.falseAlarms,
    required this.missed,
    this.precision,
    this.recall,
    this.baseRate,
    this.lift,
  });

  /// 可评估天数。
  final int evaluableDays;

  /// 事后窗口（交易日）。
  final int horizon;

  /// 报警次数。
  final int alarms;

  /// 命中次数。
  final int hits;

  /// 误报次数。
  final int falseAlarms;

  /// 漏报次数。
  final int missed;

  /// 精确率。
  final double? precision;

  /// 召回率。
  final double? recall;

  /// 基准发生率。
  final double? baseRate;

  /// 相对基准的增益。
  final double? lift;

  /// 渲染成角色可读的一段文本。
  String render() {
    final buffer = StringBuffer(
      '历史预警效能（近 $evaluableDays 个可评估时点，事后 $horizon 交易日）：\n',
    );
    if (precision != null) {
      buffer.write('- 精确率 ${precision!.toStringAsFixed(3)}');
    }
    if (recall != null) {
      buffer.write('，召回率 ${recall!.toStringAsFixed(3)}');
    }
    if (lift != null) {
      buffer.write('，相对基准增益 ${lift!.toStringAsFixed(3)}×');
    }
    buffer.write('\n- 报警 $alarms 次（命中 $hits / 误报 $falseAlarms），漏报 $missed 次\n');
    if (baseRate != null) {
      buffer.write('- 同期压力基准发生率 ${(baseRate! * 100).toStringAsFixed(1)}%\n');
    }
    return buffer.toString();
  }
}

/// 一条历史相似案例。
final class ReflectionCase {
  /// 创建案例。
  const ReflectionCase({
    required this.asOf,
    required this.level,
    this.distance,
    this.peak,
    this.last,
    this.delta,
  });

  /// 历史时点。
  final String asOf;

  /// 该时点的信号等级。
  final String level;

  /// 结构距离（越小越相似）。
  final double? distance;

  /// 事后窗口内的压力峰值。
  final double? peak;

  /// 事后窗口末值。
  final double? last;

  /// 事后窗口内的净变化。
  final double? delta;
}

/// 一次反思的结果（供角色提示词使用）。
final class ReflectionEvidence {
  /// 创建结果。
  const ReflectionEvidence({
    required this.asOf,
    required this.historySize,
    required this.cases,
  });

  /// 决策时点。
  final String asOf;

  /// 可用历史信号条数。
  final int historySize;

  /// 相似案例（按结构距离升序）。
  final List<ReflectionCase> cases;

  /// 渲染成角色可读的一段文本（数值一律原样引用，不重新计算）。
  String render() {
    final buffer = StringBuffer('历史相似时点（结构最接近，事后走势仅供归因）：\n');
    for (final item in cases) {
      buffer.write('- ${item.asOf}（等级 ${item.level}');
      if (item.distance != null) {
        buffer.write('，结构距离 ${item.distance!.toStringAsFixed(4)}');
      }
      if (item.delta != null) {
        buffer.write('，其后压力净变化 ${item.delta!.toStringAsFixed(4)}');
      }
      if (item.peak != null) {
        buffer.write('，峰值 ${item.peak!.toStringAsFixed(4)}');
      }
      buffer.write('）\n');
    }
    return buffer.toString();
  }
}
