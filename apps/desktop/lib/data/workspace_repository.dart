import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../core/app_log.dart';
import '../core/errors.dart';
import 'sidecar/sidecar_supervisor.dart';

/// 工作台数据仓储：只读真实 sidecar 数据，拿不到就显式失败。
///
/// 严禁在这里编造任何数值；调用方拿到错误后必须渲染「需授权/不可达/缺失」。
final class WorkspaceRepository {
  WorkspaceRepository({required this.supervisor, required this.log});

  final SidecarSupervisor supervisor;

  /// 开发日志。
  final AppLog log;

  Future<WorkspaceInfoResult> workspaceInfo() => _call(
    'workspace.info',
    const WorkspaceInfoParams().toJson(),
    WorkspaceInfoResult.parse,
  );

  Future<List<SourceLedgerEntry>> sources({bool includeDisabled = true}) =>
      _call(
        'sources.list',
        SourcesListParams(includeDisabled: includeDisabled).toJson(),
        (payload) => SourcesListResult.parse(payload).sources,
      );

  Future<List<HealthEntry>> sourcesHealth() => _call(
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
  }) => _call(
    'inbox.ingest',
    InboxIngestParams(
      path: path,
      declaredSource: declaredSource,
      asOf: asOf,
    ).toJson(),
    InboxIngestResult.parse,
  );

  Future<T> _call<T>(
    String method,
    Map<String, Object?> params,
    T Function(Object? payload) parse,
  ) async {
    try {
      return await supervisor.callTyped(method, params, parse);
    } on AppError catch (e) {
      log.error('$method 失败', error: e);
      rethrow;
    }
  }
}
