import 'package:cbr_maw_contracts/contracts_dart.dart';
import 'package:cbr_maw_design_system/cbr_maw_design_system.dart'
    show CbrChartCard, CbrKpiCard, CbrRiskLevel, CbrSeries;

import '../../app/app_state.dart';
import '../../app/shell/app_shell.dart';
import '../../app/routes.dart';
import '../../app/theme/tokens.dart';
import '../../app/ui.dart';
import '../../app/widgets/chips.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../core/clock.dart';
import '../../core/errors.dart';
import '../../data/sidecar/sidecar_supervisor.dart';

/// 概览（docs/02 F5-1）：就绪度、数据新鲜度、来源健康、当前风险、近期研判。
final class OverviewPage extends StatefulWidget {
  /// 创建页面。
  const OverviewPage({required this.state, super.key});

  /// 应用状态。
  final AppState state;

  @override
  State<OverviewPage> createState() => _OverviewPageState();
}

class _OverviewPageState extends State<OverviewPage> {
  Future<_OverviewData>? _future;

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

  Future<_OverviewData> _load() async {
    final repo = widget.state.repository;
    WorkspaceInfoResult? info;
    Object? infoError;
    try {
      info = await repo.workspaceInfo();
    } on AppError catch (e) {
      infoError = e;
    }
    List<HealthEntry>? health;
    Object? healthError;
    try {
      health = await repo.sourcesHealth();
    } on AppError catch (e) {
      healthError = e;
    }
    // 压力走势：只读已入库的 CFSI 历史（不在此处临时计算，避免页面打开就触发重算）。
    var cfsi = const <({String date, double value})>[];
    try {
      final result = await repo.query(
        view: DbView.cfsiHistory,
        asOf: Clock.asOfNow(),
        limit: 120,
      );
      final dateIdx = result.columns.indexOf('as_of');
      final valueIdx = result.columns.indexOf('cfsi');
      if (dateIdx >= 0 && valueIdx >= 0) {
        cfsi = [
          for (final row in result.rows)
            if (row[dateIdx] is String && row[valueIdx] is num)
              (
                date: row[dateIdx]! as String,
                value: (row[valueIdx]! as num).toDouble(),
              ),
        ];
      }
    } on AppError {
      // 历史为空不算错误：图表显示空态，不编造曲线。
      cfsi = const [];
    }
    return _OverviewData(
      info: info,
      infoError: infoError,
      health: health,
      healthError: healthError,
      cfsi: cfsi,
    );
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '概览',
          subtitle: '一屏回答：现在能不能用、数据新不新、系统好不好',
          actions: [
            OutlinedButton.icon(
              onPressed: _reload,
              icon: const Icon(Icons.refresh, size: 16),
              label: const Text('刷新'),
            ),
          ],
        ),
        Expanded(
          child: FutureBuilder<_OverviewData>(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const _OverviewSkeleton();
              }
              final data = snapshot.data ?? const _OverviewData();
              return ListView(
                padding: const EdgeInsets.fromLTRB(
                  Tokens.space5,
                  0,
                  Tokens.space5,
                  Tokens.space8,
                ),
                children: [
                  if (!state.hasApiKey) ...[
                    InlineBanner(
                      message:
                          '尚未配置主模型密钥。历史结论与本地数据仍可浏览，'
                          '但无法发起新的研判。',
                      tone: BannerTone.warn,
                      icon: Icons.key_outlined,
                    ),
                    const SizedBox(height: Tokens.space3),
                  ],
                  if (state.config.syntheticDefault) ...[
                    const InlineBanner(
                      message:
                          '当前为 SYNTHETIC 仿真数据模式。以下结果仅供测试与离线回归，'
                          '不构成任何真实市场结论。',
                      tone: BannerTone.info,
                      icon: Icons.science_outlined,
                    ),
                    const SizedBox(height: Tokens.space3),
                  ],
                  MetricStrip(
                    metrics: [
                      // 内核状态用设计系统 KPI 卡：状态色与"不可用"文案
                      // 由设计系统统一，app 侧不再自绘第二套。
                      CbrKpiCard(
                        title: '内核状态',
                        value: state.kernelState.label,
                        caption: state.supervisor.handshake?.version == null
                            ? '尚未握手'
                            : '内核 ${state.supervisor.handshake!.version}',
                        level: state.kernelState == SidecarState.ready
                            ? CbrRiskLevel.low
                            : CbrRiskLevel.high,
                      ),
                      MetricTile(
                        label: '工作区序列数',
                        value: data.info == null
                            ? '不可达'
                            : '${data.info!.seriesCount}',
                        hint: data.info == null
                            ? '需启动内核后读取'
                            : '观测 ${data.info!.obsCount} 条',
                        tone: data.info == null ? BannerTone.warn : null,
                      ),
                      MetricTile(
                        label: '最近入库',
                        value: data.info?.lastIngestAt == null
                            ? '尚无记录'
                            : Clock.relative(data.info!.lastIngestAt),
                        hint: Clock.display(data.info?.lastIngestAt),
                      ),
                      MetricTile(
                        label: '数据新鲜度',
                        value: _freshnessLabel(data.health),
                        hint: data.health == null ? '需启动内核后读取' : '按来源陈旧度汇总',
                        tone: _freshnessTone(data.health),
                      ),
                    ],
                  ),
                  const SizedBox(height: Tokens.space4),
                  if (data.cfsi.isNotEmpty) ...[
                    CbrChartCard(
                      title: '压力指数走势（最近 ${data.cfsi.length} 个交易日）',
                      series: [
                        CbrSeries(
                          name: 'CFSI 压力分位',
                          points: [
                            for (var i = 0; i < data.cfsi.length; i++)
                              (x: i.toDouble(), y: data.cfsi[i].value),
                          ],
                        ),
                      ],
                    ),
                    const SizedBox(height: Tokens.space4),
                  ],
                  SectionCard(
                    title: '来源健康',
                    trailing: TextButton(
                      onPressed: () => AppShellNavigator.go(Routes.sources),
                      child: const Text('查看来源台账'),
                    ),
                    child: _HealthSection(data: data),
                  ),
                  const SizedBox(height: Tokens.space4),
                  SectionCard(
                    title: '当前风险与近期研判',
                    trailing: TextButton(
                      onPressed: () =>
                          AppShellNavigator.go(Routes.investigation),
                      child: const Text('开始研判'),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          '尚无风险结论。风险等级由确定性阈值判定，'
                          '需要先完成一次研判并产出可回指的证据。',
                        ),
                        const SizedBox(height: Tokens.space3),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: FilledButton.tonal(
                            onPressed: () =>
                                AppShellNavigator.go(Routes.investigation),
                            child: const Text('发起第一次研判'),
                          ),
                        ),
                      ],
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

  static String _freshnessLabel(List<HealthEntry>? health) {
    if (health == null) {
      return '不可达';
    }
    if (health.isEmpty) {
      return '无来源';
    }
    final stale = health.where((entry) => entry.stale).length;
    return stale == 0 ? '全部新鲜' : '$stale 个已陈旧';
  }

  static BannerTone? _freshnessTone(List<HealthEntry>? health) {
    if (health == null) {
      return BannerTone.warn;
    }
    return health.any((entry) => entry.stale) ? BannerTone.warn : BannerTone.ok;
  }
}

final class _HealthSection extends StatelessWidget {
  const _HealthSection({required this.data});

  final _OverviewData data;

  @override
  Widget build(BuildContext context) {
    if (data.healthError != null) {
      final error = data.healthError;
      return ErrorStateView(
        what: '来源健康读取失败',
        why: error is AppError ? error.why : '$error',
        next: '可稍后重试；若持续失败请查看诊断页',
      );
    }
    final health = data.health;
    if (health == null) {
      return const Text('来源健康尚未读取。');
    }
    if (health.isEmpty) {
      return const EmptyState(
        title: '尚无来源健康记录',
        message: '来源台账为空。可在来源页查看可接入的数据来源。',
        icon: Icons.hub_outlined,
      );
    }
    final counts = <SourceState, int>{};
    for (final entry in health) {
      counts.update(entry.state, (v) => v + 1, ifAbsent: () => 1);
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          spacing: Tokens.space2,
          runSpacing: Tokens.space2,
          children: [
            for (final entry in counts.entries)
              StatusTag(
                label: '${SourceStateChip.labelFor(entry.key)} ${entry.value}',
                tone: entry.key == SourceState.reachable
                    ? BannerTone.ok
                    : BannerTone.warn,
              ),
          ],
        ),
        const SizedBox(height: Tokens.space3),
        for (final entry in health.take(6))
          ListRow(
            title: entry.sourceId,
            subtitle:
                '上次成功：${Clock.relative(entry.lastSuccessAt)}'
                '${entry.failureReason == null ? '' : ' · ${entry.failureReason}'}',
            trailing: SourceStateChip(state: entry.state, stale: entry.stale),
          ),
      ],
    );
  }
}

final class _OverviewSkeleton extends StatelessWidget {
  const _OverviewSkeleton();

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(Tokens.space5),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: const [
          SkeletonBlock(height: 40),
          SizedBox(height: 16),
          SkeletonBlock(height: 120),
          SizedBox(height: 16),
          SkeletonBlock(height: 200),
        ],
      ),
    );
  }
}

final class _OverviewData {
  const _OverviewData({
    this.cfsi = const [],
    this.info,
    this.infoError,
    this.health,
    this.healthError,
  });

  final WorkspaceInfoResult? info;
  final Object? infoError;
  final List<HealthEntry>? health;
  final Object? healthError;
  final List<({String date, double value})> cfsi;
}
