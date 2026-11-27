import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

import 'ui.dart';

import 'package:window_manager/window_manager.dart';

import '../agents/investigation_controller.dart';
import 'app_scope.dart';
import 'app_state.dart';
import 'preferences.dart';
import 'router.dart';
import 'routes.dart';
import 'shell/app_shell.dart';
import 'shell/window_drop_zone.dart';
import 'theme/theme.dart';

/// 应用根组件。
final class CbrMawApp extends StatefulWidget {
  /// 创建应用。
  const CbrMawApp({
    required this.state,
    required this.preferences,
    required this.controller,
    super.key,
  });

  /// 应用状态。
  final AppState state;

  /// 界面偏好。
  final UiPreferences preferences;

  /// 研判控制器。
  final InvestigationController controller;

  @override
  State<CbrMawApp> createState() => _CbrMawAppState();
}

class _CbrMawAppState extends State<CbrMawApp> {
  AppRouter? _router;

  @override
  void initState() {
    super.initState();
    widget.preferences.addListener(_onPrefs);
    _rebuildRouter();
  }

  @override
  void dispose() {
    widget.preferences.removeListener(_onPrefs);
    super.dispose();
  }

  void _onPrefs() {
    if (mounted) {
      setState(_rebuildRouter);
    }
  }

  void _rebuildRouter() {
    // router 只建一次：偏好变化由 shell 内部订阅，避免重建丢导航状态。
    _router ??= AppRouter(
      state: widget.state,
      controller: widget.controller,
      preferences: widget.preferences,
      onOpenPalette: () {},
    );
  }

  /// 全局快捷键（Ctrl+1..9 切换工作台、Ctrl+K 命令面板）。
  Map<ShortcutActivator, VoidCallback> _shortcuts(BuildContext context) {
    final router = _router!.router;
    return {
      const SingleActivator(LogicalKeyboardKey.keyK, control: true): () {
        unawaited(openCommandPalette(context));
      },
      for (var i = 0; i < 9; i++)
        SingleActivator(
          LogicalKeyboardKey(LogicalKeyboardKey.digit1.keyId + i),
          control: true,
        ): () {
          final items = navItems;
          if (i < items.length) {
            router.go(items[i].path);
          }
        },
    };
  }

  @override
  Widget build(BuildContext context) {
    final router = _router!.router;
    return AppStateScope(
      state: widget.state,
      preferences: widget.preferences,
      child: ListenableBuilder(
        listenable: widget.preferences,
        builder: (context, _) => MaterialApp.router(
          title: 'CBR-MAW',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light(),
          darkTheme: AppTheme.dark(),
          themeMode: widget.preferences.themeMode,
          routerConfig: router,
          builder: (context, child) {
            // 根 DefaultTextStyle 必须来自主题：Material 之外的文本（页头、步骤条、
            // 壳层标签）会继承 WidgetsApp 的调试样式，带上黄色下划线与等宽字体。
            // 主题的 textTheme 显式带 TextDecoration.none，从根注入一次性解决。
            final base = Theme.of(context).textTheme.bodyMedium;
            final body = CallbackShortcuts(
              bindings: _shortcuts(context),
              child: Focus(
                autofocus: true,
                // 窗口任意位置都可拖入文件。
                child: WindowDropZone(child: child ?? const SizedBox.shrink()),
              ),
            );
            return base == null
                ? body
                : DefaultTextStyle(style: base, child: body);
          },
        ),
      ),
    );
  }
}

/// 窗口装配（window_manager 原生 API）。
///
/// - 记忆窗口尺寸/位置（键 `ui.window.*`）；
/// - 关闭按钮在 Windows 隐藏到托盘（进程继续），Linux/macOS 正常关闭；
/// - 最小尺寸 960×640，保证「large」档侧栏可用。
final class WindowBootstrap {
  const WindowBootstrap._();

  /// 初始化窗口。
  static Future<Window?> init({required String title}) async {
    final window = WindowManager.instance.getCurrent();
    if (window == null) {
      return null;
    }
    window
      ..title = title
      ..minimumSize = const Size(960, 640).toNative()
      ..setSize(const Size(1360, 860).toNative(), false)
      ..center()
      ..show();
    return window;
  }

  /// 恢复上次几何（没有记录则居中）。
  static Future<void> restoreGeometry(
    UiPreferences preferences,
    Window? window,
  ) async {
    if (window == null) {
      return;
    }
    final size = preferences.windowSize;
    if (size != null && size.width >= 960 && size.height >= 640) {
      window.setSize(size.toNative(), false);
    }
    final position = preferences.windowPosition;
    if (position != null) {
      window.position = position.toNative();
    } else {
      window.center();
    }
    // 尺寸/位置变化时记录（节流：只在事件到达时写）。
    window.addListener((event) {
      if (event is WindowResizedEvent) {
        unawaited(preferences.saveWindowSize(event.newSize.toSize()));
      } else if (event is WindowMovedEvent) {
        unawaited(preferences.saveWindowPosition(event.newPosition.toOffset()));
      }
    });
  }

  /// 关闭语义：Windows 隐藏到托盘，其余平台放行。
  static void handleCloseRequest(Window window) {
    window.addListener((event) {
      if (event is! WindowCloseRequestedEvent) {
        return;
      }
      if (Platform.isWindows) {
        event.request.cancel();
        window.hide();
      }
      // 非 Windows：不取消，交给系统正常关闭。
    });
  }
}
