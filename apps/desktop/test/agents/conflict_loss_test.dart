import 'package:cbr_maw/agents/conflict/conflict_loss.dart';
import 'package:cbr_maw/agents/models/domain.dart';
import 'package:flutter_test/flutter_test.dart';

Conflict _conflict({
  required String id,
  required ConflictType type,
  Severity severity = Severity.medium,
  bool resolved = false,
  ResolvedBy? resolvedBy,
}) => Conflict(
  conflictId: id,
  subject: '外溢指数',
  claimIds: const ['c1', 'c2'],
  roles: const [RoleId.regulator, RoleId.investor],
  type: type,
  description: '测试冲突',
  severity: severity,
  resolved: resolved,
  resolvedBy: resolvedBy,
);

void main() {
  group('冲突接入决策损失', () {
    test('偏好差异不计入损失（docs/20：不算错误）', () {
      final loss = conflictLossBreakdown(
        conflicts: [
          _conflict(id: 'k1', type: ConflictType.preference, severity: Severity.high),
        ],
      );
      expect(loss['conflict_total'], 0);
      expect(loss.containsKey('conflict_by_type_preference'), isFalse);
    });

    test('事实分歧比方向分歧更贵', () {
      final fact = conflictLossBreakdown(
        conflicts: [_conflict(id: 'k1', type: ConflictType.fact, severity: Severity.high)],
      );
      final directional = conflictLossBreakdown(
        conflicts: [
          _conflict(id: 'k2', type: ConflictType.directional, severity: Severity.high),
        ],
      );
      expect(fact['conflict_total'], greaterThan(directional['conflict_total']!));
    });

    test('工具重算仲裁后代价大幅下降', () {
      final unresolved = conflictLossBreakdown(
        conflicts: [_conflict(id: 'k1', type: ConflictType.fact, severity: Severity.high)],
      );
      final resolved = conflictLossBreakdown(
        conflicts: [
          _conflict(
            id: 'k1',
            type: ConflictType.fact,
            severity: Severity.high,
            resolved: true,
            resolvedBy: ResolvedBy.tool,
          ),
        ],
      );
      expect(
        resolved['conflict_total']!,
        lessThan(unresolved['conflict_total']! * 0.2),
        reason: '工具重算是最可信的仲裁，代价应显著低于未决',
      );
    });

    test('升级人工的部分单独计数', () {
      final loss = conflictLossBreakdown(
        conflicts: [
          _conflict(id: 'k1', type: ConflictType.fact, severity: Severity.high),
          _conflict(id: 'k2', type: ConflictType.directional),
        ],
        escalated: const ['k1'],
      );
      expect(loss['conflict_escalated'], greaterThan(0));
      expect(
        loss['conflict_escalated']!,
        lessThan(loss['conflict_total']!),
        reason: '升级部分不能超过总损失',
      );
    });

    test('无冲突时总损失为 0', () {
      expect(conflictLossBreakdown(conflicts: const [])['conflict_total'], 0);
    });
  });
}
