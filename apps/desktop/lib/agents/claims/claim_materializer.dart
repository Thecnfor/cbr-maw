/// Claim → Evidence 强制绑定与自检回填（docs/03 §1.7，迁移清单 A.1）。
///
/// 规则：
/// - numeric 一律以 kind=tool 证据的 value/unit 覆盖；无 tool 证据 → 丢弃；
/// - text 必须绑定 kind=kb 证据；否则丢弃；
/// - directional 必须绑定 kind=signal 或数值证据；否则丢弃；
/// - 不在证据包内的 evidenceId 被过滤，过滤后为空 → 丢弃。
///
/// 丢弃是常态，调用方负责记 `claim_rejected` 审计。
library;

import '../models/domain.dart';

/// LLM 草稿主张（未回填）。
final class DraftClaim {
  /// 创建草稿。
  const DraftClaim({
    required this.claimType,
    required this.subject,
    required this.text,
    this.value,
    this.unit,
    this.direction,
    this.evidenceIds = const [],
    this.confidence,
  });

  /// 类型（未知时按 text 处理）。
  final String claimType;

  /// 主题。
  final String subject;

  /// 文本。
  final String text;

  /// LLM 给出的数值（会被证据覆盖）。
  final double? value;

  /// LLM 给出的单位。
  final String? unit;

  /// 方向。
  final Direction? direction;

  /// LLM 引用的证据。
  final List<String> evidenceIds;

  /// 置信度。
  final double? confidence;
}

/// 回填结果：保留的 claim、被拒记录与数值不一致计数。
final class MaterializeResult {
  /// 创建结果。
  const MaterializeResult(this.claims, this.rejected, {this.numericMismatches = 0});

  /// 通过回填的 claim。
  final List<Claim> claims;

  /// 被丢弃的草稿索引与原因。
  final List<RejectedClaim> rejected;

  /// LLM 自报数值与工具重算不一致的条数（docs/23 §3.2「数值不一致率」）。
  ///
  /// 主张里的数值最终一律以工具重算为准，所以这项必须单独计数：
  /// 否则「LLM 说错了多少」在产品里完全不可观测。
  final int numericMismatches;
}

/// 被拒的 claim 记录（写 `claim_rejected` 审计）。
final class RejectedClaim {
  /// 创建记录。
  const RejectedClaim({
    required this.index,
    required this.claimType,
    required this.reason,
    required this.evidenceIds,
  });

  /// 草稿序号（1 起）。
  final int index;

  /// 类型。
  final String claimType;

  /// 原因。
  final String reason;

  /// 原引用证据。
  final List<String> evidenceIds;
}

/// 把 LLM 草稿回填成可溯源 claim。
MaterializeResult materializeClaims({
  required List<DraftClaim> drafts,
  required Map<String, Evidence> evidence,
  required RoleId role,
  String? signalRef,
}) {
  final claims = <Claim>[];
  final rejected = <RejectedClaim>[];
  var numericMismatches = 0;

  for (var i = 0; i < drafts.length; i++) {
    final draft = drafts[i];
    final index = i + 1;
    final availableIds = draft.evidenceIds
        .where(evidence.containsKey)
        .toList(growable: false);
    if (availableIds.isEmpty) {
      rejected.add(
        RejectedClaim(
          index: index,
          claimType: draft.claimType,
          reason: 'unsupported_by_evidence',
          evidenceIds: draft.evidenceIds,
        ),
      );
      continue;
    }

    ClaimType type;
    try {
      type = ClaimType.parse(draft.claimType);
    } on ArgumentError {
      type = ClaimType.text;
    }

    final Claim? claim;
    switch (type) {
      case ClaimType.numeric:
        claim = _numericClaim(
          draft,
          availableIds,
          evidence,
          role,
          claims.length,
        );
      case ClaimType.text:
        claim = _textClaim(draft, availableIds, evidence, role, claims.length);
      case ClaimType.directional:
        claim = _directionalClaim(
          draft,
          availableIds,
          evidence,
          role,
          claims.length,
          signalRef,
        );
    }

    if (claim == null) {
      rejected.add(
        RejectedClaim(
          index: index,
          claimType: draft.claimType,
          reason: 'unsupported_by_evidence',
          evidenceIds: draft.evidenceIds,
        ),
      );
      continue;
    }
    // 数值一致性（只看 LLM 明确给了数值的主张）：与工具重算比对。
    // 容差与核验层一致（docs/09：abs 1e-6 / rel 1e-3）。
    if (type == ClaimType.numeric &&
        draft.value != null &&
        claim.value != null &&
        !_numbersMatch(draft.value!, claim.value!, absTol: 1e-6, relTol: 1e-3)) {
      numericMismatches++;
    }

    claims.add(claim);
  }

  return MaterializeResult(claims, rejected, numericMismatches: numericMismatches);
}

Claim? _numericClaim(
  DraftClaim draft,
  List<String> ids,
  Map<String, Evidence> evidence,
  RoleId role,
  int seq,
) {
  // 数值唯一来源：kind=tool 且带 value；LLM 给的数值一律被覆盖。
  Evidence? numeric;
  for (final id in ids) {
    final item = evidence[id];
    if (item != null && item.kind == EvidenceKind.tool && item.value != null) {
      numeric = item;
      break;
    }
  }
  if (numeric == null) {
    return null;
  }
  final label = draft.subject.trim().isEmpty
      ? numeric.title
      : draft.subject.trim();
  final unit = numeric.unit;
  return Claim(
    claimId: 'clm_${role.wire}_${seq + 1}',
    role: role,
    claimType: ClaimType.numeric,
    subject: label,
    text: unit == null || unit.isEmpty
        ? '$label为 ${numeric.value}'
        : '$label为 ${numeric.value} $unit',
    value: numeric.value,
    unit: unit,
    evidenceIds: _ordered(ids, numeric.evidenceId),
    confidence: _clamp(draft.confidence, 0.9),
  );
}

Claim? _textClaim(
  DraftClaim draft,
  List<String> ids,
  Map<String, Evidence> evidence,
  RoleId role,
  int seq,
) {
  final kbIds = ids
      .where((id) => evidence[id]?.kind == EvidenceKind.kb)
      .toList(growable: false);
  if (kbIds.isEmpty) {
    return null;
  }
  final subject = draft.subject.trim().isEmpty
      ? evidence[kbIds.first]!.title
      : draft.subject.trim();
  return Claim(
    claimId: 'clm_${role.wire}_${seq + 1}',
    role: role,
    claimType: ClaimType.text,
    subject: subject,
    text: draft.text.trim().isEmpty ? '知识库证据支持该判断。' : draft.text.trim(),
    evidenceIds: kbIds,
    confidence: _clamp(draft.confidence, 0.8),
  );
}

Claim? _directionalClaim(
  DraftClaim draft,
  List<String> ids,
  Map<String, Evidence> evidence,
  RoleId role,
  int seq,
  String? signalRef,
) {
  final supported = ids.any((id) {
    final item = evidence[id];
    return item != null &&
        (item.kind == EvidenceKind.signal || item.value != null);
  });
  if (!supported) {
    return null;
  }
  final ordered = signalRef != null && ids.contains(signalRef)
      ? _ordered(ids, signalRef)
      : ids;
  return Claim(
    claimId: 'clm_${role.wire}_${seq + 1}',
    role: role,
    claimType: ClaimType.directional,
    subject: draft.subject.trim().isEmpty ? '方向性判断' : draft.subject.trim(),
    text: draft.text.trim().isEmpty ? '基于现有证据的方向性判断。' : draft.text.trim(),
    direction: draft.direction ?? Direction.none,
    evidenceIds: ordered,
    confidence: _clamp(draft.confidence, 0.75),
  );
}

List<String> _ordered(List<String> ids, String first) => [
  if (ids.contains(first)) first,
  ...ids.where((id) => id != first),
];

double _clamp(double? value, double fallback) =>
    (value ?? fallback).clamp(0.0, 1.0).toDouble();

/// 数值一致（容差与核验层一致）。
bool _numbersMatch(double a, double b, {required double absTol, required double relTol}) {
  final diff = (a - b).abs();
  if (diff <= absTol) {
    return true;
  }
  final scale = a.abs() > b.abs() ? a.abs() : b.abs();
  return diff <= relTol * scale;
}
