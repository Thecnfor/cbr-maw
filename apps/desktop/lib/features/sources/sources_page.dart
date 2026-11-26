import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../../app/app_state.dart';
import '../../app/routes.dart';
import '../../app/shell/app_shell.dart';
import '../../app/theme/theme.dart';
import '../../app/theme/tokens.dart';
import '../../app/ui.dart';
import '../../app/widgets/chips.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../core/clock.dart';
import '../../core/errors.dart';

/// 来源台账（docs/02 F4-1、F4-11）：列表 + 五态 + 陈旧度 + 角标。
final class SourcesPage extends StatefulWidget {
  /// 创建页面。
  const SourcesPage({required this.state, super.key});

  /// 应用状态。
  final AppState state;

  @override
  State<SourcesPage> createState() => _SourcesPageState();
}

class _SourcesPageState extends State<SourcesPage> {
  Future<_SourcesData>? _future;
  SourceState? _filter;

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

  Future<_SourcesData> _load() async {
    final repo = widget.state.repository;
    try {
      final sources = await repo.sources();
      final health = await repo.sourcesHealth();
      final healthById = {for (final entry in health) entry.sourceId: entry};
      return _SourcesData(sources: sources, healthById: healthById);
    } on AppError catch (e) {
      return _SourcesData(error: e);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '来源台账',
          subtitle: '每个来源的可达性、授权状态与陈旧度；无数据时显式标注原因',
          actions: [
            OutlinedButton.icon(
              onPressed: _reload,
              icon: const Icon(Icons.refresh, size: 16),
              label: const Text('刷新'),
            ),
          ],
        ),
        Expanded(
          child: FutureBuilder<_SourcesData>(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              final data = snapshot.data ?? const _SourcesData();
              if (data.error != null) {
                final error = data.error!;
                return ErrorStateView(
                  what: '来源台账读取失败',
                  why: error.why,
                  next: error.next,
                  onRetry: _reload,
                );
              }
              final filtered = _filter == null
                  ? data.sources
                  : data.sources
                        .where(
                          (s) =>
                              (data.healthById[s.id]?.state ?? _stateOf(s)) ==
                              _filter,
                        )
                        .toList();
              return Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.symmetric(
                      horizontal: Tokens.space5,
                    ),
                    child: Wrap(
                      spacing: Tokens.space2,
                      children: [
                        FilterChip(
                          label: const Text('全部'),
                          selected: _filter == null,
                          onSelected: (_) => setState(() => _filter = null),
                        ),
                        for (final state in SourceState.values)
                          FilterChip(
                            label: Text(SourceStateChip.labelFor(state)),
                            selected: _filter == state,
                            onSelected: (_) => setState(() => _filter = state),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: Tokens.space3),
                  Expanded(
                    child: data.sources.isEmpty
                        ? const EmptyState(
                            title: '来源台账为空',
                            message: '尚未登记任何数据来源。可在设置中检查来源配置。',
                            icon: Icons.hub_outlined,
                          )
                        : filtered.isEmpty
                        ? const EmptyState(
                            title: '当前筛选条件下没有匹配结果',
                            message: '可切换筛选条件查看其他来源。',
                            icon: Icons.filter_alt_off_outlined,
                          )
                        : ListView.separated(
                            padding: const EdgeInsets.fromLTRB(
                              Tokens.space5,
                              0,
                              Tokens.space5,
                              Tokens.space8,
                            ),
                            itemCount: filtered.length,
                            separatorBuilder: (_, _) =>
                                const SizedBox(height: 6),
                            itemBuilder: (context, index) {
                              final source = filtered[index];
                              final health = data.healthById[source.id];
                              final state = health?.state ?? _stateOf(source);
                              return _SourceRow(
                                source: source,
                                state: state,
                                stale: health?.stale ?? false,
                                lastSuccessAt:
                                    health?.lastSuccessAt ??
                                    source.lastSuccessAt,
                                coverageStart: health?.coverageStart,
                                coverageEnd: health?.coverageEnd,
                              );
                            },
                          ),
                  ),
                ],
              );
            },
          ),
        ),
      ],
    );
  }

  static SourceState _stateOf(SourceLedgerEntry source) =>
      switch (source.reachability) {
        'reachable' => SourceState.reachable,
        'need_auth' => SourceState.needAuth,
        'need_login' => SourceState.needLogin,
        'restricted' => SourceState.restricted,
        _ => SourceState.unreachable,
      };
}

final class _SourceRow extends StatelessWidget {
  const _SourceRow({
    required this.source,
    required this.state,
    required this.stale,
    required this.lastSuccessAt,
    required this.coverageStart,
    required this.coverageEnd,
  });

  final SourceLedgerEntry source;
  final SourceState state;
  final bool stale;
  final String? lastSuccessAt;
  final String? coverageStart;
  final String? coverageEnd;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        color: theme.cardTheme.color,
        borderRadius: BorderRadius.circular(Tokens.radiusCard),
        border: Border.all(color: theme.colorScheme.outlineVariant),
      ),
      padding: const EdgeInsets.all(Tokens.space4),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  source.sourceName,
                  style: theme.textTheme.titleSmall,
                ),
              ),
              SourceStateChip(state: state, stale: stale),
            ],
          ),
          const SizedBox(height: Tokens.space2),
          Text(
            '${source.id} · ${source.modality} · ${source.accessMode}',
            style: TextStyle(
              fontSize: 12,
              color: theme.colorScheme.onSurfaceVariant,
            ),
          ),
          const SizedBox(height: Tokens.space2),
          KeyValueRow(label: '授权状态', value: source.authorizationStatus),
          KeyValueRow(
            label: '分档',
            value: switch (source.tier) {
              LedgerTier.t1Public => '公开可取',
              LedgerTier.t2Credentialed => '需凭证',
              LedgerTier.t3Terminal => '仅本机终端',
              LedgerTier.t4NotAllowed => '不允许自动抓取',
            },
          ),
          KeyValueRow(
            label: '关联序列',
            value: source.seriesIds.isEmpty
                ? '未登记'
                : source.seriesIds.join('、'),
          ),
          KeyValueRow(
            label: '上次成功',
            value:
                '${Clock.relative(lastSuccessAt)}（${Clock.display(lastSuccessAt)}）',
          ),
          KeyValueRow(
            label: '陈旧度',
            value: stale ? '已陈旧（超过阈值）' : '在阈值内',
            valueColor: stale ? SemanticColors.of(context).warnInk : null,
          ),
          KeyValueRow(
            label: '覆盖期',
            value: coverageStart == null && coverageEnd == null
                ? '未登记覆盖期'
                : '${coverageStart ?? '未登记'} 至 ${coverageEnd ?? '未登记'}',
          ),
          if (source.lastError != null)
            KeyValueRow(
              label: '最近失败',
              value: source.lastError!,
              valueColor: SemanticColors.of(context).dangerInk,
            ),
          if (state != SourceState.reachable)
            Padding(
              padding: const EdgeInsets.only(top: Tokens.space2),
              child: _UnavailableActions(
                sourceName: source.sourceName,
                state: state,
                reason: _UnavailableActions._reason(state),
              ),
            ),
        ],
      ),
    );
  }
}

final class _SourcesData {
  const _SourcesData({
    this.sources = const [],
    this.healthById = const {},
    this.error,
  });

  final List<SourceLedgerEntry> sources;
  final Map<String, HealthEntry> healthById;
  final AppError? error;
}

/// 不可达来源的两个可点动作：申请授权 / 更换来源（docs/22 屏 7）。
final class _UnavailableActions extends StatelessWidget {
  const _UnavailableActions({
    required this.sourceName,
    required this.state,
    required this.reason,
  });

  final String sourceName;
  final SourceState state;
  final String reason;

  @override
  Widget build(BuildContext context) {
    final colors = SemanticColors.of(context);
    final needsAuth =
        state == SourceState.needAuth || state == SourceState.needLogin;
    return Container(
      padding: const EdgeInsets.all(Tokens.space3),
      decoration: BoxDecoration(
        color: colors.warnTint,
        borderRadius: BorderRadius.circular(Tokens.radiusCard),
        border: Border.all(color: colors.warnInk.withValues(alpha: 0.35)),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            needsAuth ? Icons.lock_outline : Icons.shield_outlined,
            size: 18,
            color: colors.warnInk,
          ),
          const SizedBox(width: Tokens.space2),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '$sourceName ${SourceStateChip.labelFor(state)}',
                  style: TextStyle(
                    color: colors.warnInk,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(reason),
                Text(
                  '该来源不显示任何数值（不是 0，也不是占位符）。',
                  style: TextStyle(fontSize: 12, color: colors.warnInk),
                ),
              ],
            ),
          ),
          TextButton(
            onPressed: () => AppShellNavigator.go(Routes.settings),
            child: const Text('申请授权'),
          ),
          TextButton(
            onPressed: () => AppShellNavigator.go(Routes.dataCards),
            child: const Text('更换来源'),
          ),
        ],
      ),
    );
  }

  static String _reason(SourceState state) => switch (state) {
    SourceState.needAuth => '该来源需要有效凭证才能获取数据，当前未配置凭证。',
    SourceState.needLogin => '该来源需要登录后才能访问，请先完成登录。',
    SourceState.restricted => '该来源有反爬策略或当前被拒绝访问。',
    _ => '目标站点当前不可达（DNS / 连接 / 5xx）。',
  };
}
