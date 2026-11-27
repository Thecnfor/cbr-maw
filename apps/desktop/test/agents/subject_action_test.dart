import 'package:cbr_maw/agents/models/domain.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('三主体离散行动（ADR-011 §3.1）', () {
    test('每个主体恰有三个动作，且互不重叠', () {
      for (final role in [
        RoleId.regulator,
        RoleId.financing,
        RoleId.investor,
      ]) {
        expect(SubjectAction.forRole(role).length, 3, reason: role.wire);
      }
      final all = SubjectAction.values.map((a) => a.wire).toList();
      expect(all.toSet().length, all.length, reason: '动作名不得重复');
    });

    test('跨主体动作一律拒绝（不猜）', () {
      // investor 的 Buy 不属于 regulator。
      expect(SubjectAction.parseFor(RoleId.regulator, 'Buy'), isNull);
      expect(SubjectAction.parseFor(RoleId.regulator, 'In')?.label, '准入');
      expect(SubjectAction.parseFor(RoleId.investor, 'Sell')?.label, '卖出');
      expect(
        SubjectAction.parseFor(RoleId.financing, 'Equilibrium')?.label,
        '均衡',
      );
    });

    test('非法/缺失值返回 null 而不是默认动作', () {
      expect(SubjectAction.parseFor(RoleId.regulator, 'buy'), isNull);
      expect(SubjectAction.parseFor(RoleId.regulator, null), isNull);
      expect(SubjectAction.parseFor(RoleId.regulator, 42), isNull);
      expect(SubjectAction.parseFor(RoleId.regulator, 'Hedge'), isNull);
    });
  });
}
