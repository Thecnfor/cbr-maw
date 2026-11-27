/// A2UI 适配层（docs/03 §10 / docs/04 / ADR-002）：白名单守卫 → 官方渲染。
///
/// 职责边界：
/// - 消息解析、组件树与数据模型状态、增量渲染全部由 `package:genui` 的
///   [SurfaceController] 承担，本层不再手写协议解析与 patch 状态机；
/// - 本层只保留安全边界：**渲染前**按 `cbrRegisteredComponentNames` 拒收未登记
///   组件。命中即整条 `updateComponents` 不进入 controller（fail-closed），
///   并记录 [RenderRejection]（原因可读、可上报），绝不静默丢弃；
/// - 本目录是唯一允许依赖 `package:genui/` 的位置（ADR-002）。
library;

import 'dart:async';

import 'package:cbr_maw_a2ui_catalog/cbr_maw_a2ui_catalog.dart'
    show
        A2uiMessage,
        CreateSurfaceMessage,
        DeleteSurfaceMessage,
        UpdateComponentsMessage,
        UpdateDataModelMessage,
        buildCbrCatalog,
        cbrCatalogId,
        cbrRegisteredComponentNames;
import 'package:genui/genui.dart'
    show
        A2uiMessageSink,
        A2uiValidationException,
        Catalog,
        SurfaceContext,
        SurfaceController,
        SurfaceUpdate,
        genUiLogger;

/// 一条渲染拒收记录（`renderError{surfaceId}` 的代码侧载体）。
final class RenderRejection {
  /// 创建记录。
  const RenderRejection({
    required this.surfaceId,
    required this.componentId,
    required this.componentKind,
    required this.reason,
  });

  /// surface id。
  final String surfaceId;

  /// 节点 id（线路层，kebab-case）。
  final String componentId;

  /// 组件类型（UpperCamelCase）。
  final String componentKind;

  /// 拒收原因（面向日志与模型反馈）。
  final String reason;

  /// 线路层错误形状（与 docs/06 §9 VC-5 的 `renderError` 对齐）。
  Map<String, Object?> toJson() => {
    'surfaceId': surfaceId,
    'componentId': componentId,
    'componentKind': componentKind,
    'reason': reason,
  };

  @override
  String toString() =>
      'renderError{surfaceId: $surfaceId, componentId: $componentId, '
      'kind: $componentKind, reason: $reason}';
}

/// 组件白名单守卫（安全边界）。
///
/// 白名单唯一真源：[cbrRegisteredComponentNames]。
final class CbrVisualGuard {
  /// 创建守卫；测试可注入更小的集合。
  CbrVisualGuard({Set<String>? allowedComponents})
    : allowedComponents = Set.unmodifiable(
        allowedComponents ?? cbrRegisteredComponentNames,
      );

  /// 允许渲染的组件类型。
  final Set<String> allowedComponents;

  /// 校验一组线路组件，返回全部拒收项（空列表 = 整批放行）。
  List<RenderRejection> validate(
    String surfaceId,
    Iterable<Map<String, Object?>> components,
  ) {
    final rejected = <RenderRejection>[];
    for (final component in components) {
      final rawId = component['id'];
      final rawKind = component['component'];
      final id = rawId is String && rawId.isNotEmpty ? rawId : '<missing-id>';
      final kind = rawKind is String && rawKind.isNotEmpty
          ? rawKind
          : '<missing-component>';
      if (rawId is! String || rawId.isEmpty) {
        rejected.add(
          RenderRejection(
            surfaceId: surfaceId,
            componentId: id,
            componentKind: kind,
            reason: '组件缺少非空 id',
          ),
        );
        continue;
      }
      if (rawKind is! String || rawKind.isEmpty) {
        rejected.add(
          RenderRejection(
            surfaceId: surfaceId,
            componentId: id,
            componentKind: kind,
            reason: '组件缺少 component 类型',
          ),
        );
        continue;
      }
      if (!allowedComponents.contains(rawKind)) {
        rejected.add(
          RenderRejection(
            surfaceId: surfaceId,
            componentId: id,
            componentKind: rawKind,
            reason: '组件未登记：$rawKind',
          ),
        );
      }
    }
    return rejected;
  }
}

/// 领域对象 → A2UI 消息映射，并把消息交给官方 [SurfaceController]。
///
/// 公开入口（[handleMessage] / [handleJson]）在转发前执行白名单守卫。
final class SurfaceBridge implements A2uiMessageSink {
  /// 创建桥接器。
  ///
  /// [catalog] 缺省为 CBR 自有 catalog（`cn.cbrmaw.a2ui.catalog`）。
  SurfaceBridge({Catalog? catalog, CbrVisualGuard? guard})
    : catalog = catalog ?? buildCbrCatalog(),
      guard = guard ?? CbrVisualGuard() {
    controller = SurfaceController(catalogs: [this.catalog]);
  }

  /// 渲染所用的 catalog。
  final Catalog catalog;

  /// 组件白名单守卫。
  final CbrVisualGuard guard;

  /// 官方渲染 controller（widget 层通过 [contextFor] 取 `SurfaceContext`）。
  late final SurfaceController controller;

  final List<RenderRejection> _rejections = [];
  final StreamController<RenderRejection> _rejectionStream =
      StreamController<RenderRejection>.broadcast();

  /// 已记录的拒收（按发生顺序）。
  List<RenderRejection> get rejections => List.unmodifiable(_rejections);

  /// 拒收事件流。
  Stream<RenderRejection> get rejectionStream => _rejectionStream.stream;

  /// 当前存活的 surface id。
  Iterable<String> get activeSurfaceIds => controller.activeSurfaceIds;

  /// surface 变更事件（widget 层可据此重建列表）。
  Stream<SurfaceUpdate> get surfaceUpdates => controller.surfaceUpdates;

  /// 取单个 surface 的渲染上下文。
  SurfaceContext contextFor(String surfaceId) =>
      controller.contextFor(surfaceId);

  /// 接收 A2UI 消息：白名单守卫 → [SurfaceController]。
  @override
  void handleMessage(A2uiMessage message) {
    if (message is UpdateComponentsMessage) {
      final rejected = guard.validate(message.surfaceId, message.components);
      if (rejected.isNotEmpty) {
        for (final rejection in rejected) {
          _record(rejection);
        }
        // fail-closed：整条更新不进入 controller，surface 保持上一次的合法内容。
        return;
      }
    }
    controller.handleMessage(message);
  }

  /// 接收 A2UI v0.9 线格式 JSON（解析由官方 `a2ui_core` 完成）。
  ///
  /// 畸形或版本不匹配时抛 `A2uiValidationError`。
  void handleJson(Map<String, Object?> json) =>
      handleMessage(A2uiMessage.fromJson(json.cast<String, dynamic>()));

  /// 构造 createSurface 消息。
  CreateSurfaceMessage createSurface(String surfaceId) => CreateSurfaceMessage(
    surfaceId: surfaceId,
    catalogId: cbrCatalogId,
    sendDataModel: true,
  );

  /// 构造 updateComponents 消息。
  UpdateComponentsMessage updateComponents(
    String surfaceId,
    List<Map<String, Object?>> components,
  ) => UpdateComponentsMessage(
    surfaceId: surfaceId,
    components: [
      for (final component in components) Map<String, dynamic>.from(component),
    ],
  );

  /// 构造 updateDataModel 消息。
  UpdateDataModelMessage updateDataModel(
    String surfaceId,
    String? path,
    Object? value,
  ) => UpdateDataModelMessage(surfaceId: surfaceId, path: path, value: value);

  /// 构造 deleteSurface 消息。
  DeleteSurfaceMessage deleteSurface(String surfaceId) =>
      DeleteSurfaceMessage(surfaceId: surfaceId);

  /// 释放 controller 与事件流。
  Future<void> dispose() async {
    controller.dispose();
    await _rejectionStream.close();
  }

  void _record(RenderRejection rejection) {
    _rejections.add(rejection);
    genUiLogger.warning(rejection.toString());
    if (!_rejectionStream.isClosed) {
      _rejectionStream.add(rejection);
    }
    controller.reportError(
      A2uiValidationException(rejection.reason, surfaceId: rejection.surfaceId),
      StackTrace.current,
    );
  }
}
