import 'package:cbr_maw/agents/claims/claim_materializer.dart';
import 'package:cbr_maw/agents/claims/risk_level.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:cbr_maw/agents/roles/role_config.dart';
import 'package:flutter_test/flutter_test.dart';

import 'fixtures.dart';

Evidence toolEvidence({
  String id = 'ev_tool_1',
  double value = 0.62,
  String title = 'dy_spillover 溢出指数',
  DateTime? asOf,
}) => Evidence(
  evidenceId: id,
  kind: EvidenceKind.tool,
  asOf: asOf ?? DateTime.utc(2024, 8, 5),
  title: title,
  value: value,
  unit: 'ratio',
  tool: const ToolRef(name: 'systemic_risk', version: '1.0.0'),
  createdAt: DateTime.utc(2024, 8, 5),
  hash: 'hash_$id',
);

Evidence kbEvidence({String id = 'ev_kb_1'}) => Evidence(
  evidenceId: id,
  kind: EvidenceKind.kb,
  asOf: DateTime.utc(2024, 8, 5),
  title: '宏观审慎政策',
  source: SourceRef(
    name: 'kb',
    chunkId: 'chunk_1',
    releaseTime: DateTime.utc(2024, 8, 1),
  ),
  createdAt: DateTime.utc(2024, 8, 5),
  hash: 'hash_$id',
);

void main() {
  group('claim 自检回填', () {
    test('无证据的 claim 被丢弃并记 claim_rejected', () {
      final result = materializeClaims(
        drafts: const [
          DraftClaim(
            claimType: 'numeric',
            subject: '外溢指数',
            text: '外溢指数为 0.62',
            evidenceIds: ['ev_missing'],
          ),
        ],
        evidence: {toolEvidence().evidenceId: toolEvidence()},
        role: RoleId.regulator,
      );

      expect(result.claims, isEmpty);
      expect(result.rejected, hasLength(1));
      expect(result.rejected.single.reason, 'unsupported_by_evidence');
    });

    test('numeric claim 以工具证据覆盖模型自报数值', () {
      final evidence = toolEvidence(value: 0.62);
      final result = materializeClaims(
        drafts: const [
          DraftClaim(
            claimType: 'numeric',
            subject: '外溢指数',
            text: '模型编的 0.99',
            value: 0.99,
            unit: 'percent',
            evidenceIds: ['ev_tool_1'],
          ),
        ],
        evidence: {evidence.evidenceId: evidence},
        role: RoleId.regulator,
      );

      expect(result.claims, hasLength(1));
      expect(result.claims.single.value, 0.62);
      expect(result.claims.single.unit, 'ratio');
    });

    test('text claim 缺少 KB 证据被丢弃', () {
      final result = materializeClaims(
        drafts: const [
          DraftClaim(
            claimType: 'text',
            subject: '政策',
            text: '政策收紧',
            evidenceIds: ['ev_tool_1'],
          ),
        ],
        evidence: {toolEvidence().evidenceId: toolEvidence()},
        role: RoleId.regulator,
      );
      expect(result.claims, isEmpty);
      expect(result.rejected.single.reason, 'unsupported_by_evidence');
    });

    test('text claim 绑定 KB 证据时保留', () {
      final kb = kbEvidence();
      final result = materializeClaims(
        drafts: const [
          DraftClaim(
            claimType: 'text',
            subject: '政策',
            text: '政策偏紧',
            evidenceIds: ['ev_kb_1'],
          ),
        ],
        evidence: {kb.evidenceId: kb},
        role: RoleId.regulator,
      );
      expect(result.claims.single.claimType, ClaimType.text);
      expect(result.claims.single.evidenceIds, ['ev_kb_1']);
    });
  });

  group('确定性定级', () {
    RoleSpec spec(String role) => catalog().spec(RoleId.parse(role));

    test('概率越 critical 阈值 → critical', () {
      final decision = decideLevel(
        spec: spec('regulator'),
        signal: RiskSignal(
          asOf: DateTime.utc(2024, 8, 5),
          modelVersion: 'test',
          horizons: const {10: 0.75},
        ),
        evidence: const [],
      );
      expect(decision.level, RiskLevel.critical);
    });

    test('工具证据越阈 → 等级 +1 并记录触发证据', () {
      final decision = decideLevel(
        spec: spec('regulator'),
        signal: RiskSignal(
          asOf: DateTime.utc(2024, 8, 5),
          modelVersion: 'test',
          horizons: const {10: 0.3},
        ),
        evidence: [toolEvidence(value: 0.62)],
      );
      // 0.3 >= 0.5*0.5 → medium，再因 dy_spillover=0.62 >= 0.5 上调到 high。
      expect(decision.level, RiskLevel.high);
      expect(decision.escalationEvidenceIds, ['ev_tool_1']);
    });

    test('缺窗口时取最近窗口', () {
      expect(
        probabilityForWindow(
          RiskSignal(
            asOf: DateTime.utc(2024, 8, 5),
            modelVersion: 'test',
            horizons: const {5: 0.2, 20: 0.6},
          ),
          10,
        ),
        0.2,
      );
    });
  });
}
