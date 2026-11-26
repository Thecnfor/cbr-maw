/// R4 协调仲裁（docs/03 §4.2；旧 `orchestration/conflict.py`）。
///
/// 优先级：工具重算 > 权威证据等级 > 人工（HITL）。偏好差异不判错。
library;

import '../blackboard/evidence_blackboard.dart';
import '../models/domain.dart';
import '../roles/role_config.dart';

/// subject 关键词 → 权威工具（顺序敏感：越具体越靠前）。
const List<(List<String>, String)> kSubjectToolRules = [
  (
    [
      'northbound',
      'southbound',
      'capital_flow',
      'ah_premium',
      '资金',
      '北向',
      '南向',
      '跨境',
    ],
    'capital_flow',
  ),
  (['funding', 'credit_spread', 'refinanc', '利差', '融资', '信用'], 'funding_cost'),
  (
    ['spillover', 'covar', 'correlation', 'systemic', '外溢', '传染', '相关性'],
    'systemic_risk',
  ),
  (
    ['var', 'cvar', 'drawdown', 'volatility', '最大回撤', '波动', '回撤'],
    'risk_measure',
  ),
  (['stress_prob', 'probability', 'prob_high', '预测概率', '高压力概率'], 'forecast'),
  (['scenario', '情景', '冲击'], 'scenario'),
  (['policy', 'regulation', '政策', '监管', '资本管制'], 'knowledge_search'),
  (['trend', 'direction', '方向', '趋势'], 'systemic_risk'),
];

/// 兜底工具。
const String kDefaultTool = 'risk_measure';

/// 按 subject 选权威工具（可选限定已注册工具集）。
String? toolForSubject(String? subject, {Set<String>? available}) {
  final text = (subject ?? '').toLowerCase();
  for (final (keywords, tool) in kSubjectToolRules) {
    if (!keywords.any(text.contains)) {
      continue;
    }
    if (available != null && !available.contains(tool)) {
      continue;
    }
    return tool;
  }
  if (available != null) {
    return available.contains(kDefaultTool) ? kDefaultTool : null;
  }
  return kDefaultTool;
}

/// 仲裁结果。
final class ArbitrationResult {
  /// 创建结果。
  const ArbitrationResult({
    required this.conflicts,
    required this.escalated,
    required this.claimStatusUpdates,
    required this.limitations,
    required this.toolCalls,
  });

  /// 已仲裁的冲突。
  final List<Conflict> conflicts;

  /// 升级 HITL 的冲突 id。
  final List<String> escalated;

  /// 需要回写的 claim 状态。
  final Map<String, ClaimStatus> claimStatusUpdates;

  /// 仲裁局限。
  final List<String> limitations;

  /// 仲裁消耗的工具调用。
  final int toolCalls;
}

/// 对冲突逐条仲裁。
///
/// [recompute] 为权威重算回调：给定工具名与 subject，返回新证据（失败返回 null）。
/// 它走「绕过权限」的重算入口，仅编排层可用。
Future<ArbitrationResult> arbitrateConflicts({
  required List<Conflict> conflicts,
  required Map<String, Claim> claimsById,
  required EvidenceBlackboard board,
  required Map<RoleId, RoleSpec> specs,
  Future<Evidence?> Function(String tool, Conflict conflict)? recompute,
  bool finalRound = true,
}) async {
  final resolvedConflicts = <Conflict>[];
  final escalated = <String>[];
  final statusUpdates = <String, ClaimStatus>{};
  final limitations = <String>[];
  var toolCalls = 0;

  for (final conflict in conflicts) {
    if (conflict.resolved) {
      resolvedConflicts.add(conflict);
      continue;
    }

    if (conflict.type == ConflictType.preference) {
      for (final claimId in conflict.claimIds) {
        statusUpdates[claimId] = ClaimStatus.preference;
      }
      resolvedConflicts.add(
        conflict.copyWith(
          resolved: true,
          resolvedBy: ResolvedBy.consensus,
          resolution: '偏好差异，保留差异、分主体呈现，不计入错误率。',
        ),
      );
      continue;
    }

    final claims = [
      for (final id in conflict.claimIds)
        if (claimsById[id] != null) claimsById[id]!,
    ];
    if (claims.isEmpty) {
      continue;
    }

    final tool = toolForSubject(conflict.subject);
    if (tool != null &&
        recompute != null &&
        conflict.type == ConflictType.fact) {
      final permissionRoles = claims
          .map((c) => specs[c.role]?.allowsTool(tool) ?? false)
          .toList();
      if (permissionRoles.any((allowed) => allowed)) {
        toolCalls++;
        final evidence = await recompute(tool, conflict);
        if (evidence != null) {
          board.add(evidence);
          final authoritative = evidence.value;
          if (authoritative != null) {
            final sorted = [...claims]
              ..sort((a, b) {
                final da = (a.value ?? 0) - authoritative;
                final db = (b.value ?? 0) - authoritative;
                return da.abs().compareTo(db.abs());
              });
            for (final claim in sorted) {
              statusUpdates[claim.claimId] =
                  claim.claimId == sorted.first.claimId
                  ? ClaimStatus.verified
                  : ClaimStatus.rejected;
            }
          }
          resolvedConflicts.add(
            conflict.copyWith(
              resolved: true,
              resolvedBy: ResolvedBy.tool,
              resolution:
                  '以工具重算为准（${evidence.tool?.name ?? tool}），证据 ${evidence.evidenceId}。',
            ),
          );
          continue;
        }
      } else {
        limitations.add('口径权威工具 $tool 不在相关角色权限内，仲裁降级为证据等级裁决。');
      }
    }

    // 权威证据等级裁决。
    final grades = claims.map((c) => _maxGrade(c.evidenceIds, board)).toList();
    final maxGrade = grades.reduce((a, b) => a >= b ? a : b);
    if (maxGrade > 0 && grades.where((g) => g == maxGrade).length == 1) {
      final winnerIndex = grades.indexOf(maxGrade);
      for (var i = 0; i < claims.length; i++) {
        statusUpdates[claims[i].claimId] = i == winnerIndex
            ? ClaimStatus.verified
            : ClaimStatus.rejected;
      }
      resolvedConflicts.add(
        conflict.copyWith(
          resolved: true,
          resolvedBy: ResolvedBy.authority,
          resolution: '按证据权威等级裁决（tool 3 > kb/policy 2 > signal/market 1）。',
        ),
      );
      continue;
    }

    if (finalRound) {
      escalated.add(conflict.conflictId);
      resolvedConflicts.add(
        conflict.copyWith(
          severity: Severity.high,
          resolution: '自动仲裁无法判定，升级人工复核。',
        ),
      );
    } else {
      resolvedConflicts.add(conflict.copyWith(resolution: '证据不足，保留冲突待后续轮次。'));
    }
  }

  return ArbitrationResult(
    conflicts: resolvedConflicts,
    escalated: escalated,
    claimStatusUpdates: statusUpdates,
    limitations: limitations,
    toolCalls: toolCalls,
  );
}

int _maxGrade(List<String> evidenceIds, EvidenceBlackboard board) {
  var max = 0;
  for (final id in evidenceIds) {
    final grade = board.lookup(id)?.grade ?? 0;
    if (grade > max) {
      max = grade;
    }
  }
  return max;
}
