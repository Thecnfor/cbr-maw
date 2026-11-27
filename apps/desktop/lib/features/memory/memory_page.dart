import '../../app/ui.dart';

import '../../app/app_scope.dart';
import '../../app/theme/tokens.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../core/clock.dart';

/// 记忆（ADR-010）：三库 MI/LLR/HLR 的规模、向量化状态与检索。
///
/// 设计要点：
/// - 统计与检索都走 kernel 的 `memory.stats` / `memory.search`，UI 不自己算；
/// - 检索必须带 `as_of`（PIT 由 kernel 强制），界面明确标出这一点；
/// - 缺数据时显示 `—` 与原因，不编造条数。
/// 记忆统计/检索的数据源；缺省走 `AppState.repository`。
typedef MemoryStatsLoader = Future<Map<String, Object?>> Function();
typedef MemorySearchLoader = Future<List<Map<String, Object?>>> Function({
  required String asOf,
  required String query,
  int topK,
});

final class MemoryPage extends StatefulWidget {
  /// 创建页面。
  ///
  /// 两个 loader 可注入：没有 sidecar 的 widget 测试需要它们。
  const MemoryPage({this.statsLoader, this.searchLoader, super.key});

  /// 统计来源；null = 走真实 kernel。
  final MemoryStatsLoader? statsLoader;

  /// 检索来源；null = 走真实 kernel。
  final MemorySearchLoader? searchLoader;

  @override
  State<MemoryPage> createState() => _MemoryPageState();
}

class _MemoryPageState extends State<MemoryPage> {
  final _query = TextEditingController();
  Map<String, Object?>? _stats;
  List<Map<String, Object?>>? _hits;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _loadStats());
  }

  @override
  void dispose() {
    _query.dispose();
    super.dispose();
  }

  Future<void> _loadStats() async {
    setState(() => _busy = true);
    try {
      // 只有没注入 loader 时才需要 AppStateScope（widget 测试不提供它）。
      final loader =
          widget.statsLoader ??
          AppStateScope.read(context).repository.memoryStats;
      final stats = await loader();
      if (mounted) {
        setState(() {
          _stats = stats;
          _error = null;
        });
      }
    } on Object catch (err) {
      if (mounted) {
        setState(() => _error = '$err');
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  Future<void> _search() async {
    final query = _query.text.trim();
    if (query.isEmpty) {
      return;
    }
    final asOf = Clock.nowUtc().toIso8601String().substring(0, 10);
    setState(() => _busy = true);
    try {
      final loader =
          widget.searchLoader ??
          ({required String asOf, required String query, int topK = 8}) =>
              AppStateScope.read(context).repository
                  .memorySearch(asOf: asOf, query: query, topK: topK);
      final hits = await loader(asOf: asOf, query: query, topK: 8);
      if (mounted) {
        setState(() {
          _hits = hits;
          _error = null;
        });
      }
    } on Object catch (err) {
      if (mounted) {
        setState(() => _error = '$err');
      }
    } finally {
      if (mounted) {
        setState(() => _busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final stats = _stats;
    final perStore = stats?['per_store'] is Map
        ? (stats!['per_store']! as Map).cast<String, Object?>()
        : const <String, Object?>{};
    final embeddingReady = stats?['embedding_ready'] == true;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const PageHeader(
          title: '记忆',
          subtitle: '三库记忆（MI 情报 / LLR 浅层反思 / HLR 深层复盘）；检索强制时点前过滤',
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Tokens.space5,
              0,
              Tokens.space5,
              Tokens.space8,
            ),
            children: [
              if (_error != null) ...[
                InlineBanner(message: _error!, tone: BannerTone.error),
                const SizedBox(height: Tokens.space3),
              ],
              SectionCard(
                title: '库规模',
                trailing: TextButton(
                  onPressed: _busy ? null : _loadStats,
                  child: const Text('刷新'),
                ),
                child: Column(
                  children: [
                    KeyValueRow(
                      label: '总记录',
                      value: stats?['rows']?.toString() ?? '—',
                    ),
                    KeyValueRow(
                      label: 'MI · 市场情报',
                      value: perStore['mi']?.toString() ?? '—',
                    ),
                    KeyValueRow(
                      label: 'LLR · 浅层反思',
                      value: perStore['llr']?.toString() ?? '—',
                    ),
                    KeyValueRow(
                      label: 'HLR · 深层复盘',
                      value: perStore['hlr']?.toString() ?? '—',
                    ),
                    KeyValueRow(
                      label: '向量化',
                      value: stats == null
                          ? '—'
                          : (embeddingReady
                                ? '已启用（${stats['embed_dim']} 维，ANN）'
                                : '降级为全文检索（${stats['fts_tokenizer'] ?? '—'} 分词）'),
                    ),
                    if (stats?['embedding_error'] != null)
                      KeyValueRow(
                        label: '向量化错误',
                        value: '${stats!['embedding_error']}',
                      ),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              SectionCard(
                title: '检索',
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    TextField(
                      controller: _query,
                      decoration: const InputDecoration(
                        labelText: '查询（语义 + 全文混合）',
                        hintText: '例如：北向资金撤离与汇率压力',
                      ),
                      onSubmitted: (_) => _search(),
                    ),
                    const SizedBox(height: Tokens.space2),
                    Row(
                      children: [
                        FilledButton(
                          onPressed: _busy ? null : _search,
                          child: const Text('检索'),
                        ),
                        const SizedBox(width: Tokens.space2),
                        const Text(
                          '截止到当前时点，更晚的记录不会返回',
                          style: TextStyle(fontSize: 12),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: Tokens.space4),
              if (_hits != null)
                SectionCard(
                  title: '命中（${_hits!.length}）',
                  child: _hits!.isEmpty
                      ? const Text('没有命中。记忆库为空或查询与既有记录不匹配。')
                      : Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            for (final hit in _hits!)
                              Padding(
                                padding: const EdgeInsets.only(
                                  bottom: Tokens.space2,
                                ),
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      '${hit['store'] ?? '?'} · ${hit['as_of'] ?? '?'}'
                                      ' · ${hit['id'] ?? '?'}',
                                      style: const TextStyle(fontSize: 12),
                                    ),
                                    Text('${hit['text'] ?? ''}'),
                                  ],
                                ),
                              ),
                          ],
                        ),
                ),
            ],
          ),
        ),
      ],
    );
  }
}
