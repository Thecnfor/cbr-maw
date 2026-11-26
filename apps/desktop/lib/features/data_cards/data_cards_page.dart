import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../../app/ui.dart';

import '../../app/app_scope.dart';
import '../../app/theme/tokens.dart';
import '../../app/widgets/chips.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../core/clock.dart';
import '../../core/errors.dart';

/// 数据卡（docs/02 F5-7）：每序列的口径、单位、来源、覆盖期、时点评级。
final class DataCardsPage extends StatefulWidget {
  /// 创建页面。
  const DataCardsPage({super.key});

  @override
  State<DataCardsPage> createState() => _DataCardsPageState();
}

class _DataCardsPageState extends State<DataCardsPage> {
  Future<List<Map<String, Object?>>>? _future;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    setState(() {
      _future = _load();
    });
  }

  Future<List<Map<String, Object?>>> _load() async {
    final state = AppStateScope.read(context);
    final result = await state.repository.query(
      view: DbView.dataCards,
      asOf: Clock.asOfNow(),
      limit: 200,
    );
    return result.rows
        .map(
          (row) => {
            for (var i = 0; i < result.columns.length && i < row.length; i++)
              result.columns[i]: row[i],
          },
        )
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '数据卡',
          subtitle: '序列口径与抓取状态一一对应；缺失时显式标注，不显示占位数值',
          actions: [
            OutlinedButton.icon(
              onPressed: _reload,
              icon: const Icon(Icons.refresh, size: 16),
              label: const Text('刷新'),
            ),
          ],
        ),
        Expanded(
          child: FutureBuilder<List<Map<String, Object?>>>(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                final error = snapshot.error;
                final appError = error is AppError ? error : null;
                return ErrorStateView(
                  what: '数据卡读取失败',
                  why: appError?.why ?? '$error',
                  next: appError?.next ?? '可稍后重试；若持续失败请查看诊断页',
                  onRetry: _reload,
                );
              }
              final rows = snapshot.data ?? const [];
              if (rows.isEmpty) {
                return const EmptyState(
                  title: '尚无数据卡',
                  message: '接入来源并完成抓取后，这里会按序列列出可用的数据卡。',
                  icon: Icons.dataset_outlined,
                );
              }
              return ListView.separated(
                padding: const EdgeInsets.fromLTRB(
                  Tokens.space5,
                  0,
                  Tokens.space5,
                  Tokens.space8,
                ),
                itemCount: rows.length,
                separatorBuilder: (_, _) =>
                    const SizedBox(height: Tokens.space3),
                itemBuilder: (context, index) => _DataCard(row: rows[index]),
              );
            },
          ),
        ),
      ],
    );
  }
}

final class _DataCard extends StatelessWidget {
  const _DataCard({required this.row});

  final Map<String, Object?> row;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final seriesId = row['series_id']?.toString() ?? '未命名序列';
    final state = _stateOf(row['state']?.toString());
    final reachable = state == SourceState.reachable;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(Tokens.space4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(seriesId, style: theme.textTheme.titleSmall),
                ),
                SourceStateChip(state: state, stale: row['stale'] == true),
              ],
            ),
            const SizedBox(height: Tokens.space2),
            if (!reachable)
              AccessRequiredState(
                sourceName: seriesId,
                reason:
                    '${SourceStateChip.labelFor(state)}：'
                    '${row['failure_reason']?.toString() ?? '当前没有可用数据'}。未显示任何数值。',
                icon: state == SourceState.restricted
                    ? Icons.shield_outlined
                    : Icons.lock_outline,
              )
            else ...[
              KeyValueRow(label: '单位', value: row['unit']?.toString() ?? '未登记'),
              KeyValueRow(
                label: '来源',
                value: row['source_id']?.toString() ?? '未登记',
              ),
              KeyValueRow(
                label: '覆盖期',
                value:
                    '${row['coverage_start']?.toString() ?? '—'} 至 '
                    '${row['coverage_end']?.toString() ?? '—'}',
              ),
              KeyValueRow(
                label: '上次成功',
                value: Clock.relative(row['last_success_at']?.toString()),
              ),
              KeyValueRow(
                label: '时点评级',
                value: row['release_time_rule']?.toString() ?? '未登记',
              ),
            ],
          ],
        ),
      ),
    );
  }

  static SourceState _stateOf(String? wire) => switch (wire) {
    'need_auth' => SourceState.needAuth,
    'need_login' => SourceState.needLogin,
    'restricted' => SourceState.restricted,
    'unreachable' => SourceState.unreachable,
    _ => SourceState.reachable,
  };
}
