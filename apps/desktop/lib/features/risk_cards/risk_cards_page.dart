import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../../app/app_state.dart';
import '../../app/routes.dart';
import '../../app/shell/app_shell.dart';
import '../../app/theme/theme.dart';
import '../../app/theme/tokens.dart';
import '../../app/ui.dart';
import '../../app/widgets/chips.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/dimensions.dart';
import '../../app/widgets/states.dart';
import '../../core/clock.dart';
import '../../core/errors.dart';

/// 风险卡（docs/02 F5-2）：等级、结论、关键指标、证据、限制。
final class RiskCardsPage extends StatefulWidget {
  /// 创建页面。
  const RiskCardsPage({required this.state, super.key});

  /// 应用状态。
  final AppState state;

  @override
  State<RiskCardsPage> createState() => _RiskCardsPageState();
}

class _RiskCardsPageState extends State<RiskCardsPage> {
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
    final result = await widget.state.repository.query(
      view: DbView.signals,
      asOf: Clock.asOfNow(),
      limit: 50,
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
          title: '风险卡',
          subtitle: '每条结论都必须可回指到证据；无证据的结论不会显示',
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
                  what: '风险卡读取失败',
                  why: appError?.why ?? '$error',
                  next: appError?.next ?? '可稍后重试；若持续失败请查看诊断页',
                  onRetry: _reload,
                );
              }
              final rows = snapshot.data ?? const [];
              if (rows.isEmpty) {
                return EmptyState(
                  title: '尚无风险卡',
                  message: '风险卡在完成研判后生成。可先发起一次研判。',
                  icon: Icons.shield_outlined,
                  actionLabel: '发起研判',
                  onAction: () => AppShellNavigator.go(Routes.investigation),
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
                itemBuilder: (context, index) => _SignalCard(row: rows[index]),
              );
            },
          ),
        ),
      ],
    );
  }
}

final class _SignalCard extends StatelessWidget {
  const _SignalCard({required this.row});

  final Map<String, Object?> row;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final signalId = row['signal_id']?.toString();
    final level = riskLevelFromWire(row['risk_level']?.toString());
    final value = row['value'];
    final limitations = _stringList(row['limitations']);
    final missingDims = _stringList(row['missing_dims']);
    final dims = row['dims'];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(Tokens.space4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    signalId ?? '未命名信号',
                    style: theme.textTheme.titleSmall,
                  ),
                ),
                RiskLevelBadge(level: level),
              ],
            ),
            const SizedBox(height: Tokens.space2),
            KeyValueRow(
              label: '综合信号值',
              value: value == null ? '缺失（该维度不参与计算）' : '$value',
            ),
            if (row['as_of'] != null)
              KeyValueRow(
                label: '时点',
                value: Clock.display(row['as_of']!.toString()),
              ),
            const SizedBox(height: Tokens.space3),
            Text('六维分解', style: theme.textTheme.labelLarge),
            const SizedBox(height: Tokens.space2),
            DimensionBreakdown(
              dims: dims is Map
                  ? {for (final e in dims.entries) '${e.key}': e.value}
                  : const {},
              missingDims: missingDims,
              absenceReasons: {
                for (final dim in missingDims) dim: absenceReason(null),
              },
            ),
            if (missingDims.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: Tokens.space2),
                child: KeyValueRow(
                  label: '缺席维度',
                  value: '${missingDims.join('、')}（未参与计算，未用 0 填充）',
                  valueColor: SemanticColors.of(context).warnInk,
                ),
              ),
            const SizedBox(height: Tokens.space2),
            _StructuralReading(
              dims: dims is Map
                  ? {for (final e in dims.entries) '${e.key}': e.value}
                  : const {},
              missingDims: missingDims,
            ),
            const SizedBox(height: Tokens.space3),
            Text('限制', style: theme.textTheme.labelLarge),
            const SizedBox(height: Tokens.space1),
            if (limitations.isEmpty)
              const Text('本次结果未附加系统限制。')
            else
              for (final item in limitations)
                Padding(
                  padding: const EdgeInsets.only(bottom: 2),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('· '),
                      Expanded(child: Text(item)),
                    ],
                  ),
                ),
            if (signalId != null) ...[
              const SizedBox(height: Tokens.space2),
              Align(
                alignment: Alignment.centerRight,
                child: TextButton(
                  onPressed: () =>
                      AppShellNavigator.go(Routes.timelineRun(signalId)),
                  child: const Text('在时间线中查看'),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  static List<String> _stringList(Object? value) {
    if (value is List) {
      return value.map((e) => e.toString()).toList();
    }
    return const [];
  }
}

/// 结构判读（docs/20 维度离散度）：压力主要来自哪几维 + 缺席维度的结构含义。
///
/// 只描述"来源结构"，不做因果判断；缺席维度显式列出。
final class _StructuralReading extends StatelessWidget {
  const _StructuralReading({required this.dims, required this.missingDims});

  final Map<String, Object?> dims;
  final List<String> missingDims;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final present = <String, double>{
      for (final dim in sixDimensions) dim.label: ?_numeric(dims[dim.key]),
    };
    if (present.isEmpty) {
      return const Text('结构判读不可用：六维均无可用观测。');
    }
    final sorted = present.entries.toList()
      ..sort((a, b) => b.value.compareTo(a.value));
    final top = sorted.take(2).map((e) => e.key).join('与');
    final missingLabels = [
      for (final dim in sixDimensions)
        if (missingDims.contains(dim.key)) dim.label,
    ];
    return Text(
      '当前压力主要来自$top'
      '${missingLabels.isEmpty ? '。' : '；${missingLabels.join('、')}维度尚未计入。'}'
      '相关非因果。',
      style: TextStyle(fontSize: 13, color: theme.colorScheme.onSurfaceVariant),
    );
  }

  static double? _numeric(Object? raw) {
    if (raw is num) {
      return raw.toDouble().isFinite ? raw.toDouble() : null;
    }
    if (raw is Map) {
      return _numeric(raw['value']);
    }
    return null;
  }
}

/// 风险卡详情（/risk-cards/:claimId）：结论、证据链、限制。
///
/// 数据来自本地库 `signals` 视图；查不到就显式说明，不编造结论。
final class RiskCardDetailPage extends StatefulWidget {
  /// 创建页面。
  const RiskCardDetailPage({
    required this.state,
    required this.claimId,
    super.key,
  });

  /// 应用状态。
  final AppState state;

  /// claim id。
  final String claimId;

  @override
  State<RiskCardDetailPage> createState() => _RiskCardDetailPageState();
}

class _RiskCardDetailPageState extends State<RiskCardDetailPage> {
  Future<Map<String, Object?>?>? _future;

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

  Future<Map<String, Object?>?> _load() async {
    final result = await widget.state.repository.query(
      view: DbView.signals,
      asOf: Clock.asOfNow(),
      filters: {'claim_id': widget.claimId},
      limit: 1,
    );
    if (result.rows.isEmpty) {
      return null;
    }
    final row = result.rows.first;
    return {
      for (var i = 0; i < result.columns.length && i < row.length; i++)
        result.columns[i]: row[i],
    };
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '风险卡详情',
          subtitle: widget.claimId,
          actions: [
            OutlinedButton.icon(
              onPressed: () => AppShellNavigator.go(Routes.riskCards),
              icon: const Icon(Icons.arrow_back, size: 16),
              label: const Text('返回列表'),
            ),
          ],
        ),
        Expanded(
          child: FutureBuilder<Map<String, Object?>?>(
            future: _future,
            builder: (context, snapshot) {
              if (snapshot.connectionState != ConnectionState.done) {
                return const Center(child: CircularProgressIndicator());
              }
              if (snapshot.hasError) {
                final error = snapshot.error;
                final appError = error is AppError ? error : null;
                return ErrorStateView(
                  what: '结论读取失败',
                  why: appError?.why ?? '$error',
                  next: appError?.next ?? '可稍后重试；若持续失败请查看诊断页',
                  onRetry: _reload,
                );
              }
              final row = snapshot.data;
              if (row == null) {
                return EmptyState(
                  title: '未找到该结论',
                  message:
                      '${widget.claimId} 在本地库中没有对应记录。'
                      '无证据的结论不会进入最终判定，因此可能已被丢弃。',
                  icon: Icons.search_off,
                  actionLabel: '返回风险卡',
                  onAction: () => AppShellNavigator.go(Routes.riskCards),
                );
              }
              final evidenceIds = _stringList(row['evidence_ids']);
              final limitations = _stringList(row['limitations']);
              return ListView(
                padding: const EdgeInsets.fromLTRB(
                  Tokens.space5,
                  0,
                  Tokens.space5,
                  Tokens.space8,
                ),
                children: [
                  SectionCard(
                    title: '结论',
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            RiskLevelBadge(
                              level: riskLevelFromWire(
                                row['risk_level']?.toString(),
                              ),
                            ),
                            const SizedBox(width: Tokens.space2),
                            StatusTag(
                              label: row['kind']?.toString() ?? '未知类型',
                              tone: BannerTone.info,
                            ),
                          ],
                        ),
                        const SizedBox(height: Tokens.space3),
                        Text(row['text']?.toString() ?? '该结论没有文本内容。'),
                        if (row['confidence'] != null) ...[
                          const SizedBox(height: Tokens.space2),
                          Text('置信度：${row['confidence']}'),
                        ],
                      ],
                    ),
                  ),
                  const SizedBox(height: Tokens.space4),
                  SectionCard(
                    title: '证据',
                    child: evidenceIds.isEmpty
                        ? const Text('该结论没有绑定证据。')
                        : Wrap(
                            spacing: Tokens.space2,
                            runSpacing: Tokens.space2,
                            children: [
                              for (final id in evidenceIds)
                                ActionChip(
                                  label: Text('证据 $id'),
                                  onPressed: () =>
                                      AppShellNavigator.go(Routes.evidence(id)),
                                ),
                            ],
                          ),
                  ),
                  const SizedBox(height: Tokens.space4),
                  SectionCard(
                    title: '限制',
                    child: limitations.isEmpty
                        ? const Text('本次结果未附加系统限制。')
                        : Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              for (final item in limitations)
                                Padding(
                                  padding: const EdgeInsets.only(bottom: 2),
                                  child: Row(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      const Text('· '),
                                      Expanded(child: Text(item)),
                                    ],
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

  static List<String> _stringList(Object? value) {
    if (value is List) {
      return value.map((e) => e.toString()).toList();
    }
    if (value is String && value.isNotEmpty) {
      return value.split(',');
    }
    return const [];
  }
}
