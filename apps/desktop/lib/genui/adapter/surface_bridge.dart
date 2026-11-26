/// A2UI 适配层（docs/03 §10 / docs/04）：消息解析 → catalog 严格校验 → 增量渲染。
///
/// 职责边界：
/// - 模型不直接产出 A2UI 消息；本层接收领域对象映射后的 A2UI 消息；
/// - **未登记组件显式拒绝并报错**，不得静默丢弃；
/// - 流式增量渲染；中断保留已有内容并标注「已中断」。
///
/// 本目录是唯一允许依赖 `package:genui/` 的位置（ADR-002）；为保持可测试性，
/// 这里用纯 Dart 表示消息，再由外壳交给 genui 的 SurfaceController。
library;

import 'dart:async';

import 'package:genui/genui.dart'
    show A2uiMessageEvent, GenerationEvent, TextEvent;

import '../catalog/cbr_catalog.dart';

/// 一个 A2UI 组件节点。
final class A2uiComponent {
  /// 创建节点。
  const A2uiComponent({
    required this.id,
    required this.kind,
    this.children = const [],
    this.props = const {},
  });

  /// 节点 id（kebab-case）。
  final String id;

  /// 组件 kind（UpperCamelCase，必须在 catalog 内）。
  final String kind;

  /// 子节点 id。
  final List<String> children;

  /// props。
  final Map<String, Object?> props;
}

/// A2UI 消息种类。
enum A2uiMessageType {
  createSurface('createSurface'),
  updateComponents('updateComponents'),
  updateDataModel('updateDataModel'),
  deleteSurface('deleteSurface');

  const A2uiMessageType(this.wire);

  /// JSON 字面量。
  final String wire;
}

/// 解析后的 A2UI 消息。
final class A2uiMessage {
  /// 创建消息。
  const A2uiMessage({
    required this.type,
    required this.surfaceId,
    this.catalogId,
    this.components = const [],
    this.path,
    this.value,
  });

  /// 从 JSON 解析；未知或畸形消息抛 [A2uiFormatException]。
  factory A2uiMessage.parse(Object? json) {
    if (json is! Map<String, Object?>) {
      throw const A2uiFormatException('A2UI 消息必须是 JSON 对象');
    }
    final version = json['version'];
    if (version != 'v0.9') {
      throw A2uiFormatException('A2UI 协议版本不匹配：$version（期望 v0.9）');
    }
    for (final type in A2uiMessageType.values) {
      final body = json[type.wire];
      if (body is! Map<String, Object?>) {
        continue;
      }
      final surfaceId = body['surfaceId'];
      if (surfaceId is! String || surfaceId.isEmpty) {
        throw A2uiFormatException('${type.wire} 缺少 surfaceId');
      }
      switch (type) {
        case A2uiMessageType.createSurface:
          return A2uiMessage(
            type: type,
            surfaceId: surfaceId,
            catalogId: body['catalogId'] as String?,
          );
        case A2uiMessageType.updateComponents:
          final raw = body['components'];
          if (raw is! List<Object?>) {
            throw const A2uiFormatException('updateComponents 缺少 components');
          }
          return A2uiMessage(
            type: type,
            surfaceId: surfaceId,
            components: [for (final item in raw) _parseComponent(item)],
          );
        case A2uiMessageType.updateDataModel:
          return A2uiMessage(
            type: type,
            surfaceId: surfaceId,
            path: body['path'] as String?,
            value: body['value'],
          );
        case A2uiMessageType.deleteSurface:
          return A2uiMessage(type: type, surfaceId: surfaceId);
      }
    }
    throw const A2uiFormatException('未知 A2UI 消息类型');
  }

  static A2uiComponent _parseComponent(Object? raw) {
    if (raw is! Map<String, Object?>) {
      throw const A2uiFormatException('组件必须是 JSON 对象');
    }
    final id = raw['id'];
    final kind = raw['component'];
    if (id is! String || kind is! String) {
      throw const A2uiFormatException('组件缺少 id 或 component');
    }
    final children = raw['children'];
    return A2uiComponent(
      id: id,
      kind: kind,
      children: children is List<Object?>
          ? children.whereType<String>().toList()
          : const [],
      props: {
        for (final entry in raw.entries)
          if (entry.key != 'id' &&
              entry.key != 'component' &&
              entry.key != 'children')
            entry.key: entry.value,
      },
    );
  }

  /// 消息类型。
  final A2uiMessageType type;

  /// surface id。
  final String surfaceId;

  /// catalog id（createSurface）。
  final String? catalogId;

  /// 组件（updateComponents）。
  final List<A2uiComponent> components;

  /// 数据路径（updateDataModel）。
  final String? path;

  /// 数据值（updateDataModel）。
  final Object? value;
}

/// A2UI 格式/校验错误。
final class A2uiFormatException implements Exception {
  /// 创建错误。
  const A2uiFormatException(this.message, {this.surfaceId, this.component});

  /// 说明。
  final String message;

  /// surface id。
  final String? surfaceId;

  /// 组件 kind。
  final String? component;

  @override
  String toString() => 'A2uiFormatException: $message';
}

/// surface 快照（增量渲染的产物）。
final class SurfaceState {
  /// 创建快照。
  const SurfaceState({
    required this.surfaceId,
    required this.components,
    this.data = const {},
    this.interrupted = false,
    this.error,
  });

  /// surface id。
  final String surfaceId;

  /// 节点 id → 组件。
  final Map<String, A2uiComponent> components;

  /// 数据模型。
  final Map<String, Object?> data;

  /// 是否被中断（保留已有内容）。
  final bool interrupted;

  /// 渲染错误。
  final String? error;

  /// 复制并替换。
  SurfaceState copyWith({
    Map<String, A2uiComponent>? components,
    Map<String, Object?>? data,
    bool? interrupted,
    String? error,
  }) => SurfaceState(
    surfaceId: surfaceId,
    components: components ?? this.components,
    data: data ?? this.data,
    interrupted: interrupted ?? this.interrupted,
    error: error ?? this.error,
  );
}

/// 校验结果：通过的组件 + 被拒组件（显式报错）。
final class GuardResult {
  /// 创建结果。
  const GuardResult({required this.accepted, required this.rejected});

  /// 通过。
  final List<A2uiComponent> accepted;

  /// 被拒（kind + 原因）。
  final List<(A2uiComponent, String)> rejected;
}

/// 组件白名单守卫。
final class CbrVisualGuard {
  /// 创建守卫。
  const CbrVisualGuard(this.catalog);

  /// 目录。
  final CbrCatalog catalog;

  /// 校验组件：未登记 → 拒绝；越界 props → 丢弃该参数（不是整组件）。
  GuardResult validate(Iterable<A2uiComponent> components) {
    final accepted = <A2uiComponent>[];
    final rejected = <(A2uiComponent, String)>[];
    for (final component in components) {
      final spec = catalog.find(component.kind);
      if (spec == null) {
        rejected.add((component, '组件未登记：${component.kind}'));
        continue;
      }
      final filtered = <String, Object?>{
        for (final entry in component.props.entries)
          if (spec.props.contains(entry.key)) entry.key: entry.value,
      };
      accepted.add(
        A2uiComponent(
          id: component.id,
          kind: component.kind,
          children: component.children,
          props: filtered,
        ),
      );
    }
    return GuardResult(accepted: accepted, rejected: rejected);
  }
}

/// 流式渲染器：把 A2UI 消息流增量渲染成 surface 快照流。
///
/// 中断（取消 / 出错）时保留已有内容，并置 `interrupted=true`。
final class A2uiStreamRenderer {
  /// 创建渲染器。
  A2uiStreamRenderer({required this.guard});

  /// 组件守卫。
  final CbrVisualGuard guard;

  /// 渲染一条消息流；返回快照流。
  ///
  /// 未登记组件：**整条 surface 拒绝并报错**（fail-closed），不静默丢弃。
  Stream<SurfaceState> render(Stream<A2uiMessage> messages) {
    final controller = StreamController<SurfaceState>();
    final surfaces = <String, SurfaceState>{};
    late StreamSubscription<A2uiMessage> subscription;
    var cancelled = false;

    void emit(String surfaceId) {
      final state = surfaces[surfaceId];
      if (state != null && !controller.isClosed) {
        // 中断后仍可能有一条在途消息完成；一律以「已中断」状态输出，
        // 保留已渲染内容。
        controller.add(cancelled ? state.copyWith(interrupted: true) : state);
      }
    }

    Future<void> onMessage(A2uiMessage message) async {
      if (cancelled) {
        return;
      }
      try {
        switch (message.type) {
          case A2uiMessageType.createSurface:
            surfaces[message.surfaceId] = SurfaceState(
              surfaceId: message.surfaceId,
              components: const {},
            );
            emit(message.surfaceId);
          case A2uiMessageType.updateComponents:
            final result = guard.validate(message.components);
            if (result.rejected.isNotEmpty) {
              final reasons = result.rejected
                  .map((entry) => entry.$2)
                  .join('；');
              surfaces[message.surfaceId] =
                  (surfaces[message.surfaceId] ??
                          SurfaceState(
                            surfaceId: message.surfaceId,
                            components: const {},
                          ))
                      .copyWith(error: '渲染被拒绝：$reasons');
              emit(message.surfaceId);
              controller.addError(
                A2uiFormatException(
                  '未登记组件，整条 surface 拒绝渲染：$reasons',
                  surfaceId: message.surfaceId,
                ),
              );
              return;
            }
            final current =
                surfaces[message.surfaceId] ??
                SurfaceState(
                  surfaceId: message.surfaceId,
                  components: const {},
                );
            surfaces[message.surfaceId] = current.copyWith(
              components: {
                ...current.components,
                for (final component in result.accepted)
                  component.id: component,
              },
            );
            emit(message.surfaceId);
          case A2uiMessageType.updateDataModel:
            final current =
                surfaces[message.surfaceId] ??
                SurfaceState(
                  surfaceId: message.surfaceId,
                  components: const {},
                );
            surfaces[message.surfaceId] = current.copyWith(
              data: _patch(current.data, message.path, message.value),
            );
            emit(message.surfaceId);
          case A2uiMessageType.deleteSurface:
            surfaces.remove(message.surfaceId);
        }
      } catch (error, stack) {
        if (!controller.isClosed) {
          controller.addError(error, stack);
        }
      }
    }

    subscription = messages.listen(
      (message) => unawaited(onMessage(message)),
      onError: (Object error, StackTrace stack) {
        cancelled = true;
        for (final surfaceId in surfaces.keys.toList()) {
          emit(surfaceId);
        }
        if (!controller.isClosed) {
          controller.addError(error, stack);
        }
      },
      onDone: () {
        if (!controller.isClosed) {
          controller.close();
        }
      },
      cancelOnError: false,
    );
    controller.onCancel = () {
      cancelled = true;
      unawaited(subscription.cancel());
    };
    return controller.stream;
  }

  /// 标记中断：保留已有内容并标注。
  static SurfaceState interrupt(SurfaceState state) =>
      state.copyWith(interrupted: true);

  Map<String, Object?> _patch(
    Map<String, Object?> data,
    String? path,
    Object? value,
  ) {
    if (path == null || path.isEmpty || path == '/') {
      return value is Map<String, Object?> ? value : data;
    }
    final segments = path.split('/').where((s) => s.isNotEmpty).toList();
    final result = <String, Object?>{...data};
    Map<String, Object?> cursor = result;
    for (var i = 0; i < segments.length - 1; i++) {
      final next = cursor[segments[i]];
      final child = next is Map<String, Object?>
          ? {...next}
          : <String, Object?>{};
      cursor[segments[i]] = child;
      cursor = child;
    }
    if (segments.isNotEmpty) {
      cursor[segments.last] = value;
    }
    return result;
  }
}

/// 把 genui 的解析事件转成 A2UI 消息流（文本块原样透传为注释）。
Stream<A2uiMessage> fromGenerationEvents(
  Stream<GenerationEvent> events, {
  List<String>? textLog,
}) => events.transform(
  StreamTransformer<GenerationEvent, A2uiMessage>.fromHandlers(
    handleData: (event, sink) {
      if (event is TextEvent) {
        textLog?.add(event.text);
        return;
      }
      // 非文本事件：仅 genui 的 A2uiMessageEvent 会进入这里。它携带
      // core.A2uiMessage，由外壳的 A2uiTransportAdapter 转成 JSON 后
      // 再走本层解析；本层不直接依赖 a2ui_core。
      if (event is! A2uiMessageEvent) {
        return;
      }
      sink.add(A2uiMessage.parse(event.message.toJson()));
    },
  ),
);

/// 领域对象 → A2UI 消息映射（SurfaceBridge 的最小实现）。
final class SurfaceBridge {
  /// 创建桥接器。
  const SurfaceBridge();

  /// 构造 createSurface 消息。
  A2uiMessage createSurface(String surfaceId) => A2uiMessage(
    type: A2uiMessageType.createSurface,
    surfaceId: surfaceId,
    catalogId: 'cbr.basic',
  );

  /// 构造 updateComponents 消息。
  A2uiMessage updateComponents(
    String surfaceId,
    List<A2uiComponent> components,
  ) => A2uiMessage(
    type: A2uiMessageType.updateComponents,
    surfaceId: surfaceId,
    components: components,
  );

  /// 构造 updateDataModel 消息。
  A2uiMessage updateDataModel(String surfaceId, String path, Object? value) =>
      A2uiMessage(
        type: A2uiMessageType.updateDataModel,
        surfaceId: surfaceId,
        path: path,
        value: value,
      );

  /// 序列化为 A2UI v0.9 JSON（交给 genui 的 SurfaceController）。
  Map<String, Object?> toWire(A2uiMessage message) => {
    'version': 'v0.9',
    message.type.wire: {
      'surfaceId': message.surfaceId,
      if (message.type == A2uiMessageType.createSurface) ...{
        'catalogId': message.catalogId ?? 'cbr.basic',
        'sendDataModel': true,
      },
      if (message.type == A2uiMessageType.updateComponents)
        'components': [
          for (final component in message.components)
            {
              'id': component.id,
              'component': component.kind,
              if (component.children.isNotEmpty) 'children': component.children,
              ...component.props,
            },
        ],
      if (message.type == A2uiMessageType.updateDataModel) ...{
        'path': message.path,
        'value': message.value,
      },
    },
  };
}
