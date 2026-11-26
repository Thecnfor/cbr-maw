import './ui.dart';

import '../data/gate/permission_gate.dart';
import 'app_state.dart';
import 'preferences.dart';

/// 应用作用域：向页面提供 [AppState] 与 [UiPreferences]。
///
/// 不用 Riverpod：本工程 `riverpod` 是纯 Dart 包，无 Flutter 绑定（见交付报告）。
final class AppStateScope extends InheritedNotifier<AppState> {
  /// 创建作用域。
  const AppStateScope({
    required AppState state,
    required this.preferences,
    required super.child,
    super.key,
  }) : super(notifier: state);

  /// 界面偏好。
  final UiPreferences preferences;

  /// 读取应用状态。
  static AppState of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppStateScope>();
    assert(scope != null, '缺少 AppStateScope');
    return scope!.notifier!;
  }

  /// 读取应用状态（不订阅变化）。
  static AppState read(BuildContext context) {
    final scope = context.getInheritedWidgetOfExactType<AppStateScope>();
    assert(scope != null, '缺少 AppStateScope');
    return scope!.notifier!;
  }

  /// 读取界面偏好。
  static UiPreferences prefsOf(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppStateScope>();
    assert(scope != null, '缺少 AppStateScope');
    return scope!.preferences;
  }

  /// 读取权限门卫（测试与诊断用）。
  static PermissionGate gateOf(BuildContext context) => of(context).gate;

  @override
  bool updateShouldNotify(covariant InheritedNotifier<AppState> oldWidget) =>
      super.updateShouldNotify(oldWidget) ||
      (oldWidget is AppStateScope && oldWidget.preferences != preferences);
}
