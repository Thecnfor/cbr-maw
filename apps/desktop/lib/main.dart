import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

import './app/ui.dart';

import 'app/agent_bootstrap.dart';
import 'app/app.dart';
import 'app/app_state.dart';
import 'app/preferences.dart';

/// 启动入口。
///
/// 平台约定：桌面端启用 window_manager；其他平台（含 Android）跳过窗口管理。
/// Android 无 sidecar，所有 RPC 会显式返回 `E_PLATFORM_UNSUPPORTED`（由内核侧实现）。
Future<void> main(List<String> args) async {
  WidgetsFlutterBinding.ensureInitialized();
  await SystemChannels.platform
      .invokeMethod<void>('SystemChrome.setApplicationSwitcherDescription', {
        'label': 'CBR-MAW',
        'primaryColor': 0xFF2563EB,
      })
      .catchError((Object _) {});
  final window = _isDesktop
      ? await WindowBootstrap.init(title: 'CBR-MAW')
      : null;
  final state = await AppState.bootstrap(args);
  final preferences = await UiPreferences.load();
  if (_isDesktop) {
    await WindowBootstrap.restoreGeometry(preferences, window);
    if (window != null) {
      WindowBootstrap.handleCloseRequest(window);
    }
  }
  final controller = await AgentBootstrapFactory.create(state);
  runApp(
    CbrMawApp(state: state, preferences: preferences, controller: controller),
  );
}

bool get _isDesktop =>
    Platform.isWindows || Platform.isLinux || Platform.isMacOS;
