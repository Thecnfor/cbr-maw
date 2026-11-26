import '../../app/app_scope.dart';
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

/// 时间线（docs/02 F5-6）：历次研判 / 告警 / 冲突 / 决策，可按角色与等级筛选。
final class TimelinePage extends StatefulWidget {
  /// 创建页面。
  const TimelinePage({required this.state, super.key});

  /// 应用状态。
  final AppState state;

  @override
  State<TimelinePage> createState() => _TimelinePageState();
}

class _TimelinePageState extends State<TimelinePage> {
  String? _roleFilter;
  String? _outcomeFilter;

  @override
  Widget build(BuildContext context) {
    final events = widget.state.auditEvents;
    final filtered = events.where((event) {
      if (_roleFilter != null && event.actor != _roleFilter) {
        return false;
      }
      if (_outcomeFilter != null && event.outcome != _outcomeFilter) {
        return false;
      }
      return true;
    }).toList();
    final roles = events.map((event) => event.actor).toSet().toList()..sort();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '时间线',
          subtitle: '本次会话的研判、工具调用、冲突与决策审计',
          actions: [
            OutlinedButton.icon(
              onPressed: () => AppShellNavigator.go(Routes.diagnostics),
              icon: const Icon(Icons.monitor_heart_outlined, size: 16),
              label: const Text('诊断'),
            ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: Tokens.space5),
          child: Wrap(
            spacing: Tokens.space2,
            runSpacing: Tokens.space2,
            children: [
              FilterChip(
                label: const Text('全部角色'),
                selected: _roleFilter == null,
                onSelected: (_) => setState(() => _roleFilter = null),
              ),
              for (final role in roles)
                FilterChip(
                  label: Text(roleLabel(role)),
                  selected: _roleFilter == role,
                  onSelected: (_) => setState(() => _roleFilter = role),
                ),
              const SizedBox(width: Tokens.space3),
              FilterChip(
                label: const Text('全部结果'),
                selected: _outcomeFilter == null,
                onSelected: (_) => setState(() => _outcomeFilter = null),
              ),
              for (final outcome in const [
                'allowed',
                'denied',
                'failed',
                'pending_hitl',
              ])
                FilterChip(
                  label: Text(_outcomeLabel(outcome)),
                  selected: _outcomeFilter == outcome,
                  onSelected: (_) => setState(() => _outcomeFilter = outcome),
                ),
            ],
          ),
        ),
        const SizedBox(height: Tokens.space3),
        Expanded(
          child: events.isEmpty
              ? const EmptyState(
                  title: '尚无审计事件',
                  message: '工具调用与权限判定会实时记入时间线。可先发起一次研判。',
                  icon: Icons.timeline_outlined,
                )
              : filtered.isEmpty
              ? const EmptyState(
                  title: '当前筛选条件下没有匹配结果',
                  message: '可清除筛选条件查看全部事件。',
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
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final event = filtered[index];
                    return ListRow(
                      title: '${event.type} · ${event.tool}',
                      subtitle:
                          '${roleLabel(event.actor)} · ${_outcomeLabel(event.outcome)} · '
                          '${Clock.display(event.ts)} · ${event.reason}',
                      leading: Icon(
                        _outcomeIcon(event.outcome),
                        size: 16,
                        color: _outcomeColor(context, event.outcome),
                      ),
                      trailing: StatusTag(
                        label: _riskLabel(event.riskLevel.wire),
                        tone: BannerTone.info,
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }

  static String _outcomeLabel(String outcome) => switch (outcome) {
    'allowed' => '已执行',
    'denied' => '越权拒绝',
    'failed' => '执行失败',
    'pending_hitl' => '待人工确认',
    _ => outcome,
  };

  static IconData _outcomeIcon(String outcome) => switch (outcome) {
    'allowed' => Icons.check_circle_outline,
    'denied' => Icons.block,
    'failed' => Icons.error_outline,
    'pending_hitl' => Icons.pan_tool_outlined,
    _ => Icons.circle_outlined,
  };

  static Color _outcomeColor(BuildContext context, String outcome) {
    final colors = SemanticColors.of(context);
    return switch (outcome) {
      'allowed' => colors.okInk,
      'denied' => colors.dangerInk,
      'failed' => colors.dangerInk,
      _ => colors.warnInk,
    };
  }

  static String _riskLabel(String wire) => switch (wire) {
    'L0' => '仅查看',
    'L1' => '需确认的操作',
    'L2' => '高风险操作',
    _ => wire,
  };
}

/// 时间线详情（/timeline/:runId）：单次研判的审计回看。
final class TimelineRunPage extends StatelessWidget {
  /// 创建页面。
  const TimelineRunPage({required this.runId, super.key});

  /// run id。
  final String runId;

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final events = state.auditEvents;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '研判详情',
          subtitle: runId,
          actions: [
            OutlinedButton.icon(
              onPressed: () => AppShellNavigator.go(Routes.timeline),
              icon: const Icon(Icons.arrow_back, size: 16),
              label: const Text('返回时间线'),
            ),
          ],
        ),
        Expanded(
          child: events.isEmpty
              ? const EmptyState(
                  title: '尚无该研判的记录',
                  message: '本次会话还没有产生审计事件。可先发起一次研判。',
                  icon: Icons.timeline_outlined,
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(
                    Tokens.space5,
                    0,
                    Tokens.space5,
                    Tokens.space8,
                  ),
                  itemCount: events.length,
                  separatorBuilder: (_, _) => const Divider(height: 1),
                  itemBuilder: (context, index) {
                    final event = events[index];
                    return ListRow(
                      title: '${event.type} · ${event.tool}',
                      subtitle:
                          '${roleLabel(event.actor)} · ${event.outcome} · '
                          '${Clock.display(event.ts)} · ${event.reason}',
                    );
                  },
                ),
        ),
      ],
    );
  }
}
