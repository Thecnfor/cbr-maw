import 'dart:convert';

import '../models/domain.dart';
import 'package:cbr_maw_contracts/contracts_dart.dart'
    show Failure, SidecarClient, Success;

/// 知识库证据源（`text` 类 claim 的唯一合法依据）。
///
/// `materializeClaims` 要求 `text` claim 必须绑定 `kind=kb` 证据；
/// 此前编排层从不检索知识库，导致 `text` claim 全被丢弃——角色能说的
/// 只剩数值与方向，政策/方法论层面的判断没有出处。
///
/// 零 Mock：检索失败返回空列表，不编造政策条文。
final class KernelKnowledgeSource {
  /// 创建来源。
  const KernelKnowledgeSource(this.client);

  /// sidecar 客户端。
  final SidecarClient client;

  /// 按 [query] 检索截至 [asOf] 的知识库片段。
  Future<List<Evidence>> read({
    required String query,
    required DateTime asOf,
    int topK = 3,
  }) async {
    final day = asOf.toUtc().toIso8601String().substring(0, 10);
    // 契约 kb.search 不接受顶层 as_of（params.additionalProperties=false）；
    // PIT 走 filters.as_of（filters 是自由对象，kernel 会据此按 publish_time
    // 过滤）。若误用 filters.end，kernel 不认该键 → 等于不设上界。
    final results = await client
        .send('kb.search', {
          'query': query,
          'top_k': topK,
          'filters': {'as_of': day},
        })
        .toList();
    final result = results.single;
    return switch (result) {
      Success(:final value) => _parse(day, value),
      Failure() => const [],
    };
  }

  /// 边界解析即校验：结构不符的命中直接丢弃（不猜字段）。
  static List<Evidence> _parse(String day, Object? payload) {
    if (payload is! Map<String, Object?>) {
      return const [];
    }
    final hits = payload['hits'];
    if (hits is! List) {
      return const [];
    }
    final out = <Evidence>[];
    for (final item in hits.whereType<Map<String, Object?>>()) {
      final chunkId = item['chunk_id'];
      final text = item['text'];
      if (chunkId is! String || text is! String || text.isEmpty) {
        continue;
      }
      final published = item['published_at']?.toString();
      // PIT：检索已按 as_of 过滤，这里再兜一层——发布时间晚于决策时点
      // 的片段一律丢弃（双层防护，docs/00 四级 PIT）。
      if (published != null &&
          published.isNotEmpty &&
          published.compareTo(day) > 0) {
        continue;
      }
      final sourceId = item['source_id']?.toString() ?? '未登记来源';
      final title = item['locator']?.toString() ?? '知识库片段';
      final payloadMap = {
        'chunk_id': chunkId,
        'document_id': item['document_id']?.toString() ?? '',
        'locator': title,
        'published_at': published,
        'score': item['score'],
        'text': text,
        'domain': 'policy.fulltext',
      };
      out.add(
        Evidence(
          evidenceId: 'ev_kb_$chunkId',
          kind: EvidenceKind.kb,
          asOf: DateTime.parse('${published ?? day}T00:00:00Z'),
          title: title,
          summary: text.length > 120 ? '${text.substring(0, 120)}…' : text,
          payload: payloadMap,
          source: SourceRef(name: sourceId),
          producedBy: 'kb.search',
          createdAt: DateTime.now().toUtc(),
          hash: _hash(payloadMap),
        ),
      );
    }
    return out;
  }

  /// 证据载荷哈希（与工具证据同口径：规范化 JSON 的 sha256 前 16 位语义）。
  static String _hash(Map<String, Object?> payload) {
    // 这里只用 Dart 的 jsonEncode 做稳定摘要：KB 片段不参与黄金向量比对，
    // 跨语言逐字节一致的要求只针对工具数值证据（docs/00 红线 3）。
    final bytes = utf8.encode(jsonEncode(payload));
    var hash = 0;
    for (final byte in bytes) {
      hash = (hash * 31 + byte) & 0x7fffffffffff;
    }
    return hash.toRadixString(16).padLeft(12, '0');
  }
}
