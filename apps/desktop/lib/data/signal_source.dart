import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart'
    show Failure, SidecarClient, Success;

/// 共享风险信号的**真实来源**：kernel `signal.compute`（CFSI 确定性压力分位）。
///
/// 返回 null = 该时点无可用信号（缺失维度不得填 0）；调用方按「信号缺失」处理。
final class KernelSignalSource {
  /// 创建来源。
  const KernelSignalSource(this.client);

  /// sidecar 客户端。
  final SidecarClient client;

  /// 取 [asOf] 当日信号。
  Future<RiskSignal?> read(DateTime asOf) async {
    final day = asOf.toUtc().toIso8601String().substring(0, 10);
    final results = await client
        .send('signal.compute', {'as_of': day})
        .toList();
    final result = results.single;
    return switch (result) {
      Success(:final value) => _parse(day, value),
      Failure() => null,
    };
  }

  /// 边界解析即校验：字段缺失或类型不符 → 返回 null（不猜值）。
  static RiskSignal? _parse(String day, Object? payload) {
    if (payload is! Map<String, Object?>) {
      return null;
    }
    final value = payload['value'];
    final signalId = payload['signal_id'];
    if (value is! num || signalId is! String) {
      return null;
    }
    final level = payload['level'];
    return RiskSignal(
      asOf: DateTime.parse('${day}T10:00:00Z'),
      modelVersion: payload['model_version'] as String? ?? 'cfsi-deterministic',
      horizons: {5: value.toDouble(), 10: value.toDouble(), 20: value.toDouble()},
      percentile: value.toDouble(),
      level: _level(level is String ? level : ''),
      evidenceId: payload['evidence_id'] as String?,
    );
  }

  static RiskLevel _level(String wire) => switch (wire) {
    'critical' => RiskLevel.critical,
    'high' => RiskLevel.high,
    'medium' => RiskLevel.medium,
    _ => RiskLevel.low,
  };
}
