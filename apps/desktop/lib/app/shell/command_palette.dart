import 'package:flutter/services.dart' show LogicalKeyboardKey;

import '../ui.dart';
import '../layout/breakpoints.dart';
import '../routes.dart';
import '../theme/tokens.dart';

/// 命令面板（Ctrl+K）：分组跳转 + 无结果态。
///
/// 焦点陷阱由 [FocusScope.trapFocus] 保证；Esc 关闭并归还焦点。
final class CommandPalette extends StatefulWidget {
  /// 创建命令面板。
  const CommandPalette({
    required this.onSelect,
    required this.onClose,
    super.key,
  });

  /// 选中路径。
  final void Function(String path) onSelect;

  /// 关闭。
  final VoidCallback onClose;

  /// 显示命令面板并返回是否发生了跳转。
  static Future<void> show(
    BuildContext context, {
    required void Function(String path) onSelect,
  }) {
    return showDialog<void>(
      context: context,
      barrierColor: const Color(0xFF0B1220),
      builder: (dialogContext) => CommandPalette(
        onSelect: (path) {
          Navigator.of(dialogContext).pop();
          onSelect(path);
        },
        onClose: () => Navigator.of(dialogContext).pop(),
      ),
    );
  }

  @override
  State<CommandPalette> createState() => _CommandPaletteState();
}

class _CommandPaletteState extends State<CommandPalette> {
  final _controller = TextEditingController();
  final _focus = FocusNode();

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
    super.dispose();
  }

  List<NavItem> get _results {
    final query = _controller.text.trim().toLowerCase();
    if (query.isEmpty) {
      return navItems;
    }
    return navItems
        .where(
          (item) =>
              item.label.toLowerCase().contains(query) ||
              item.path.toLowerCase().contains(query) ||
              item.group.toLowerCase().contains(query),
        )
        .toList();
  }

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final isCompact = Breakpoint.of(width) == Breakpoint.compact;
    final results = _results;
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.escape): widget.onClose,
      },
      child: FocusScope(
        autofocus: true,
        child: Center(
          child: Material(
            color: Colors.transparent,
            child: ConstrainedBox(
              constraints: BoxConstraints(
                maxWidth: isCompact ? width : 640,
                maxHeight: 480,
              ),
              child: Container(
                decoration: BoxDecoration(
                  color: Theme.of(context).cardTheme.color,
                  borderRadius: BorderRadius.circular(Tokens.radiusCard),
                  border: Border.all(
                    color: Theme.of(context).colorScheme.outline,
                  ),
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Padding(
                      padding: const EdgeInsets.all(Tokens.space3),
                      child: TextField(
                        controller: _controller,
                        focusNode: _focus,
                        autofocus: true,
                        onChanged: (_) => setState(() {}),
                        decoration: const InputDecoration(
                          hintText: '跳转到页面或工作台…',
                          prefixIcon: Icon(Icons.search, size: 18),
                        ),
                      ),
                    ),
                    const Divider(height: 1),
                    if (results.isEmpty)
                      const Padding(
                        padding: EdgeInsets.all(Tokens.space6),
                        child: Text('没有匹配的页面。可换个关键词，或按 Esc 关闭。'),
                      )
                    else
                      Flexible(
                        child: ListView.builder(
                          shrinkWrap: true,
                          itemCount: results.length,
                          itemBuilder: (context, index) {
                            final item = results[index];
                            return ListTile(
                              dense: true,
                              leading: Icon(item.icon, size: 18),
                              title: Text(item.label),
                              subtitle: Text(item.group),
                              onTap: () => widget.onSelect(item.path),
                            );
                          },
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
