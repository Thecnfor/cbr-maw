import 'dart:async';

import 'package:cbr_maw_contracts/contracts_dart.dart' show ToolRiskLevel;
import 'package:desktop_drop/desktop_drop.dart';
import 'package:file_picker/file_picker.dart';
import 'package:flutter/services.dart'
    show HardwareKeyboard, KeyDownEvent, LogicalKeyboardKey;

import '../../agents/investigation_controller.dart';
import '../../agents/run_events.dart';
import '../../app/app_scope.dart';
import '../../app/app_state.dart';
import '../../app/inbox_log.dart';
import '../../app/routes.dart';
import '../../app/shell/app_shell.dart';
import '../../app/theme/theme.dart';
import '../../app/theme/tokens.dart';
import '../../app/ui.dart';
import '../../app/widgets/chips.dart';
import '../../app/widgets/common.dart' show MetricTile;

import '../../app/widgets/states.dart';
import '../../app/widgets/synthetic.dart';
import 'investigation_rules.dart';
import '../../core/clock.dart';
import '../../data/gate/permission_gate.dart' show AuditEvent;
import '../../core/errors.dart';

/// 对话式研判（docs/02 F5-5）：对话流 + Agent 活动流双列 + 输入框。
final class InvestigationPage extends StatefulWidget {
  /// 创建页面。
  const InvestigationPage({
    required this.state,
    required this.controller,
    super.key,
  });

  /// 应用状态。
  final AppState state;

  /// 研判控制器（Agent 编排 agent 提供）。
  final InvestigationController controller;

  @override
  State<InvestigationPage> createState() => _InvestigationPageState();
}

class _InvestigationPageState extends State<InvestigationPage> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _activity = <RunEvent>[];
  final _messages = <_ChatMessage>[];
  StreamSubscription<RunEvent>? _sub;
  String? _runId;
  bool _running = false;
  bool _interrupted = false;
  int _hiddenClaims = 0;
  String? _failure;
  RunSummary? _summary;

  @override
  void dispose() {
    _sub?.cancel();
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final question = _input.text.trim();
    if (question.isEmpty || _running) {
      return;
    }
    if (!widget.state.hasApiKey) {
      setState(() {
        _failure =
            '无法发起研判。尚未配置主模型密钥，模型调用会失败。'
            '可前往设置 → 密钥配置主模型密钥后重试。';
      });
      return;
    }
    final runId = 'run_${DateTime.now().microsecondsSinceEpoch}';
    setState(() {
      _running = true;
      _interrupted = false;
      _hiddenClaims = 0;
      _failure = null;
      _summary = null;
      _runId = runId;
      _messages.add(_ChatMessage(role: 'user', text: question));
      _activity.clear();
    });
    _input.clear();
    _sub = widget.controller
        .run(question, runId: runId)
        .listen(
          _onEvent,
          onError: (Object error) {
            setState(() {
              _running = false;
              _failure = error is AppError ? error.message : '$error';
            });
          },
          onDone: () {
            if (mounted) {
              setState(() => _running = false);
            }
          },
        );
  }

  void _onEvent(RunEvent event) {
    if (!mounted) {
      return;
    }
    setState(() {
      _activity.add(event);
      switch (event) {
        case RunStarted():
          break;
        case AgentActivity(:final agentRole, :final action):
          _messages.add(
            _ChatMessage(role: agentRole, text: _activityLabel(action)),
          );
        case ToolInvoked(:final tool, :final denied):
          _messages.add(
            _ChatMessage(
              role: 'system',
              text: denied ? '工具 $tool 越权，未执行。' : '已调用工具 $tool。',
            ),
          );
        case ClaimProduced(
          :final text,
          :final evidenceIds,
          :final confidence,
          :final kind,
        ):
          // 缺证据的 claim 不可见（红线：结论必须可溯源）。
          if (!InvestigationRules.isVisible(evidenceIds)) {
            _hiddenClaims++;
            break;
          }
          _messages.add(
            _ChatMessage(
              role: 'claim',
              text: text,
              evidenceIds: evidenceIds,
              note: confidence,
              numeric: InvestigationRules.needsRecomputeNote(kind),
            ),
          );
        case ConflictFound(:final category, :final escalated):
          _messages.add(
            _ChatMessage(
              role: 'system',
              text:
                  '检出冲突（${_conflictLabel(category)}）'
                  '${escalated ? '，已升级人工确认' : ''}。',
            ),
          );
        case RunFailed(:final code, :final message, :final degraded):
          _running = false;
          _failure = message;
          widget.state.recordAudit(
            AuditEvent(
              ts: Clock.asOfNow(),
              type: 'run_failed',
              actor: 'coordinator',
              tool: 'investigation',
              riskLevel: ToolRiskLevel.l0,
              outcome: 'failed',
              reason: message,
              detail: {'code': code, 'degraded': degraded},
            ),
          );
          _messages.add(
            _ChatMessage(
              role: 'system',
              text: '${degraded ? '已降级为部分结论。' : ''}$message',
            ),
          );
        case RunFinished(:final summary):
          _running = false;
          _summary = summary;
          // 降级必须写审计（docs/22 全局规则「降级可见」）。
          if (summary.partial || summary.degradedRoles.isNotEmpty) {
            widget.state.recordAudit(
              AuditEvent(
                ts: Clock.asOfNow(),
                type: 'degraded',
                actor: 'coordinator',
                tool: 'investigation',
                riskLevel: ToolRiskLevel.l0,
                outcome: 'partial',
                reason: summary.degradedRoles.isEmpty
                    ? '预算耗尽，结论为部分结论'
                    : '角色降级：${summary.degradedRoles.join('、')}',
                detail: {
                  'run_id': summary.runId,
                  'partial': summary.partial,
                  'degraded_roles': summary.degradedRoles,
                  'limitations': summary.limitations,
                },
              ),
            );
          }
          _messages.add(
            _ChatMessage(role: 'system', text: _summaryText(summary)),
          );
      }
    });
    _scrollToBottom();
  }

  void _scrollToBottom() {
    if (!_scroll.hasClients) {
      return;
    }
    unawaited(
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: Tokens.motionBase,
        curve: Curves.easeOut,
      ),
    );
  }

  static String _activityLabel(String action) => switch (action) {
    'role_start' => '开始分析',
    'role_done' => '分析完成',
    'peer_review' => '复核同行结论',
    'tool_call' => '调用工具',
    'evidence_shared' => '共享证据',
    'arbitrate' => '参与仲裁',
    _ => action,
  };

  static String _conflictLabel(String category) => switch (category) {
    'fact' => '事实分歧',
    'directional' => '方向分歧',
    'preference' => '偏好差异（不计为错误）',
    _ => category,
  };

  Future<void> _cancel() async {
    final runId = _runId;
    if (runId == null) {
      return;
    }
    if (mounted) {
      setState(() {
        _running = false;
        // 已生成内容保留，只追加「已中断」标记（docs/22 屏 4）。
        _interrupted = true;
        _messages.add(
          const _ChatMessage(
            role: 'system',
            text: '已中断：以上为中断前已生成的内容。',
            interrupted: true,
          ),
        );
      });
    }
    await widget.controller.cancel(runId);
    // 不 await 订阅取消：模型调用挂起时取消会一直等，界面必须立刻返回。
    final sub = _sub;
    _sub = null;
    unawaited(sub?.cancel());
  }

  String _summaryText(RunSummary summary) =>
      InvestigationRules.summaryText(summary, hiddenClaims: _hiddenClaims);

  @override
  Widget build(BuildContext context) {
    final prefs = AppStateScope.prefsOf(context);
    final synthetic = prefs.dataMode?.synthetic ?? false;
    final readOnly = !widget.state.hasApiKey && prefs.readOnly;
    return LayoutBuilder(
      builder: (context, constraints) {
        final twoColumn = constraints.maxWidth >= 840;
        final conversation = _ConversationColumn(
          messages: _messages,
          running: _running,
          failure: _failure,
          input: _input,
          scroll: _scroll,
          onSend: _send,
          onCancel: _cancel,
          readOnly: readOnly,
          synthetic: synthetic,
          summary: _summary,
          interrupted: _interrupted,
        );
        final activity = _ActivityColumn(events: _activity);
        return Column(
          children: [
            Expanded(
              child: twoColumn
                  ? Row(
                      children: [
                        Expanded(flex: 3, child: conversation),
                        const VerticalDivider(width: 1),
                        SizedBox(width: 340, child: activity),
                      ],
                    )
                  : conversation,
            ),
            if (!twoColumn && _activity.isNotEmpty)
              SizedBox(height: 160, child: activity),
          ],
        );
      },
    );
  }
}

final class _ConversationColumn extends StatelessWidget {
  const _ConversationColumn({
    required this.messages,
    required this.running,
    required this.failure,
    required this.input,
    required this.scroll,
    required this.onSend,
    required this.onCancel,
    required this.readOnly,
    required this.synthetic,
    required this.summary,
    required this.interrupted,
  });

  final List<_ChatMessage> messages;
  final bool running;
  final String? failure;
  final TextEditingController input;
  final ScrollController scroll;
  final VoidCallback onSend;
  final VoidCallback onCancel;
  final bool readOnly;
  final bool synthetic;
  final RunSummary? summary;
  final bool interrupted;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        if (readOnly)
          const Padding(
            padding: EdgeInsets.fromLTRB(
              Tokens.space4,
              Tokens.space3,
              Tokens.space4,
              0,
            ),
            child: InlineBanner(
              message:
                  '只读模式：未配置主模型密钥，研判入口不可用。'
                  '可浏览本地数据与来源台账；到设置 → 密钥配置后可发起研判。',
              tone: BannerTone.warn,
              icon: Icons.key_off_outlined,
            ),
          ),
        if (synthetic)
          const Padding(
            padding: EdgeInsets.fromLTRB(
              Tokens.space4,
              Tokens.space3,
              Tokens.space4,
              0,
            ),
            child: Align(
              alignment: Alignment.centerLeft,
              child: SyntheticBadge(),
            ),
          ),
        Expanded(
          child: messages.isEmpty
              ? EmptyState(
                  title: '尚无对话',
                  message: '输入一个问题开始研判。结论必须绑定证据，无证据的结论不会被展示。',
                  icon: Icons.forum_outlined,
                  actionLabel: readOnly ? null : '问：当前跨境资金压力处在什么水平？',
                  onAction: readOnly
                      ? null
                      : () {
                          input.text = '当前跨境资金压力处在什么水平？';
                          onSend();
                        },
                )
              : ListView.builder(
                  controller: scroll,
                  padding: const EdgeInsets.all(Tokens.space4),
                  itemCount: messages.length + (failure == null ? 0 : 1),
                  itemBuilder: (context, index) {
                    if (failure != null && index == messages.length) {
                      return Padding(
                        padding: const EdgeInsets.only(bottom: Tokens.space3),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            InlineBanner(
                              message: failure!,
                              tone: BannerTone.error,
                            ),
                            const SizedBox(height: Tokens.space2),
                            Align(
                              alignment: Alignment.centerLeft,
                              child: OutlinedButton.icon(
                                onPressed: () =>
                                    AppShellNavigator.go(Routes.settings),
                                icon: const Icon(
                                  Icons.settings_outlined,
                                  size: 16,
                                ),
                                label: const Text('前往设置 → 密钥'),
                              ),
                            ),
                          ],
                        ),
                      );
                    }
                    return _Bubble(message: messages[index]);
                  },
                ),
        ),
        if (summary != null)
          _DecisionPanel(summary: summary!, onOpenEvidence: () {}),
        if (summary != null && summary!.partial)
          Padding(
            padding: const EdgeInsets.fromLTRB(
              Tokens.space4,
              0,
              Tokens.space4,
              Tokens.space2,
            ),
            child: InlineBanner(
              message:
                  '部分结论：${summary!.degradedRoles.isEmpty ? '预算耗尽导致覆盖不全' : '降级角色 ${summary!.degradedRoles.map(roleLabel).join('、')}'}。'
                  '数值仍来自工具重算，可点证据核对。',
              tone: BannerTone.warn,
            ),
          ),
        if (interrupted)
          Padding(
            padding: const EdgeInsets.fromLTRB(
              Tokens.space4,
              0,
              Tokens.space4,
              Tokens.space2,
            ),
            child: Align(
              alignment: Alignment.centerLeft,
              child: StatusTag(
                label: '已中断 · 可重新提问',
                tone: BannerTone.warn,
                icon: Icons.stop_circle_outlined,
              ),
            ),
          ),
        _Composer(
          input: input,
          running: running,
          onSend: onSend,
          onCancel: onCancel,
          readOnly: readOnly,
        ),
      ],
    );
  }
}

final class _Composer extends StatefulWidget {
  const _Composer({
    required this.input,
    required this.running,
    required this.onSend,
    required this.onCancel,
    required this.readOnly,
  });

  final TextEditingController input;
  final bool running;
  final VoidCallback onSend;
  final VoidCallback onCancel;
  final bool readOnly;

  @override
  State<_Composer> createState() => _ComposerState();
}

class _ComposerState extends State<_Composer> {
  bool _dragging = false;

  Future<void> _pickFiles() async {
    final picked = await FilePicker.pickFiles(dialogTitle: '选择要加入投递箱的文件');
    final paths = picked.map((file) => file.path).whereType<String>().toList();
    if (paths.isEmpty || !mounted) {
      return;
    }
    await _ingest(paths);
  }

  Future<void> _ingest(List<String> paths) async {
    final state = AppStateScope.read(context);
    final messenger = ScaffoldMessenger.of(context);
    final records = await InboxUploader.of(state).ingestAll(paths);
    final ok = records.where((r) => r.status == IngestStatus.ingested).length;
    final bad = records.length - ok;
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          bad == 0
              ? '已加入投递箱，正在清洗入库 · ${records.length} 个文件'
              : '投递完成：入库 $ok 个，被拒/需确认 $bad 个。可在投递箱查看原因。',
        ),
      ),
    );
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent event) {
    if (event is! KeyDownEvent) {
      return KeyEventResult.ignored;
    }
    // Esc 停止生成（中断后保留已生成内容，docs/22 屏 4）。
    if (event.logicalKey == LogicalKeyboardKey.escape && widget.running) {
      widget.onCancel();
      return KeyEventResult.handled;
    }
    // Ctrl+Enter 发送；Shift+Enter 换行（默认行为）。
    if (event.logicalKey == LogicalKeyboardKey.enter &&
        HardwareKeyboard.instance.isControlPressed &&
        !widget.readOnly) {
      widget.onSend();
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    return DropTarget(
      onDragEntered: (_) => setState(() => _dragging = true),
      onDragExited: (_) => setState(() => _dragging = false),
      onDragDone: (details) async {
        setState(() => _dragging = false);
        final paths = details.files
            .map((file) => file.path)
            .where((path) => path.isNotEmpty)
            .toList();
        if (paths.isNotEmpty) {
          await _ingest(paths);
        }
      },
      child: Container(
        padding: const EdgeInsets.all(Tokens.space3),
        decoration: BoxDecoration(
          border: Border(
            top: BorderSide(
              color: _dragging
                  ? Theme.of(context).colorScheme.primary
                  : Theme.of(context).dividerTheme.color ??
                        Theme.of(context).colorScheme.outline,
              width: _dragging ? 2 : 1,
            ),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Focus(
              // 键盘处理挂在整行上：焦点在输入框或按钮时 Esc / Ctrl+Enter 都生效。
              onKeyEvent: _onKey,
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  Tooltip(
                    message: widget.readOnly
                        ? '只读模式不可发起研判；配置密钥后可投递'
                        : '附件区：导入文件到投递箱（与窗口拖拽同一清洗链路）',
                    child: IconButton(
                      onPressed: widget.readOnly ? null : _pickFiles,
                      icon: const Icon(Icons.attach_file),
                    ),
                  ),
                  Expanded(
                    child: TextField(
                      controller: widget.input,
                      minLines: 1,
                      maxLines: 4,
                      enabled: !widget.readOnly,
                      decoration: InputDecoration(
                        hintText: widget.readOnly
                            ? '只读模式：未配置主模型密钥，无法发起研判'
                            : '输入研判问题，Ctrl+Enter 发送，Shift+Enter 换行',
                      ),
                    ),
                  ),
                  const SizedBox(width: Tokens.space2),
                  if (widget.running)
                    OutlinedButton(
                      onPressed: widget.onCancel,
                      child: const Text('停止生成（Esc）'),
                    )
                  else
                    Tooltip(
                      message: widget.readOnly
                          ? '未配置主模型密钥，研判入口不可用'
                          : 'Ctrl+Enter',
                      child: FilledButton(
                        onPressed: widget.readOnly ? null : widget.onSend,
                        child: const Text('发送'),
                      ),
                    ),
                ],
              ),
            ),
            if (!widget.readOnly)
              Padding(
                padding: const EdgeInsets.only(left: 48, top: 2),
                child: Text(
                  '也可把文件拖到这里或窗口任意位置；两处共用同一清洗链路。',
                  style: TextStyle(
                    fontSize: 11,
                    color: Theme.of(context).colorScheme.onSurfaceVariant,
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

final class _Bubble extends StatelessWidget {
  const _Bubble({required this.message});

  final _ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final isUser = message.role == 'user';
    final isSystem = message.role == 'system';
    final isClaim = message.role == 'claim';
    final color = isClaim
        ? theme.colorScheme.primary
        : isUser
        ? theme.colorScheme.onSurfaceVariant
        : isSystem
        ? theme.colorScheme.onSurfaceVariant
        : roleColor(message.role);
    final label = isUser
        ? '我'
        : isSystem
        ? '系统'
        : isClaim
        ? '结论'
        : roleLabel(message.role);
    final colors = SemanticColors.of(context);
    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        constraints: const BoxConstraints(maxWidth: 640),
        margin: const EdgeInsets.only(bottom: Tokens.space3),
        padding: const EdgeInsets.all(Tokens.space3),
        decoration: BoxDecoration(
          color: isUser
              ? theme.colorScheme.primary.withValues(alpha: 0.08)
              : theme.cardTheme.color,
          borderRadius: BorderRadius.circular(Tokens.radiusCard),
          border: Border.all(
            color: message.interrupted
                ? colors.warnInk.withValues(alpha: 0.5)
                : isUser
                ? theme.colorScheme.primary.withValues(alpha: 0.4)
                : color.withValues(alpha: 0.3),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  label,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w600,
                    color: color,
                  ),
                ),
                if (message.interrupted) ...[
                  const SizedBox(width: 6),
                  StatusTag(
                    label: '已中断',
                    tone: BannerTone.warn,
                    icon: Icons.stop_circle_outlined,
                  ),
                ],
              ],
            ),
            const SizedBox(height: 4),
            Text(message.text),
            if (message.numeric) ...[
              const SizedBox(height: 4),
              Text(
                '数值以工具重算为准',
                style: TextStyle(fontSize: 11, color: colors.idleInk),
              ),
            ],
            if (message.evidenceIds.isNotEmpty) ...[
              const SizedBox(height: Tokens.space2),
              Wrap(
                spacing: 6,
                runSpacing: 4,
                children: [
                  for (final id in message.evidenceIds)
                    ActionChip(
                      label: Text('证据 $id'),
                      onPressed: () =>
                          AppShellNavigator.go(Routes.evidence(id)),
                    ),
                ],
              ),
            ],
            if (message.note != null) ...[
              const SizedBox(height: 4),
              Text(
                '置信度：${message.note}',
                style: TextStyle(
                  fontSize: 11,
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

final class _ActivityColumn extends StatelessWidget {
  const _ActivityColumn({required this.events});

  final List<RunEvent> events;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.all(Tokens.space3),
          child: Row(
            children: [
              Text('Agent 活动流', style: Theme.of(context).textTheme.titleSmall),
              const Spacer(),
              Text(
                '${events.length} 条',
                style: TextStyle(
                  fontSize: 12,
                  color: Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
        const Divider(height: 1),
        Expanded(
          child: events.isEmpty
              ? const Center(child: Text('尚无活动。发起研判后会实时显示。'))
              : ListView.builder(
                  padding: const EdgeInsets.all(Tokens.space3),
                  itemCount: events.length,
                  itemBuilder: (context, index) =>
                      _ActivityItem(event: events[index]),
                ),
        ),
      ],
    );
  }
}

final class _ActivityItem extends StatelessWidget {
  const _ActivityItem({required this.event});

  final RunEvent event;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final (String title, String detail, IconData icon) = switch (event) {
      RunStarted(:final mode) => (
        '研判开始',
        '模式：$mode',
        Icons.play_circle_outline,
      ),
      AgentActivity(:final agentRole, :final action, :final detail) => (
        '${roleLabel(agentRole)} · ${_label(action)}',
        detail.toString(),
        Icons.circle_outlined,
      ),
      ToolInvoked(:final tool, :final denied, :final result) => (
        '工具 $tool',
        denied ? '越权，未执行' : (result?.toString() ?? '已执行'),
        denied ? Icons.block : Icons.build_outlined,
      ),
      ClaimProduced(:final text, :final evidenceIds) => (
        '结论',
        '$text（证据 ${evidenceIds.length} 条）',
        Icons.rule,
      ),
      ConflictFound(:final category, :final escalated) => (
        '冲突 · $category',
        escalated ? '已升级人工' : '已消解',
        Icons.compare_arrows,
      ),
      RunFailed(:final message) => ('研判失败', message, Icons.error_outline),
      RunFinished(:final summary) => (
        '研判结束',
        '风险等级：${summary.riskLevel}',
        Icons.flag_outlined,
      ),
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: Tokens.space2),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 14, color: theme.colorScheme.onSurfaceVariant),
          const SizedBox(width: 6),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title, style: const TextStyle(fontSize: 12)),
                Text(
                  detail,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 11,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                Text(
                  Clock.relative(Clock.asOfNow()),
                  style: TextStyle(
                    fontSize: 10,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  static String _label(String action) => switch (action) {
    'role_start' => '开始分析',
    'role_done' => '分析完成',
    'peer_review' => '复核同行结论',
    _ => action,
  };
}

final class _ChatMessage {
  const _ChatMessage({
    required this.role,
    required this.text,
    this.evidenceIds = const [],
    this.note,
    this.numeric = false,
    this.interrupted = false,
  });

  final String role;
  final String text;
  final List<String> evidenceIds;
  final String? note;

  /// 数值结论：界面必须标「以工具重算为准」。
  final bool numeric;

  /// 中断前已生成的内容。
  final bool interrupted;
}

/// 本次研判的决策面板：把协同过程指标摆到台面上。
///
/// 这些数字（主张/证据/冲突/降级/token/成本）此前只落审计、不上面，
/// 用户看不到"这次研判花了多少、几方分歧、是否降级"——那正是本产品
/// 相对单模型直答的可审计性所在（docs/02 F5、docs/08 §5）。
final class _DecisionPanel extends StatelessWidget {
  const _DecisionPanel({required this.summary, required this.onOpenEvidence});

  final RunSummary summary;
  final VoidCallback onOpenEvidence;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colors = SemanticColors.of(context);
    final modeLabel = switch (summary.mode) {
      'single' => '单智能体',
      'independent' => '独立分析',
      'collaborative' => '协同核验',
      'demo' => '演示',
      _ => summary.mode,
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        Tokens.space4,
        0,
        Tokens.space4,
        Tokens.space2,
      ),
      child: Container(
        padding: const EdgeInsets.all(Tokens.space3),
        decoration: BoxDecoration(
          color: theme.cardTheme.color,
          borderRadius: BorderRadius.circular(Tokens.radiusCard),
          border: Border.all(
            color: theme.dividerTheme.color ?? theme.colorScheme.outline,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text('本次研判', style: theme.textTheme.titleSmall),
                const SizedBox(width: Tokens.space2),
                RiskLevelBadge(
                  level: riskLevelFromWire(summary.riskLevel),
                ),
                const Spacer(),
                Text(
                  modeLabel,
                  style: TextStyle(
                    fontSize: 11,
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
              ],
            ),
            const SizedBox(height: Tokens.space2),
            Wrap(
              spacing: Tokens.space2,
              runSpacing: Tokens.space2,
              children: [
                MetricTile(label: '主张', value: '${summary.claimIds.length}'),
                MetricTile(label: '证据', value: '${summary.evidenceIds.length}'),
                MetricTile(
                  label: '冲突',
                  value: '${summary.conflictIds.length}',
                  tone: summary.conflictIds.isEmpty ? null : BannerTone.warn,
                ),
                MetricTile(
                  label: 'token',
                  value: '${summary.tokensUsed}',
                  hint: summary.costUsd > 0
                      ? '≈ \$${summary.costUsd.toStringAsFixed(4)}'
                      : null,
                ),
              ],
            ),
            if (summary.degradedRoles.isNotEmpty) ...[
              const SizedBox(height: Tokens.space2),
              Text(
                '降级角色：${summary.degradedRoles.map(roleLabel).join('、')}'
                '（该角色本轮未出卡，其余结论照常核验）',
                style: TextStyle(fontSize: 12, color: colors.warnInk),
              ),
            ],
            if (summary.limitations.isNotEmpty) ...[
              const SizedBox(height: Tokens.space2),
              Text(
                '局限',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
              for (final item in summary.limitations.take(3))
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Text(
                    '· $item',
                    style: TextStyle(
                      fontSize: 12,
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}
