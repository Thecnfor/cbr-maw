import 'package:cbr_maw_a2ui_catalog/cbr_maw_a2ui_catalog.dart';
import 'package:flutter_test/flutter_test.dart';

/// 构造一条最小 component 记录。
({String id, String type, Map<String, Object?> props}) component(
  String id,
  String type, [
  Map<String, Object?> props = const <String, Object?>{},
]) => (id: id, type: type, props: props);

void main() {
  group('catalog 注册表（docs/06 §9 VC-6）', () {
    test('组件名唯一且非空', () {
      final names = cbrCatalogItems.map((item) => item.name).toList();
      expect(names.toSet().length, names.length);
      expect(names, isNotEmpty);
    });

    test('覆盖 docs/02 F3-3 要求的全部形态', () {
      final names = cbrRegisteredComponentNames;
      const required = <String>{
        'RoleCard',
        'MetricTable',
        'ClaimTable',
        'DataCardList',
        'EvidenceList',
        'ConflictDiff',
        'CrossValidationList',
        'VerificationSummary',
        'DecisionSummary',
        'CostMeter',
        'ConfirmCard',
        'ChartCard',
        'DataTable',
        'SourceChip',
        'EmptyState',
        'ErrorState',
        'AccessRequired',
        'ProgressBar',
        'Tag',
        'Divider',
        'Text',
      };
      expect(
        names.containsAll(required),
        isTrue,
        reason: '缺少：${required.difference(names)}',
      );
    });

    test('每个组件都声明了 state 字段（VC-3）', () {
      for (final item in cbrCatalogItems) {
        final props =
            (item.dataSchema.value['properties'] as Map<String, Object?>?) ??
            const <String, Object?>{};
        // 少数纯展示组件（Text / Divider / Tag）无状态，其余必须有 state。
        // 纯展示与「本身就是状态」的组件不需要 state 字段。
        const stateless = <String>{
          'Text',
          'Divider',
          'Tag',
          'EmptyState',
          'ErrorState',
          'AccessRequired',
          // A2UI 协议布局容器：无业务状态，状态由子组件表达。
          'Column',
          'Row',
          'Card',
          'List',
          'Tabs',
        };
        if (stateless.contains(item.name)) {
          continue;
        }
        expect(props.containsKey('state'), isTrue, reason: item.name);
      }
    });

    test('每个组件都有唯一 kebab-case id，且与组件名一一对应', () {
      expect(cbrComponentKebabIds.keys.toSet(), cbrRegisteredComponentNames);
      final kebab = RegExp(r'^[a-z][a-z0-9]*(-[a-z0-9]+)*$');
      final values = cbrComponentKebabIds.values.toList();
      expect(values.toSet().length, values.length, reason: 'kebab id 必须唯一');
      for (final id in values) {
        expect(kebab.hasMatch(id), isTrue, reason: id);
      }
    });

    test('版本号独立于 A2UI 协议版本', () {
      expect(cbrCatalogVersion, isNotEmpty);
      expect(cbrCatalogId, contains('.'));
    });
  });

  group('strict 校验拒绝未登记内容（docs/02 F3-2、docs/06 VC-5）', () {
    test('已登记组件通过', () {
      final result = cbrValidateStrict(
        surfaceId: 's1',
        components: <({String id, String type, Map<String, Object?> props})>[
          component('root', 'RoleCard', <String, Object?>{
            'role': 'financing',
            'headline': '测试',
          }),
        ],
      );
      expect(result.isAccepted, isTrue);
    });

    test('未登记组件被显式拒绝，而不是静默丢弃', () {
      final result = cbrValidateStrict(
        surfaceId: 's1',
        components: <({String id, String type, Map<String, Object?> props})>[
          component('root', 'FancyGradientCard'),
        ],
      );
      expect(result.isAccepted, isFalse);
      expect(result.violation!.kind, CbrStrictViolationKind.unknownComponent);
      expect(result.violation!.detail, contains('FancyGradientCard'));
      expect(result.violation!.toString(), contains('renderError'));
    });

    test('未登记参数被拒绝（VC-2：颜色/字号等一律拒绝）', () {
      final result = cbrValidateStrict(
        surfaceId: 's2',
        components: <({String id, String type, Map<String, Object?> props})>[
          component('root', 'Text', <String, Object?>{
            'text': 'x',
            'color': '#FF0000',
          }),
        ],
      );
      expect(result.isAccepted, isFalse);
      expect(result.violation!.kind, CbrStrictViolationKind.unknownProperty);
      expect(result.violation!.detail, contains('color'));
    });

    test('非 kebab-case 节点 id 被拒绝', () {
      final result = cbrValidateStrict(
        surfaceId: 's3',
        components: <({String id, String type, Map<String, Object?> props})>[
          component('rootNode', 'Text', <String, Object?>{'text': 'x'}),
        ],
      );
      expect(result.isAccepted, isFalse);
      expect(result.violation!.kind, CbrStrictViolationKind.invalidComponentId);
    });

    test('允许的参数集由 schema 推导，不重复维护', () {
      final allowed = cbrAllowedPropsFor('RoleCard');
      expect(
        allowed,
        containsAll(<String>['role', 'headline', 'riskLevel', 'state', 'id']),
      );
      expect(allowed, isNot(contains('color')));
      expect(allowed, isNot(contains('fontSize')));
      expect(cbrAllowedPropsFor('不存在'), isEmpty);
    });
  });

  group('catalog 构造', () {
    test('buildCbrCatalog 的 catalogId 与组件数量正确', () {
      final catalog = buildCbrCatalog();
      expect(catalog.catalogId, cbrCatalogId);
      expect(catalog.items.length, cbrCatalogItems.length);
      expect(catalog.systemPromptFragments, isNotEmpty);
    });

    test('toCapabilitiesJson 暴露全部组件 schema', () {
      final catalog = buildCbrCatalog();
      final json = catalog.toCapabilitiesJson();
      final components = json['components'] as Map<String, Object?>;
      expect(components.keys.toSet(), cbrRegisteredComponentNames);
    });
  });
}
