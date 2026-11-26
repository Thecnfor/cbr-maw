/// 成本与硬预算（docs/03 §6；旧 `orchestration/budget.py`）。
///
/// J = L + μ·C；预算耗尽 → 明确降级为「部分结论」，**绝不降级为 Mock 结论**。
library;

import '../models/domain.dart';
import '../roles/role_config.dart';

/// 成本模型。
final class CostModel {
  /// 创建成本模型。
  const CostModel({
    required this.costPerToolCall,
    required this.costPer1kTokens,
    required this.costPerLatencyMs,
    required this.coordinationWeightMu,
  });

  /// 从编排配置构造。
  factory CostModel.fromSettings(OrchestrationSettings settings) => CostModel(
    costPerToolCall: settings.costPerToolCall,
    costPer1kTokens: settings.costPer1kTokens,
    costPerLatencyMs: settings.costPerLatencyMs,
    coordinationWeightMu: settings.coordinationWeightMu,
  );

  /// 每次工具调用成本。
  final double costPerToolCall;

  /// 每千 token 成本。
  final double costPer1kTokens;

  /// 每毫秒延迟成本。
  final double costPerLatencyMs;

  /// 协同成本权重 μ。
  final double coordinationWeightMu;

  /// L：语言/推理成本。
  double languageCost(TokenUsage usage) =>
      (usage.total / 1000.0) * costPer1kTokens;

  /// C：协调成本。
  double coordinationCost({required int toolCalls, required int latencyMs}) =>
      toolCalls * costPerToolCall + latencyMs * costPerLatencyMs;

  /// J = L + μ·C。
  double jointCost({
    required TokenUsage tokens,
    required int toolCalls,
    required int latencyMs,
  }) =>
      languageCost(tokens) +
      coordinationWeightMu *
          coordinationCost(toolCalls: toolCalls, latencyMs: latencyMs);
}

/// 单角色预算。
final class RoleBudget {
  /// 创建预算。
  const RoleBudget({
    required this.maxToolCalls,
    required this.maxTokens,
    required this.maxLatencyMs,
  });

  /// 从配置构造。
  factory RoleBudget.fromSettings(OrchestrationSettings settings) => RoleBudget(
    maxToolCalls: settings.maxToolCallsPerAgent,
    maxTokens: settings.maxTokensPerAgent,
    maxLatencyMs: settings.maxLatencyMsPerAgent,
  );

  /// 工具调用上限。
  final int maxToolCalls;

  /// token 上限。
  final int maxTokens;

  /// 延迟上限。
  final int maxLatencyMs;

  /// 剩余可用（不可变）。
  RoleBudget minus({int toolCalls = 0, int tokens = 0, int latencyMs = 0}) =>
      RoleBudget(
        maxToolCalls: (maxToolCalls - toolCalls).clamp(0, maxToolCalls),
        maxTokens: (maxTokens - tokens).clamp(0, maxTokens),
        maxLatencyMs: (maxLatencyMs - latencyMs).clamp(0, maxLatencyMs),
      );

  /// 是否已耗尽。
  bool get exhausted => maxToolCalls <= 0 || maxTokens <= 0;
}

/// 任务级预算账本：每角色池 + 整轮熔断。
final class BudgetGuard {
  /// 创建预算守卫。
  BudgetGuard({
    required this.perRole,
    required this.maxWallClockMs,
    required this.maxJointCost,
    required int actorCount,
    required this.costModel,
    this.startedAt,
  }) : _remaining = {for (var i = 0; i < actorCount; i++) i: perRole};

  /// 每角色上限。
  final RoleBudget perRole;

  /// 墙钟上限。
  final int maxWallClockMs;

  /// J 的硬上限（null 表示不限）。
  final double? maxJointCost;

  /// 成本模型。
  final CostModel costModel;

  /// 起始时刻（用于墙钟判断）。
  final DateTime? startedAt;

  final Map<int, RoleBudget> _remaining;
  var _toolCalls = 0;
  var _tokens = 0;
  var _latencyMs = 0;
  var _truncated = false;
  var _tripped = false;
  String? _tripReason;

  /// 是否发生截断。
  bool get truncated => _truncated;

  /// 是否熔断。
  bool get tripped => _tripped;

  /// 熔断原因。
  String? get tripReason => _tripReason;

  /// 累计工具调用。
  int get totalToolCalls => _toolCalls;

  /// 累计 token。
  int get totalTokens => _tokens;

  /// 累计延迟。
  int get totalLatencyMs => _latencyMs;

  /// 当前 J。
  double get jointCost => costModel.jointCost(
    tokens: TokenUsage(total: _tokens),
    toolCalls: _toolCalls,
    latencyMs: _latencyMs,
  );

  /// 请求一次工具调用；超限返回 false（该次调用不执行）。
  bool requestToolCall(int slot) {
    if (_tripped) {
      return false;
    }
    final budget = _remaining[slot];
    if (budget == null || budget.maxToolCalls <= 0) {
      _truncated = true;
      return false;
    }
    _remaining[slot] = budget.minus(toolCalls: 1);
    _toolCalls++;
    return true;
  }

  /// 记录 token（超出上限时截断，返回实际计入量）。
  int chargeTokens(int slot, int raw) {
    if (raw <= 0) {
      return 0;
    }
    final budget = _remaining[slot];
    final allowed = budget == null ? raw : raw.clamp(0, budget.maxTokens);
    if (budget != null) {
      _remaining[slot] = budget.minus(tokens: allowed);
    }
    if (allowed < raw) {
      _truncated = true;
    }
    _tokens += allowed;
    return allowed;
  }

  /// 记录延迟。
  void chargeLatency(int latencyMs) {
    _latencyMs += latencyMs.clamp(0, 1 << 30);
  }

  /// 检查熔断条件（墙钟 / J）。
  bool checkCircuitBreaker() {
    if (_tripped) {
      return true;
    }
    final started = startedAt;
    if (started != null &&
        DateTime.now().difference(started).inMilliseconds > maxWallClockMs) {
      _tripped = true;
      _tripReason = 'wallClock';
    } else if (maxJointCost != null && jointCost > maxJointCost!) {
      _tripped = true;
      _tripReason = 'jointCost';
    }
    return _tripped;
  }
}
