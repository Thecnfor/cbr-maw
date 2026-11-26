/// R3 分歧识别（docs/03 §1.3 / §2.3；旧 `orchestration/blackboard.py` 的 detect_conflicts）。
///
/// 只做跨角色 claim 级比对；同角色内部不产生冲突；卡级等级差异不判冲突。
/// 分类优先级：fact > directional > preference。
library;

import '../models/domain.dart';
import '../roles/role_config.dart';

/// subject 归一化：去空格、小写、下划线连接。
String normalizeSubject(String? subject) =>
    (subject ?? '').trim().toLowerCase().split(RegExp(r'\s+')).join('_');

/// 数值比较（绝对 + 相对容差）。
bool numbersMatch(
  double a,
  double b, {
  double absTol = 1e-6,
  double relTol = 1e-3,
}) {
  final diff = (a - b).abs();
  if (diff <= absTol) {
    return true;
  }
  final scale = (a.abs() > b.abs() ? a.abs() : b.abs());
  return scale > 0 && diff / scale <= relTol;
}

/// 检出冲突。
List<Conflict> detectConflicts({
  required List<Claim> claims,
  required Map<RoleId, RoleSpec> specs,
  double absTol = 1e-6,
  double relTol = 1e-3,
}) {
  final bySubject = <String, List<Claim>>{};
  for (final claim in claims) {
    final key = normalizeSubject(claim.subject);
    if (key.isEmpty) {
      continue;
    }
    (bySubject[key] ??= []).add(claim);
  }

  final conflicts = <Conflict>[];
  for (final entry in bySubject.entries) {
    final group = entry.value;
    if (group.length < 2) {
      continue;
    }
    // 每 subject 至多 1 条冲突；跨角色两两分类，取优先级最高者。
    Conflict? best;
    for (var i = 0; i < group.length; i++) {
      for (var j = i + 1; j < group.length; j++) {
        final a = group[i];
        final b = group[j];
        if (a.role == b.role) {
          continue;
        }
        final candidate = _classify(
          a,
          b,
          entry.key,
          specs,
          absTol: absTol,
          relTol: relTol,
        );
        if (candidate == null) {
          continue;
        }
        if (best == null || _rank(candidate.type) > _rank(best.type)) {
          best = candidate;
        }
      }
    }
    if (best != null) {
      conflicts.add(best);
    }
  }

  return [
    for (var i = 0; i < conflicts.length; i++)
      Conflict(
        conflictId: 'cf_${i + 1}',
        subject: conflicts[i].subject,
        claimIds: conflicts[i].claimIds,
        roles: conflicts[i].roles,
        type: conflicts[i].type,
        description: conflicts[i].description,
        severity: conflicts[i].severity,
        evidenceIds: conflicts[i].evidenceIds,
      ),
  ];
}

int _rank(ConflictType type) => switch (type) {
  ConflictType.fact => 3,
  ConflictType.directional => 2,
  ConflictType.preference => 1,
};

Conflict? _classify(
  Claim a,
  Claim b,
  String subject,
  Map<RoleId, RoleSpec> specs, {
  required double absTol,
  required double relTol,
}) {
  final overlap = a.evidenceIds.toSet().intersection(b.evidenceIds.toSet());

  // fact：同 subject、均为 numeric、单位可比、数值不相等、不共享证据。
  if (a.claimType == ClaimType.numeric && b.claimType == ClaimType.numeric) {
    final comparable = _unitsComparable(a.unit, b.unit);
    if (comparable &&
        a.value != null &&
        b.value != null &&
        !numbersMatch(a.value!, b.value!, absTol: absTol, relTol: relTol) &&
        overlap.isEmpty) {
      final scale = (a.value!.abs() > b.value!.abs()
          ? a.value!.abs()
          : b.value!.abs());
      final relative = scale == 0 ? 0.0 : (a.value! - b.value!).abs() / scale;
      return Conflict(
        conflictId: '',
        subject: subject,
        claimIds: [a.claimId, b.claimId],
        roles: [a.role, b.role],
        type: ConflictType.fact,
        description: '同一口径数值不一致：${a.text} / ${b.text}',
        severity: relative > 0.05 ? Severity.high : Severity.medium,
        evidenceIds: [...a.evidenceIds, ...b.evidenceIds],
      );
    }
  }

  // directional：方向相反。
  if (a.claimType == ClaimType.directional &&
      b.claimType == ClaimType.directional) {
    final da = a.direction;
    final db = b.direction;
    if (da != null &&
        db != null &&
        da != Direction.none &&
        db != Direction.none &&
        da != db) {
      return Conflict(
        conflictId: '',
        subject: subject,
        claimIds: [a.claimId, b.claimId],
        roles: [a.role, b.role],
        type: ConflictType.directional,
        description: '方向相反：${da.wire} vs ${db.wire}',
        severity: overlap.isNotEmpty ? Severity.high : Severity.medium,
        evidenceIds: [...a.evidenceIds, ...b.evidenceIds],
      );
    }
  }

  // preference：证据一致或数值相容，但角色阈值/权重不同。
  final specA = specs[a.role];
  final specB = specs[b.role];
  final differs =
      specA != null &&
      specB != null &&
      (specA.highStressProb != specB.highStressProb ||
          specA.decisionLossWeights.toString() !=
              specB.decisionLossWeights.toString());
  if (differs &&
      (overlap.isNotEmpty ||
          (a.value != null &&
              b.value != null &&
              numbersMatch(
                a.value!,
                b.value!,
                absTol: absTol,
                relTol: relTol,
              )))) {
    return Conflict(
      conflictId: '',
      subject: subject,
      claimIds: [a.claimId, b.claimId],
      roles: [a.role, b.role],
      type: ConflictType.preference,
      description: '偏好差异：证据一致但阈值/损失权重不同（不算错误）。',
      severity: Severity.low,
      evidenceIds: [...a.evidenceIds, ...b.evidenceIds],
    );
  }

  return null;
}

bool _unitsComparable(String? a, String? b) {
  if (a == null || b == null || a.isEmpty || b.isEmpty) {
    return true;
  }
  return a.trim().toLowerCase() == b.trim().toLowerCase();
}
