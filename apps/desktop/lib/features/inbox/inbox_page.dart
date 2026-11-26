import 'dart:io';

import '../../app/ui.dart';

import 'package:file_picker/file_picker.dart';
import 'package:path/path.dart' as p;

import '../../app/app_scope.dart';
import '../../app/inbox_log.dart';
import '../../app/theme/theme.dart';
import '../../app/theme/tokens.dart';
import '../../app/widgets/common.dart';
import '../../app/widgets/states.dart';
import '../../app/widgets/synthetic.dart';
import '../../core/clock.dart';

/// 投递箱（docs/02 F4-5、docs/22 屏 3）：逐文件状态 + 被拒原因 + 原文件保留。
///
/// 落点两处等价：窗口任意处拖拽（[WindowDropZone]）与对话输入框附件区，
/// 三者共用 [InboxUploader]（同一清洗链路、同一份日志）。
final class InboxPage extends StatefulWidget {
  /// 创建页面。
  const InboxPage({super.key});

  @override
  State<InboxPage> createState() => _InboxPageState();
}

class _InboxPageState extends State<InboxPage> {
  List<FileSystemEntity>? _files;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  Future<void> _reload() async {
    final state = AppStateScope.read(context);
    final dir = Directory(state.paths.inboxDir);
    try {
      if (!await dir.exists()) {
        await dir.create(recursive: true);
      }
      final entries = await dir.list().toList();
      entries.sort((a, b) => a.path.compareTo(b.path));
      if (mounted) {
        setState(() {
          _files = entries;
          _error = null;
        });
      }
    } on FileSystemException catch (e) {
      if (mounted) {
        setState(() => _error = e.message);
      }
    }
  }

  Future<void> _pickFiles() async {
    final picked = await FilePicker.pickFiles(dialogTitle: '选择要加入投递箱的文件');
    final paths = picked.map((file) => file.path).whereType<String>().toList();
    if (paths.isEmpty || !mounted) {
      return;
    }
    await _upload(paths);
  }

  Future<void> _upload(List<String> paths, {String? declaredSource}) async {
    final state = AppStateScope.read(context);
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _busy = true);
    final uploader = InboxUploader.of(state);
    final records = await uploader.ingestAll(
      paths,
      declaredSource: declaredSource,
    );
    if (!mounted) {
      return;
    }
    setState(() => _busy = false);
    final ok = records.where((r) => r.status == IngestStatus.ingested).length;
    final bad = records.length - ok;
    messenger.showSnackBar(
      SnackBar(
        content: Text(
          bad == 0
              ? '已加入投递箱，正在清洗入库 · ${records.length} 个文件'
              : '投递完成：入库 $ok 个，被拒/需确认 $bad 个。原因见下方清单。',
        ),
      ),
    );
    await _reload();
  }

  @override
  Widget build(BuildContext context) {
    final state = AppStateScope.of(context);
    final prefs = AppStateScope.prefsOf(context);
    final synthetic = prefs.dataMode?.synthetic ?? false;
    final records = state.inboxLog.records;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        PageHeader(
          title: '投递箱',
          subtitle: '把文件拖到窗口任意位置或输入框附件区即可加入；清洗结果逐文件反馈',
          actions: [
            OutlinedButton.icon(
              onPressed: _busy ? null : _pickFiles,
              icon: const Icon(Icons.upload_file_outlined, size: 16),
              label: const Text('选择文件'),
            ),
            const SizedBox(width: Tokens.space2),
            OutlinedButton.icon(
              onPressed: _reload,
              icon: const Icon(Icons.refresh, size: 16),
              label: const Text('刷新'),
            ),
          ],
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
              if (synthetic) ...[
                const Align(
                  alignment: Alignment.centerLeft,
                  child: SyntheticBadge(),
                ),
                const SizedBox(height: Tokens.space3),
              ],
              SectionCard(
                title: '路径',
                child: KeyValueRow(label: '投递箱目录', value: state.paths.inboxDir),
              ),
              const SizedBox(height: Tokens.space4),
              if (_error != null)
                ErrorStateView(
                  what: '投递箱读取失败',
                  why: _error!,
                  next: '可检查可写根目录权限后重试',
                  onRetry: _reload,
                )
              else if (_files == null)
                const Center(child: CircularProgressIndicator())
              else if (_files!.isEmpty && records.isEmpty)
                EmptyState(
                  title: '投递箱是空的',
                  message:
                      '把 CSV / Excel 拖进窗口，或点这里选择文件。'
                      '${synthetic ? '（当前为 SYNTHETIC 示例数据，不可用于投资或监管决策）' : ''}',
                  icon: Icons.move_to_inbox_outlined,
                  actionLabel: '选择文件',
                  onAction: _pickFiles,
                )
              else ...[
                if (records.isNotEmpty) ...[
                  SectionCard(
                    title: '本次投递结果',
                    trailing: TextButton(
                      onPressed: () => setState(state.inboxLog.clear),
                      child: const Text('清空记录'),
                    ),
                    child: Column(
                      children: [
                        for (final record in records)
                          _RecordRow(
                            record: record,
                            onRetry: _busy
                                ? null
                                : (declared) => _upload([
                                    record.originalPath,
                                  ], declaredSource: declared),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: Tokens.space4),
                ],
                SectionCard(
                  title: '投递箱中的文件（原文件保留，不删除）',
                  child: Column(
                    children: [
                      for (final entity in _files!)
                        ListRow(
                          title: p.basename(entity.path),
                          subtitle: entity is File
                              ? '${_size(entity)} · 已复制到投递箱'
                              : '目录',
                          leading: Icon(
                            entity is Directory
                                ? Icons.folder_outlined
                                : Icons.description_outlined,
                            size: 18,
                          ),
                        ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: Tokens.space4),
              const SectionCard(
                title: '列名映射',
                child: Text(
                  '自动映射结果会逐条展示；未命中的列落到 custom.* 并标「需人工确认」。'
                  '当前版本改映射需在来源台账里登记序列后重新投递（见设置 → 数据源）。',
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  static String _size(File file) {
    final bytes = file.lengthSync();
    if (bytes < 1024) {
      return '$bytes B';
    }
    if (bytes < 1024 * 1024) {
      return '${(bytes / 1024).toStringAsFixed(1)} KB';
    }
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
}

/// 逐文件状态行：状态 + 序列 + 行数 + 原因 + 重试（可改声明来源）。
final class _RecordRow extends StatefulWidget {
  const _RecordRow({required this.record, required this.onRetry});

  final IngestRecord record;
  final Future<void> Function(String? declaredSource)? onRetry;

  @override
  State<_RecordRow> createState() => _RecordRowState();
}

class _RecordRowState extends State<_RecordRow> {
  late final _declared = TextEditingController(
    text: widget.record.declaredSource ?? '',
  );

  @override
  void dispose() {
    _declared.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final record = widget.record;
    final colors = SemanticColors.of(context);
    final (BannerTone tone, IconData icon, Color ink) = switch (record.status) {
      IngestStatus.ingested => (
        BannerTone.ok,
        Icons.check_circle_outline,
        colors.okInk,
      ),
      IngestStatus.needsConfirmation => (
        BannerTone.warn,
        Icons.help_outline,
        colors.warnInk,
      ),
      IngestStatus.rejected => (
        BannerTone.error,
        Icons.error_outline,
        colors.dangerInk,
      ),
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: Tokens.space3),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 16, color: ink),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  record.fileName,
                  style: theme.textTheme.bodyMedium,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              StatusTag(label: record.status.label, tone: tone),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            record.status == IngestStatus.ingested
                ? '序列 ${record.seriesId} · ${record.rows} 行 · ${Clock.display(record.at)}'
                : '原因：${record.reason ?? '未提供原因'}',
            style: TextStyle(
              fontSize: 12,
              color: record.status == IngestStatus.ingested
                  ? theme.colorScheme.onSurfaceVariant
                  : ink,
            ),
          ),
          if (record.status != IngestStatus.ingested) ...[
            const SizedBox(height: Tokens.space2),
            Row(
              children: [
                SizedBox(
                  width: 220,
                  child: TextField(
                    controller: _declared,
                    decoration: const InputDecoration(
                      labelText: '声明来源（可选，重试时生效）',
                      isDense: true,
                    ),
                  ),
                ),
                const SizedBox(width: Tokens.space2),
                TextButton(
                  onPressed: widget.onRetry == null
                      ? null
                      : () => widget.onRetry!(
                          _declared.text.trim().isEmpty
                              ? null
                              : _declared.text.trim(),
                        ),
                  child: const Text('重新投递'),
                ),
                const SizedBox(width: Tokens.space1),
                Text(
                  '原文件保留在投递箱',
                  style: TextStyle(fontSize: 11, color: colors.idleInk),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
