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
