import 'package:cbr_maw/agents/blackboard/evidence_blackboard.dart';
import 'package:cbr_maw/agents/conflict/conflict_arbitrator.dart';
import 'package:cbr_maw/agents/conflict/conflict_detector.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw/agents/verification/verifier.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fixtures.dart';

Claim numericClaim({
  required String id,
  required RoleId role,
  required double value,
  String subject = '外溢指数',
  List<String> evidenceIds = const ['ev_a'],
  String unit = 'ratio',
}) => Claim(
  claimId: id,
  role: role,
  claimType: ClaimType.numeric,
  subject: subject,
  text: '$subject 为 $value',
  value: value,
  unit: unit,
  evidenceIds: evidenceIds,
);

Evidence evidenceFor(String id, {double value = 0.5, DateTime? asOf}) =>
    Evidence(
      evidenceId: id,
      kind: EvidenceKind.tool,
      asOf: asOf ?? DateTime.utc(2024, 8, 5),
      title: 'systemic_risk',
      value: value,
      unit: 'ratio',
      tool: const ToolRef(name: 'systemic_risk', version: '1.0.0'),
      createdAt: DateTime.utc(2024, 8, 5),
      hash: 'hash_$id',
    );

void main() {
  group('冲突三分类', () {
    test('同口径数值不一致且不共享证据 → fact', () {
      final conflicts = detectConflicts(
        claims: [
          numericClaim(id: 'c1', role: RoleId.regulator, value: 0.62),
          numericClaim(
            id: 'c2',
            role: RoleId.investor,
            value: 0.30,
            evidenceIds: const ['ev_b'],
          ),
        ],
        specs: catalog().specs,
      );
      expect(conflicts, hasLength(1));
      expect(conflicts.single.type, ConflictType.fact);
      expect(conflicts.single.severity, Severity.high);
    });

    test('偏好差异不算错误、不计入核验错误率', () async {
      final shared = evidenceFor('ev_shared', value: 0.62);
      final board = EvidenceBlackboard()..add(shared);
      final claims = [
        numericClaim(
          id: 'c1',
          role: RoleId.regulator,
          value: 0.62,
          evidenceIds: const ['ev_shared'],
        ),
        numericClaim(
          id: 'c2',
          role: RoleId.investor,
          value: 0.62,
          evidenceIds: const ['ev_shared'],
        ),
      ];
      final conflicts = detectConflicts(claims: claims, specs: catalog().specs);
      expect(conflicts.single.type, ConflictType.preference);
      expect(conflicts.single.severity, Severity.low);

      final arbitration = await arbitrateConflicts(
        conflicts: conflicts,
        claimsById: {for (final c in claims) c.claimId: c},
        board: board,
        specs: catalog().specs,
      );
      expect(arbitration.escalated, isEmpty);
      expect(
        arbitration.claimStatusUpdates.values.every(
          (status) => status == ClaimStatus.preference,
        ),
        isTrue,
      );

      final report = verify(
        VerificationContext(
          runId: 'run',
          asOf: DateTime.utc(2024, 8, 5),
          cards: [
            RiskCard(
              role: RoleId.regulator,
              asOf: DateTime.utc(2024, 8, 5),
              riskLevel: RiskLevel.medium,
              headline: 'h',
              claims: [claims.first.copyWith(status: ClaimStatus.preference)],
            ),
          ],
          evidenceIndex: board.evidenceById,
          deniedToolCalls: const [],
          roleSpecs: catalog().specs,
        ),
      );
      expect(report.numericChecksTotal, 1);
      expect(report.numericChecksPassed, 1);
      expect(report.numericErrorRate, 0);
    });

    test('方向相反 → directional', () {
      Claim directional(String id, RoleId role, Direction direction) => Claim(
        claimId: id,
        role: role,
        claimType: ClaimType.directional,
        subject: '压力方向',
        text: '方向 ${direction.wire}',
        direction: direction,
        evidenceIds: const ['ev_sig'],
      );
      final conflicts = detectConflicts(
        claims: [
          directional('c1', RoleId.regulator, Direction.up),
          directional('c2', RoleId.investor, Direction.down),
        ],
        specs: catalog().specs,
      );
      expect(conflicts.single.type, ConflictType.directional);
    });
  });

  group('仲裁', () {
    test('fact 冲突优先以工具重算裁决', () async {
      final board = EvidenceBlackboard()..add(evidenceFor('ev_a', value: 0.62));
      final claims = [
        numericClaim(id: 'c1', role: RoleId.regulator, value: 0.62),
        numericClaim(
          id: 'c2',
          role: RoleId.investor,
          value: 0.30,
          evidenceIds: const ['ev_b'],
        ),
      ];
      board.add(evidenceFor('ev_b', value: 0.30));
      final conflicts = detectConflicts(claims: claims, specs: catalog().specs);

      final result = await arbitrateConflicts(
        conflicts: conflicts,
        claimsById: {for (final c in claims) c.claimId: c},
        board: board,
        specs: catalog().specs,
        recompute: (tool, conflict) async =>
            evidenceFor('ev_recomputed', value: 0.62),
      );
      expect(result.conflicts.single.resolvedBy, ResolvedBy.tool);
      expect(result.claimStatusUpdates['c1'], ClaimStatus.verified);
      expect(result.claimStatusUpdates['c2'], ClaimStatus.rejected);
      expect(result.escalated, isEmpty);
    });

    test('无工具可裁且证据等级相同 → 升级 HITL', () async {
      final board = EvidenceBlackboard();
      final claims = [
        numericClaim(
          id: 'c1',
          role: RoleId.regulator,
          value: 0.62,
          evidenceIds: const [],
        ),
        numericClaim(
          id: 'c2',
          role: RoleId.investor,
          value: 0.30,
          evidenceIds: const [],
        ),
      ];
      final conflicts = detectConflicts(claims: claims, specs: catalog().specs);
      final result = await arbitrateConflicts(
        conflicts: conflicts,
        claimsById: {for (final c in claims) c.claimId: c},
        board: board,
        specs: catalog().specs,
        recompute: (tool, conflict) async => null,
      );
      expect(result.escalated, hasLength(1));
    });
  });

  group('六类核验', () {
    RiskCard cardWith(List<Claim> claims, {DateTime? asOf}) => RiskCard(
      role: RoleId.regulator,
      asOf: asOf ?? DateTime.utc(2024, 8, 5),
      riskLevel: RiskLevel.high,
      headline: 'h',
      claims: claims,
    );

    test('泄漏事件 > 0 时核验不通过', () {
      final future = evidenceFor('ev_future', asOf: DateTime.utc(2024, 8, 9));
      final claim = numericClaim(
        id: 'c1',
        role: RoleId.regulator,
        value: 0.5,
        evidenceIds: const ['ev_future'],
      );
      final report = verify(
        VerificationContext(
          runId: 'run',
          asOf: DateTime.utc(2024, 8, 5),
          cards: [
            cardWith([claim]),
          ],
          evidenceIndex: {future.evidenceId: future},
          deniedToolCalls: const [],
          roleSpecs: catalog().specs,
        ),
      );
      expect(report.leakageEvents, 1);
      expect(report.passed, isFalse);
    });

    test('越权工具调用 → permissionViolations 且核验不通过', () {
      final report = verify(
        VerificationContext(
          runId: 'run',
          asOf: DateTime.utc(2024, 8, 5),
          cards: const [],
          evidenceIndex: const {},
          deniedToolCalls: const [(RoleId.financing, 'systemic_risk')],
          roleSpecs: catalog().specs,
        ),
      );
      expect(report.permissionViolations, 1);
      expect(report.passed, isFalse);
    });

    test('数值与工具证据不一致 → numeric 错误', () {
      final evidence = evidenceFor('ev_a', value: 0.62);
      final claim = numericClaim(
        id: 'c1',
        role: RoleId.regulator,
        value: 0.99,
        evidenceIds: const ['ev_a'],
      );
      final report = verify(
        VerificationContext(
          runId: 'run',
          asOf: DateTime.utc(2024, 8, 5),
          cards: [
            cardWith([claim]),
          ],
          evidenceIndex: {evidence.evidenceId: evidence},
          deniedToolCalls: const [],
          roleSpecs: catalog().specs,
        ),
      );
      expect(report.numericChecksPassed, 0);
      expect(report.numericErrorRate, 1.0);
      expect(report.passed, isFalse);
    });

    test('未解决冲突与预算截断被如实记录（偏好差异不算）', () {
      final report = verify(
        VerificationContext(
          runId: 'run',
          asOf: DateTime.utc(2024, 8, 5),
          cards: const [],
          evidenceIndex: const {},
          deniedToolCalls: const [],
          conflicts: const [
            Conflict(
              conflictId: 'cf_1',
              subject: 'x',
              claimIds: ['a', 'b'],
              roles: [RoleId.regulator, RoleId.investor],
              type: ConflictType.fact,
              description: '数值不一致',
            ),
            Conflict(
              conflictId: 'cf_2',
              subject: 'y',
              claimIds: ['c', 'd'],
              roles: [RoleId.regulator, RoleId.investor],
              type: ConflictType.preference,
              description: '偏好差异',
              resolved: true,
              resolvedBy: ResolvedBy.consensus,
            ),
          ],
          budgetTruncated: true,
          roleSpecs: catalog().specs,
        ),
      );
      final types = report.issues.map((i) => i.issueType).toList();
      expect(types, contains('conflict'));
      expect(types, contains('budget'));
      // 只有未解决的 fact 冲突产生 issue，偏好差异不产生。
      expect(types.where((t) => t == 'conflict'), hasLength(1));
    });

    test('KB 证据缺 chunkId → citation 失败', () {
      final kb = Evidence(
        evidenceId: 'ev_kb',
        kind: EvidenceKind.kb,
        asOf: DateTime.utc(2024, 8, 1),
        title: '政策',
        source: const SourceRef(name: 'kb'),
        createdAt: DateTime.utc(2024, 8, 1),
        hash: 'h',
      );
      final claim = Claim(
        claimId: 'c1',
        role: RoleId.regulator,
        claimType: ClaimType.text,
        subject: '政策',
        text: '政策偏紧',
        evidenceIds: const ['ev_kb'],
      );
      final report = verify(
        VerificationContext(
          runId: 'run',
          asOf: DateTime.utc(2024, 8, 5),
          cards: [
            cardWith([claim]),
          ],
          evidenceIndex: {kb.evidenceId: kb},
          deniedToolCalls: const [],
          roleSpecs: catalog().specs,
        ),
      );
      expect(report.citationChecksPassed, 0);
      // 引文错误是 error 级 issue；passed 判据按 docs/03 §2.3（numeric/permission/
      // leakage/schema），此处断言错误被如实记录。
      expect(report.issues.any((i) => i.issueType == 'citation'), isTrue);
    });
  });
}
