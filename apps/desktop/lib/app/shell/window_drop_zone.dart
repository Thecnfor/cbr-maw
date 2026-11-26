import 'package:desktop_drop/desktop_drop.dart';

import '../app_scope.dart';
import '../inbox_log.dart';
import '../ui.dart';

/// 窗口级拖拽：把文件拖到**窗口任意位置**都加入投递箱（docs/07 §9.4）。
///
/// 悬停时给整体描边 + 居中提示；与对话输入框附件区共用 [InboxUploader]
/// （同一清洗链路、同一份投递日志）。
final class WindowDropZone extends StatefulWidget {
  /// 创建拖拽区。
  const WindowDropZone({required this.child, super.key});

  /// 内容。
  final Widget child;

  @override
  State<WindowDropZone> createState() => _WindowDropZoneState();
}

class _WindowDropZoneState extends State<WindowDropZone> {
  bool _dragging = false;

  Future<void> _handle(List<String> paths) async {
    if (paths.isEmpty) {
      return;
    }
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

  @override
  Widget build(BuildContext context) {
    return DropTarget(
      onDragEntered: (_) => setState(() => _dragging = true),
      onDragExited: (_) => setState(() => _dragging = false),
      onDragDone: (details) async {
        setState(() => _dragging = false);
        await _handle(
          details.files
              .map((file) => file.path)
              .where((path) => path.isNotEmpty)
              .toList(),
        );
      },
      child: Stack(
        children: [
          widget.child,
          if (_dragging)
            Positioned.fill(
              child: IgnorePointer(
                child: Container(
                  decoration: BoxDecoration(
                    border: Border.all(
                      color: Theme.of(context).colorScheme.primary,
                      width: 2,
                    ),
                    color: Theme.of(context).colorScheme.primary
                        .withValues(alpha: 0.04),
                  ),
                  alignment: Alignment.center,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 20,
                      vertical: 12,
                    ),
                    decoration: BoxDecoration(
                      color: Theme.of(context).cardTheme.color,
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(
                        color: Theme.of(context).colorScheme.primary,
                      ),
                    ),
                    child: const Text('松开以加入投递箱'),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}
