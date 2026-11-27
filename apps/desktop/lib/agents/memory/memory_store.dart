/// 三库记忆的 Dart 侧门面（kernel 是唯一写入者，这里只做协议适配）。
///
/// 设计（docs/24 §D5–D8）：
/// - **失败不阻断研判**：记忆不可用时返回空/记录失败，不抛给上层；
/// - **不用记忆冒充证据**：检索结果只作为「历史参考」注入，没有 `evidence_id`，
///   因此角色不能把它写进 claim 的 `evidence_ids`（引文核验会拒绝）；
/// - **PIT 由 kernel 强制**：这里只传 `as_of`，过滤在 LanceDB 侧做。
library;

import 'package:cbr_maw_contracts/contracts_dart.dart'
    show Failure, SidecarClient, Success;

/// 一条记忆记录。
final class MemoryRecord {
  /// 创建记录。
  const MemoryRecord({
    required this.id,
    required this.store,
    required this.asOf,
    required this.availableAt,
    required this.text,
    this.subject = 'all',
    this.kind = 'event',
    this.payload = const {},
  });

  /// 幂等主键。
  final String id;

  /// `mi` / `llr` / `hlr`。
  final String store;

  /// 记录所属决策时点（YYYY-MM-DD）。
  final String asOf;

  /// 可得时点（RFC3339）。
  final String availableAt;

  /// 正文。
  final String text;

  /// 主体视角。
  final String subject;

  /// 记录类型。
  final String kind;

  /// 库内差异字段。
  final Map<String, Object?> payload;

  /// JSON 形状（对齐 `memory.upsert` 契约）。
  Map<String, Object?> toJson() => {
    'id': id,
    'store': store,
    'as_of': asOf,
    'available_at': availableAt,
    'subject': subject,
    'kind': kind,
    'text': text,
    'payload': payload,
  };
}

/// 记忆检索命中。
final class MemoryHit {
  /// 创建命中。
  const MemoryHit({
    required this.id,
    required this.store,
    required this.asOf,
    required this.availableAt,
    required this.text,
    required this.score,
  });

  /// 记录 id。
  final String id;

  /// 库。
  final String store;

  /// 所属时点。
  final String asOf;

  /// 可得时点。
  final String availableAt;

  /// 正文。
  final String text;

  /// 距离（越小越相似）。
  final double score;

  /// 渲染成提示词参考块。
  String render() => '- [{asOf} · {store} · {id}] {text}'
      .replaceAll('{asOf}', asOf)
      .replaceAll('{store}', store)
      .replaceAll('{id}', id)
      .replaceAll('{text}', text);
}

/// 记忆存储接口（测试可注入内存实现）。
abstract interface class MemoryStore {
  /// 检索。
  Future<List<MemoryHit>> search({
    required String store,
    required DateTime asOf,
    required String query,
    int topK = 4,
  });

  /// 写入（幂等）。
  Future<void> upsert(List<MemoryRecord> rows);

  /// 是否可用（不可用时上层跳过，不伪造）。
  bool get available;
}

/// 走 sidecar 的实现。
final class SidecarMemoryStore implements MemoryStore {
  /// 创建。
  const SidecarMemoryStore(this.client);

  /// sidecar 客户端。
  final SidecarClient client;

  @override
  bool get available => true;

  @override
  Future<List<MemoryHit>> search({
    required String store,
    required DateTime asOf,
    required String query,
    int topK = 4,
  }) async {
    final results = await client.send('memory.search', {
      'as_of': asOf.toUtc().toIso8601String().substring(0, 10),
      'query': query,
      'store': store,
      'top_k': topK,
    }).toList();
    return switch (results.single) {
      Success(:final value) => _parse(value),
      Failure() => const [],
    };
  }

  static List<MemoryHit> _parse(Object? payload) {
    if (payload is! Map<String, Object?>) {
      return const [];
    }
    final hits = payload['hits'];
    if (hits is! List) {
      return const [];
    }
    return [
      for (final item in hits.whereType<Map<String, Object?>>())
        if (item['id'] is String && item['text'] is String)
          MemoryHit(
            id: item['id']! as String,
            store: item['store']?.toString() ?? '',
            asOf: item['as_of']?.toString() ?? '',
            availableAt: item['available_at']?.toString() ?? '',
            text: item['text']! as String,
            score: (item['score'] as num?)?.toDouble() ?? 0,
          ),
    ];
  }

  @override
  Future<void> upsert(List<MemoryRecord> rows) async {
    if (rows.isEmpty) {
      return;
    }
    await client.send('memory.upsert', {
      'rows': [for (final row in rows) row.toJson()],
    }).toList();
  }
}
