import 'package:cbr_maw/genui/actions/action_dispatcher.dart';
import 'package:cbr_maw/genui/adapter/surface_bridge.dart';
import 'package:cbr_maw/genui/catalog/cbr_catalog.dart';
import 'package:cbr_maw_a2ui_catalog/cbr_maw_a2ui_catalog.dart'
    show A2uiValidationError;
import 'package:flutter_test/flutter_test.dart';
import 'package:genui/genui.dart' show DataPath;

void main() {
  group('A2UI 消息入口（官方 SurfaceController 承载）', () {
    test('工厂方法产出官方协议消息，catalogId 指向 CBR catalog', () {
      final bridge = SurfaceBridge();
      addTearDown(bridge.dispose);

      final create = bridge.createSurface('s1');
      expect(create.surfaceId, 's1');
      expect(create.catalogId, 'cn.cbrmaw.a2ui.catalog');

      final update = bridge.updateComponents('s1', [
        {'id': 'root', 'component': 'Column', 'children': <String>[]},
      ]);
      expect(update.components, hasLength(1));
    });

    test('协议版本不匹配 → 明确报错', () {
      final bridge = SurfaceBridge();
      addTearDown(bridge.dispose);
      expect(
        () => bridge.handleJson({
          'version': 'v0.8',
          'createSurface': {'surfaceId': 's1', 'catalogId': 'cbr.basic'},
        }),
        throwsA(isA<A2uiValidationError>()),
      );
    });

    test('合法 surface 由 SurfaceController 建立组件快照', () {
      final bridge = SurfaceBridge();
      addTearDown(bridge.dispose);
      bridge.handleMessage(bridge.createSurface('s1'));
      bridge.handleMessage(
        bridge.updateComponents('s1', [
          {
            'id': 'root',
            'component': 'Column',
            'children': <String>['t1'],
          },
          {'id': 't1', 'component': 'Text', 'text': 'synthetic'},
        ]),
      );

      final definition = bridge.contextFor('s1').definition.value;
      expect(definition, isNotNull);
      expect(definition!.components.keys, containsAll(<String>['root', 't1']));
      expect(definition.components['t1']!.type, 'Text');
      expect(bridge.rejections, isEmpty);
    });

    test('updateDataModel 落到官方 data model', () {
      final bridge = SurfaceBridge();
      addTearDown(bridge.dispose);
      bridge.handleMessage(bridge.createSurface('s1'));
      bridge.handleMessage(
        bridge.updateComponents('s1', [
          {'id': 'root', 'component': 'Text', 'text': 'synthetic'},
        ]),
      );
      bridge.handleMessage(bridge.updateDataModel('s1', '/risk', 'high'));

      expect(
        bridge.contextFor('s1').dataModel.getValue<String>(DataPath('/risk')),
        'high',
      );
    });
  });

  group('未登记组件显式拒绝', () {
    test('白名单唯一真源是 cbrRegisteredComponentNames', () {
      final guard = CbrVisualGuard();
      expect(guard.allowedComponents.contains('Text'), isTrue);
      expect(guard.allowedComponents.contains('Column'), isTrue);
      expect(guard.allowedComponents.contains('EvilWidget'), isFalse);
    });

    test('拒收发生在进入 SurfaceController 之前，并记录原因', () {
      final bridge = SurfaceBridge();
      addTearDown(bridge.dispose);
      bridge.handleMessage(bridge.createSurface('s1'));
      bridge.handleMessage(
        bridge.updateComponents('s1', [
          {'id': 'root', 'component': 'EvilWidget'},
        ]),
      );

      // surface 仍然存活，但未登记组件没有进入渲染状态。
      expect(bridge.activeSurfaceIds, contains('s1'));
      expect(
        bridge.contextFor('s1').definition.value?.components,
        isNot(contains('root')),
      );

      final rejection = bridge.rejections.single;
      expect(rejection.surfaceId, 's1');
      expect(rejection.componentId, 'root');
      expect(rejection.componentKind, 'EvilWidget');
      expect(rejection.reason, contains('未登记'));
      expect(rejection.toString(), contains('renderError'));
    });

    test('同一批里有一个未登记组件 → 整批拒绝（fail-closed）', () {
      final bridge = SurfaceBridge();
      addTearDown(bridge.dispose);
      bridge.handleMessage(bridge.createSurface('s1'));
      bridge.handleMessage(
        bridge.updateComponents('s1', [
          {'id': 'root', 'component': 'Column', 'children': <String>[]},
          {'id': 't1', 'component': 'Text', 'text': 'synthetic'},
          {'id': 'x', 'component': 'EvilWidget'},
        ]),
      );

      expect(bridge.contextFor('s1').definition.value?.components, isEmpty);
      expect(bridge.rejections.single.componentKind, 'EvilWidget');
    });
  });

  group('动作风险分级与白名单', () {
    ActionDispatcher dispatcher({
      ConfirmHandler? confirm,
      List<AuditEvent>? audit,
    }) => ActionDispatcher(
      actions: [
        const ActionSpec(actionId: 'nav.open-surface', risk: ActionRisk.l0),
        ActionSpec(
          actionId: 'workspace.save-decision',
          risk: ActionRisk.l1,
          idempotent: true,
          handler: (_) async => 'row-1',
        ),
        ActionSpec(
          actionId: 'workspace.purge',
          risk: ActionRisk.l2,
          idempotent: true,
          handler: (_) async => 'purged',
        ),
      ],
      confirm: confirm,
      auditSink: audit?.add,
    );

    test('未登记动作一律拒绝', () async {
      final result = await dispatcher().dispatch(
        actionId: 'evil.action',
        payload: const {},
      );
      expect(result.ok, isFalse);
      expect(result.reason, contains('白名单'));
    });

    test('L1 缺确认处理器 → 拒绝执行（fail-closed）', () async {
      final audit = <AuditEvent>[];
      final result = await dispatcher(
        audit: audit,
      ).dispatch(actionId: 'workspace.save-decision', payload: const {'id': 1});
      expect(result.ok, isFalse);
      expect(result.reason, contains('确认'));
      expect(audit.single.outcome, 'rejectedMissingConfirmer');
    });

    test('L1 用户取消 → 不执行', () async {
      final result = await dispatcher(confirm: (_, _) async => false)
          .dispatch(actionId: 'workspace.save-decision', payload: const {});
      expect(result.ok, isFalse);
      expect(result.reason, contains('取消'));
    });

    test('L2 需确认；确认后执行并写账本', () async {
      var confirmed = 0;
      final action = dispatcher(
        confirm: (_, _) async {
          confirmed++;
          return true;
        },
      );
      final result = await action.dispatch(
        actionId: 'workspace.purge',
        payload: const {},
        idempotencyKey: 'key-1',
      );
      expect(result.ok, isTrue);
      expect(confirmed, 1);
      expect(action.ledger('key-1')?.outcome, 'succeeded');
    });

    test('组件声明的更强风险级生效（L1 动作被组件声明抬到 L2）', () async {
      var confirmed = 0;
      final action = dispatcher(
        confirm: (_, _) async {
          confirmed++;
          return true;
        },
      );
      await action.dispatch(
        actionId: 'workspace.save-decision',
        payload: const {},
        componentRisk: ActionRisk.l2,
      );
      expect(confirmed, 1);
    });

    test('幂等：同 key 同参数重放返回上次结果，不同参数拒绝', () async {
      final action = dispatcher(confirm: (_, _) async => true);
      final first = await action.dispatch(
        actionId: 'workspace.save-decision',
        payload: const {'id': 1},
        idempotencyKey: 'k',
      );
      final replay = await action.dispatch(
        actionId: 'workspace.save-decision',
        payload: const {'id': 1},
        idempotencyKey: 'k',
      );
      final drift = await action.dispatch(
        actionId: 'workspace.save-decision',
        payload: const {'id': 2},
        idempotencyKey: 'k',
      );
      expect(first.resultRef, 'row-1');
      expect(replay.resultRef, 'row-1');
      expect(drift.ok, isFalse);
      expect(drift.reason, contains('漂移'));
    });

    test('L0 无需确认直接执行', () async {
      final result = await dispatcher().dispatch(
        actionId: 'nav.open-surface',
        payload: const {},
      );
      expect(result.ok, isTrue);
    });
  });
}
