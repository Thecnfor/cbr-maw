import 'package:shared_preferences/shared_preferences.dart';

import 'ui.dart';

import 'data_mode.dart';
import 'layout/breakpoints.dart';

/// 用户界面偏好（持久化到 shared_preferences）。
final class UiPreferences extends ChangeNotifier {
  UiPreferences._(this._prefs, this._nav, this._dataMode);

  static const _themeKey = 'ui.theme_mode';
  static const _windowSizeKey = 'ui.window.size';
  static const _windowPositionKey = 'ui.window.position';
  static const _dataModeKey = 'ui.data_mode';
  static const _onboardingKey = 'ui.onboarding_complete';
  static const _readOnlyKey = 'ui.read_only';

  final SharedPreferences _prefs;
  NavPreferences _nav;
  DataMode? _dataMode;

  /// 打开偏好。
  static Future<UiPreferences> load() async {
    final prefs = await SharedPreferences.getInstance();
    final collapsed = prefs.getBool(NavPreferences.storageKey) ?? false;
    return UiPreferences._(
      prefs,
      NavPreferences(collapsed: collapsed),
      DataMode.parse(prefs.getString(_dataModeKey)),
    );
  }

  /// 侧栏折叠偏好。
  NavPreferences get nav => _nav;

  /// 用户选择的数据模式（null = 尚未选择）。
  DataMode? get dataMode => _dataMode;

  /// 选择数据模式并持久化。
  Future<void> setDataMode(DataMode mode) async {
    if (_dataMode == mode) {
      return;
    }
    _dataMode = mode;
    notifyListeners();
    await _prefs.setString(_dataModeKey, mode.wire);
  }

  /// 是否已完成首次上手（填密钥或显式选择只读）。
  bool get onboardingComplete => _prefs.getBool(_onboardingKey) ?? false;

  /// 是否显式进入只读模式（未填密钥但不拦截浏览）。
  bool get readOnly => _prefs.getBool(_readOnlyKey) ?? false;

  /// 标记首次上手完成。
  Future<void> completeOnboarding() async {
    await _prefs.setBool(_onboardingKey, true);
    notifyListeners();
  }

  /// 进入只读模式（可浏览本地数据与来源台账，研判入口置灰）。
  Future<void> enterReadOnly() async {
    await _prefs.setBool(_readOnlyKey, true);
    notifyListeners();
  }

  /// 退出只读模式（配好密钥后）。
  Future<void> exitReadOnly() async {
    await _prefs.setBool(_readOnlyKey, false);
    notifyListeners();
  }

  /// 主题模式（`system` / `light` / `dark`）。
  ThemeMode get themeMode => switch (_prefs.getString(_themeKey)) {
    'light' => ThemeMode.light,
    'dark' => ThemeMode.dark,
    _ => ThemeMode.system,
  };

  /// 切换侧栏折叠并持久化。
  Future<void> setNavCollapsed(bool collapsed) async {
    if (_nav.collapsed == collapsed) {
      return;
    }
    _nav = _nav.copyWith(collapsed: collapsed);
    notifyListeners();
    await _prefs.setBool(NavPreferences.storageKey, collapsed);
  }

  /// 上次窗口尺寸。
  Size? get windowSize {
    final raw = _prefs.getStringList(_windowSizeKey);
    if (raw == null || raw.length != 2) {
      return null;
    }
    final width = double.tryParse(raw[0]);
    final height = double.tryParse(raw[1]);
    if (width == null || height == null) {
      return null;
    }
    return Size(width, height);
  }

  /// 上次窗口位置。
  Offset? get windowPosition {
    final raw = _prefs.getStringList(_windowPositionKey);
    if (raw == null || raw.length != 2) {
      return null;
    }
    final dx = double.tryParse(raw[0]);
    final dy = double.tryParse(raw[1]);
    if (dx == null || dy == null) {
      return null;
    }
    return Offset(dx, dy);
  }

  /// 记录窗口尺寸。
  Future<void> saveWindowSize(Size size) async {
    await _prefs.setStringList(_windowSizeKey, [
      size.width.toStringAsFixed(1),
      size.height.toStringAsFixed(1),
    ]);
  }

  /// 记录窗口位置。
  Future<void> saveWindowPosition(Offset position) async {
    await _prefs.setStringList(_windowPositionKey, [
      position.dx.toStringAsFixed(1),
      position.dy.toStringAsFixed(1),
    ]);
  }

  /// 切换主题并持久化。
  Future<void> setThemeMode(ThemeMode mode) async {
    await _prefs.setString(_themeKey, switch (mode) {
      ThemeMode.light => 'light',
      ThemeMode.dark => 'dark',
      ThemeMode.system => 'system',
    });
    notifyListeners();
  }
}
