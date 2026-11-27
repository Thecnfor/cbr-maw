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
  Map<String, Object?> payload = const {'metric': 'dy_spillover'},
}) => Evidence(
  evidenceId: id,
  kind: EvidenceKind.tool,
  asOf: asOf ?? DateTime.utc(2024, 8, 5),
  title: title,
  // 升级判定只认结构化指标名（payload.metric），不认正文关键词：
  // 正文里天然含工具名与中文描述，会把每个时点都判成越阈。
  payload: payload,
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

    test('工具名出现在正文里不得触发升级（回归）', () {
      // 回归：曾用 title+summary 全文匹配关键词，`systemic_risk` 的标题天然含
      // "systemic"、risk_measure 的摘要天然含「回撤」→ 每个时点都被判越阈，
      // 三主体恒定 critical，判别力归零。
      final decision = decideLevel(
        spec: spec('regulator'),
        signal: RiskSignal(
          asOf: DateTime.utc(2024, 8, 5),
          modelVersion: 'test',
          horizons: const {10: 0.3},
        ),
        evidence: [
          toolEvidence(
            value: 0.62,
            title: 'systemic_risk 溢出指数',
            payload: const {}, // 无结构化指标名
          ),
        ],
      );
      expect(
        decision.escalationEvidenceIds,
        isEmpty,
        reason: '只有工具名/正文命中，不应升级',
      );
      expect(decision.level, RiskLevel.medium);
    });

    test('LLM 自评高于确定性定级 → 上调一级（漏报成本更高）', () {
      final decision = decideLevel(
        spec: spec('regulator'),
        signal: RiskSignal(
          asOf: DateTime.utc(2024, 8, 5),
          modelVersion: 'test',
          horizons: const {10: 0.3},
        ),
        evidence: const [],
        llmAssessment: RiskLevel.high,
      );
      // 0.3 → medium；LLM 说 high → 上调到 high。
      expect(decision.level, RiskLevel.high);
      expect(decision.llmAdjusted, isTrue);
      expect(decision.limitations.any((l) => l.contains('上调')), isTrue);
    });

    test('LLM 自评低于确定性定级 → 一律不采纳（不得压低风险）', () {
      final decision = decideLevel(
        spec: spec('regulator'),
        signal: RiskSignal(
          asOf: DateTime.utc(2024, 8, 5),
          modelVersion: 'test',
          horizons: const {10: 0.8},
        ),
        evidence: const [],
        llmAssessment: RiskLevel.low,
      );
      expect(
        decision.level,
        RiskLevel.critical,
        reason: '0.8 ≥ 0.7 → critical',
      );
      expect(decision.llmAdjusted, isFalse);
    });

    test('无 LLM 自评时定级与旧口径一致（向后兼容）', () {
      final decision = decideLevel(
        spec: spec('regulator'),
        signal: RiskSignal(
          asOf: DateTime.utc(2024, 8, 5),
          modelVersion: 'test',
          horizons: const {10: 0.3},
        ),
        evidence: const [],
      );
      expect(decision.level, RiskLevel.medium);
      expect(decision.llmAdjusted, isFalse);
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
