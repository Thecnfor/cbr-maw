import 'dart:async';

import 'package:cbr_maw/genui/actions/action_dispatcher.dart';
import 'package:cbr_maw/genui/adapter/surface_bridge.dart';
import 'package:cbr_maw/genui/catalog/cbr_catalog.dart';
import 'package:flutter_test/flutter_test.dart';

A2uiMessage message(Map<String, Object?> body) => A2uiMessage.parse(body);

void main() {
  group('A2UI 消息解析', () {
    test('createSurface / updateComponents / updateDataModel 解析', () {
      final create = message({
        'version': 'v0.9',
        'createSurface': {'surfaceId': 's1', 'catalogId': 'cbr.basic'},
      });
      expect(create.type, A2uiMessageType.createSurface);

      final update = message({
        'version': 'v0.9',
        'updateComponents': {
          'surfaceId': 's1',
          'components': [
            {
              'id': 'root',
              'component': 'Column',
              'children': ['t1'],
            },
            {'id': 't1', 'component': 'Text', 'text': 'hi'},
          ],
        },
      });
      expect(update.components, hasLength(2));
      expect(update.components.first.children, ['t1']);

      final data = message({
        'version': 'v0.9',
        'updateDataModel': {
          'surfaceId': 's1',
          'path': '/risk',
          'value': 'high',
        },
      });
      expect(data.value, 'high');
    });

    test('协议版本不匹配 → 明确报错', () {
      expect(
        () => message({
          'version': 'v0.8',
          'createSurface': {'surfaceId': 's1'},
        }),
        throwsA(isA<A2uiFormatException>()),
      );
    });
  });

  group('未登记组件显式拒绝', () {
    test('守卫拒绝未登记组件', () {
      final guard = CbrVisualGuard(CbrCatalog.defaultCatalog);
      final result = guard.validate(const [
        A2uiComponent(id: 'x', kind: 'EvilWidget'),
        A2uiComponent(id: 'y', kind: 'Text', props: {'text': 'ok'}),
      ]);
      expect(result.accepted, hasLength(1));
      expect(result.rejected.single.$2, contains('未登记'));
    });

    test('流渲染：未登记组件 → 整条 surface 拒绝并报错，不静默丢弃', () async {
      final renderer = A2uiStreamRenderer(
        guard: CbrVisualGuard(CbrCatalog.defaultCatalog),
      );
      final controller = StreamController<A2uiMessage>();
      final states = <SurfaceState>[];
      final errors = <Object>[];

      final subscription = renderer
          .render(controller.stream)
          .listen(states.add, onError: errors.add);
      controller.add(
        message({
          'version': 'v0.9',
          'createSurface': {'surfaceId': 's1'},
        }),
      );
      controller.add(
        message({
          'version': 'v0.9',
          'updateComponents': {
            'surfaceId': 's1',
            'components': [
              {'id': 'root', 'component': 'EvilWidget'},
            ],
          },
        }),
      );
      await Future<void>.delayed(Duration.zero);
      await controller.close();
      await subscription.asFuture<void>();

      expect(errors.whereType<A2uiFormatException>(), isNotEmpty);
      expect(states.last.error, contains('未登记'));
    });
  });

  group('流式增量渲染与中断', () {
    test('增量更新 + updateDataModel 只 patch 数值', () async {
      final renderer = A2uiStreamRenderer(
        guard: CbrVisualGuard(CbrCatalog.defaultCatalog),
      );
      final states = await renderer
          .render(
            Stream.fromIterable([
              message({
                'version': 'v0.9',
                'createSurface': {'surfaceId': 's1'},
              }),
              message({
                'version': 'v0.9',
                'updateComponents': {
                  'surfaceId': 's1',
                  'components': [
                    {
                      'id': 'root',
                      'component': 'Column',
                      'children': ['risk'],
                    },
                    {'id': 'risk', 'component': 'Text', 'text': 'medium'},
                  ],
                },
              }),
              message({
                'version': 'v0.9',
                'updateDataModel': {
                  'surfaceId': 's1',
                  'path': '/risk',
                  'value': 'high',
                },
              }),
            ]),
          )
          .toList();

      expect(states.last.components, hasLength(2));
      expect(states.last.data['risk'], 'high');
    });

    test('中断保留已有内容并标注已中断', () async {
      final renderer = A2uiStreamRenderer(
        guard: CbrVisualGuard(CbrCatalog.defaultCatalog),
      );
      final controller = StreamController<A2uiMessage>();
      final states = <SurfaceState>[];
      final subscription = renderer
          .render(controller.stream)
          .listen(states.add, onError: (Object _) {});

      controller.add(
        message({
          'version': 'v0.9',
          'createSurface': {'surfaceId': 's1'},
        }),
      );
      controller.add(
        message({
          'version': 'v0.9',
          'updateComponents': {
            'surfaceId': 's1',
            'components': [
              {'id': 'root', 'component': 'Text', 'text': '已渲染'},
            ],
          },
        }),
      );
      await Future<void>.delayed(Duration.zero);
      controller.addError(StateError('流中断'));
      await Future<void>.delayed(Duration.zero);
      await subscription.cancel();

      expect(states.last.interrupted, isTrue);
      expect(states.last.components, isNotEmpty);
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

  group('SurfaceBridge', () {
    test('toWire 产出 A2UI v0.9 线格式', () {
      const bridge = SurfaceBridge();
      final wire = bridge.toWire(
        bridge.updateComponents('s1', const [
          A2uiComponent(id: 'root', kind: 'Column', children: ['t']),
          A2uiComponent(id: 't', kind: 'Text', props: {'text': 'hi'}),
        ]),
      );
      expect(wire['version'], 'v0.9');
      final body = wire['updateComponents'] as Map<String, Object?>;
      expect(body['surfaceId'], 's1');
      expect((body['components'] as List<Object?>), hasLength(2));
    });
  });
}
