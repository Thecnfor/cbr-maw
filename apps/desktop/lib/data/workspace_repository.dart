import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../core/app_log.dart';
import '../core/errors.dart';
import 'sidecar/sidecar_supervisor.dart';

/// 工作台数据仓储：只读真实 sidecar 数据，拿不到就显式失败。
///
/// 严禁在这里编造任何数值；调用方拿到错误后必须渲染「需授权/不可达/缺失」。
final class WorkspaceRepository {
  WorkspaceRepository({
    required this.supervisor,
    required this.log,
    this.collector,
  });

  final SidecarSupervisor supervisor;

  /// 采集器通道：`sources.*` / `collect.run` / `inbox.ingest` 只在它那里。
  ///
  /// 这些方法与 kernel 的 `db.*` / `tools.invoke` 分属两个 sidecar；
  /// 此前全部发往 kernel，导致来源台账与抓取链路在桌面端不可用。
  final SidecarSupervisor? collector;

  /// 开发日志。
  final AppLog log;

  /// 三库记忆统计（kernel `memory.stats`）。
  Future<Map<String, Object?>> memoryStats() => _call(
    'memory.stats',
    const <String, Object?>{},
    (payload) => payload is Map<String, Object?> ? payload : const {},
  );

  /// 三库记忆检索（kernel `memory.search`）。
  Future<List<Map<String, Object?>>> memorySearch({
    required String asOf,
    required String query,
    String? store,
    int topK = 8,
  }) => _call(
    'memory.search',
    {'as_of': asOf, 'query': query, 'store': ?store, 'top_k': topK},
    (payload) {
      final hits = payload is Map<String, Object?> ? payload['hits'] : null;
      return hits is List
          ? hits.whereType<Map<String, Object?>>().toList(growable: false)
          : const <Map<String, Object?>>[];
    },
  );

  Future<WorkspaceInfoResult> workspaceInfo() => _call(
    'workspace.info',
    const WorkspaceInfoParams().toJson(),
    WorkspaceInfoResult.parse,
  );

  Future<List<SourceLedgerEntry>> sources({bool includeDisabled = true}) =>
      _collect(
        'sources.list',
        SourcesListParams(includeDisabled: includeDisabled).toJson(),
        (payload) => SourcesListResult.parse(payload).sources,
      );

  Future<List<HealthEntry>> sourcesHealth() => _collect(
    'sources.health',
    const SourcesHealthParams().toJson(),
    (payload) => SourcesHealthResult.parse(payload).entries,
  );

  Future<List<SourceLedgerEntry>> dataCards() => _call(
    'sources.list',
    SourcesListParams(includeDisabled: true).toJson(),
    (payload) => SourcesListResult.parse(payload).sources,
  );

  Future<DbQueryResult> query({
    required DbView view,
    required String asOf,
    Map<String, Object?>? filters,
    int limit = 200,
  }) => _call(
    'db.query',
    DbQueryParams(
      view: view,
      filters: filters,
      asOf: asOf,
      limit: limit,
    ).toJson(),
    DbQueryResult.parse,
  );

  Future<InboxIngestResult> ingestInbox({
    required String path,
    String? declaredSource,
    String? asOf,
  }) => _collect(
    'inbox.ingest',
    InboxIngestParams(
      path: path,
      declaredSource: declaredSource,
      asOf: asOf,
    ).toJson(),
    InboxIngestResult.parse,
  );

  /// 发往 collector 的调用；未配置 collector 时显式失败（不静默回落到 kernel）。
  Future<T> _collect<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) {
    final target = collector;
    if (target == null) {
      throw AppError.unavailable(
        code: 'E_COLLECTOR_UNAVAILABLE',
        what: '采集器未就绪',
        why: '当前会话未启动 collector sidecar',
        next: '请确认安装包内含 collector，或重新启动应用',
      );
    }
    return _callOn(target, method, params, parse);
  }

  Future<T> _call<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) => _callOn(supervisor, method, params, parse);

  Future<T> _callOn<T>(
    SidecarSupervisor target,
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) async {
    try {
      return await target.callTyped(method, params, parse);
    } on AppError catch (e) {
      log.error('$method 失败', error: e);
      rethrow;
    }
  }
}
