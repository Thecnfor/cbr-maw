import 'package:material_ui/material_ui.dart';

import '../tokens/colors.dart';
import '../tokens/tokens.dart';

/// 由 token 装配的 Material 3 主题（docs/06 §2、§8）。
///
/// Material 默认色板不作设计真源；这里把 [CbrPalette] 映射成 [ColorScheme]，
/// 并让所有控件焦点样式走 `focus.ring`（2dp 环 + 2dp 偏移），不依赖 hover。
abstract final class CbrTheme {
  static ThemeData light() => _build(CbrPalette.light);

  static ThemeData dark() => _build(CbrPalette.dark);

  /// `ui.theme_mode` 三态默认跟随系统（docs/06 §8.1）。
  static ThemeMode themeModeOf(ThemeMode mode) => mode;

  static ThemeData _build(CbrPalette p) {
    final bool isDark = p.isDark;
    final ColorScheme scheme = ColorScheme(
      brightness: p.brightness,
      primary: p.neutral[9],
      onPrimary: p.textInverse,
      secondary: p.statusOf(CbrStatusTone.info).solid,
      onSecondary: p.textOnStatus,
      error: p.statusOf(CbrStatusTone.danger).solid,
      onError: p.textOnStatus,
      surface: p.surfaceBase,
      onSurface: p.textPrimary,
      surfaceContainerLowest: p.surfaceSunken,
      surfaceContainerLow: p.surfaceInset,
      surfaceContainer: p.surfaceBase,
      surfaceContainerHigh: p.surfaceRaised,
      surfaceContainerHighest: p.surfaceHover,
      onSurfaceVariant: p.textSecondary,
      outline: p.borderDefault,
      outlineVariant: p.borderSubtle,
      shadow: const Color(0xFF000000),
      scrim: p.surfaceOverlay,
      inverseSurface: p.neutral[9],
      onInverseSurface: p.neutral[0],
      inversePrimary: p.neutral[6],
      surfaceTint: Colors.transparent,
    );

    final TextTheme textTheme = _textTheme(p);

    return ThemeData(
      useMaterial3: true,
      brightness: p.brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: p.surfaceSunken,
      canvasColor: p.surfaceBase,
      dividerColor: p.borderSubtle,
      disabledColor: p.textDisabled,
      // 焦点不靠 hover：hover 只是桌面附加反馈，focus 用独立环。
      focusColor: Colors.transparent,
      hoverColor: p.surfaceHover,
      // InkSparkle 依赖 shader 资源，在测试与无 GPU 环境不可用；
      // 本项目也不做装饰性动效，用 ripple 即可。
      splashFactory: InkRipple.splashFactory,
      textTheme: textTheme,
      visualDensity: VisualDensity.standard,
      dividerTheme: DividerThemeData(
        color: p.borderSubtle,
        thickness: CbrBorder.hairline,
        space: CbrBorder.hairline,
      ),
      iconTheme: IconThemeData(size: CbrIconSize.md, color: p.textSecondary),
      cardTheme: CardThemeData(
        color: p.surfaceBase,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: CbrRadius.lgAll,
          side: BorderSide(color: p.borderDefault, width: CbrBorder.hairline),
        ),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: p.surfaceBase,
        foregroundColor: p.textPrimary,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        toolbarHeight: CbrLayout.topBarTall,
        shape: Border(
          bottom: BorderSide(color: p.borderSubtle, width: CbrBorder.hairline),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: p.surfaceInset,
        isDense: true,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: CbrSpace.s4,
          vertical: CbrSpace.s3,
        ),
        border: OutlineInputBorder(
          borderRadius: CbrRadius.mdAll,
          borderSide: BorderSide(
            color: p.borderDefault,
            width: CbrBorder.hairline,
          ),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: CbrRadius.mdAll,
          borderSide: BorderSide(
            color: p.borderDefault,
            width: CbrBorder.hairline,
          ),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: CbrRadius.mdAll,
          borderSide: BorderSide(color: p.focusRing, width: CbrBorder.focus),
        ),
        hintStyle: CbrType.body.copyWith(color: p.textTertiary),
        labelStyle: CbrType.label.copyWith(color: p.textSecondary),
      ),
      tooltipTheme: TooltipThemeData(
        waitDuration: const Duration(milliseconds: 400),
        textStyle: CbrType.caption.copyWith(color: p.textInverse),
        decoration: BoxDecoration(
          color: p.neutral[9],
          borderRadius: CbrRadius.smAll,
        ),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: p.neutral[9],
        contentTextStyle: CbrType.body.copyWith(color: p.textInverse),
        shape: const RoundedRectangleBorder(borderRadius: CbrRadius.mdAll),
      ),
      navigationRailTheme: NavigationRailThemeData(
        backgroundColor: p.surfaceBase,
        indicatorColor: p.surfaceHover,
        selectedIconTheme: IconThemeData(color: p.textPrimary),
        unselectedIconTheme: IconThemeData(color: p.textSecondary),
        minWidth: CbrLayout.railWidth,
        selectedLabelTextStyle: CbrType.labelStrong.copyWith(
          color: p.textPrimary,
        ),
        unselectedLabelTextStyle: CbrType.label.copyWith(
          color: p.textSecondary,
        ),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: p.surfaceBase,
        indicatorColor: p.surfaceHover,
        labelTextStyle: WidgetStatePropertyAll<TextStyle>(
          CbrType.caption.copyWith(color: p.textSecondary),
        ),
        surfaceTintColor: Colors.transparent,
        height: 64,
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          foregroundColor: p.textPrimary,
          textStyle: CbrType.bodyStrong,
          shape: const RoundedRectangleBorder(borderRadius: CbrRadius.mdAll),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: p.neutral[9],
          foregroundColor: p.textInverse,
          textStyle: CbrType.bodyStrong,
          minimumSize: const Size(0, 36),
          shape: const RoundedRectangleBorder(borderRadius: CbrRadius.mdAll),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: p.textPrimary,
          textStyle: CbrType.bodyStrong,
          side: BorderSide(color: p.borderDefault, width: CbrBorder.hairline),
          minimumSize: const Size(0, 36),
          shape: const RoundedRectangleBorder(borderRadius: CbrRadius.mdAll),
        ),
      ),
      checkboxTheme: CheckboxThemeData(
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(2)),
        side: BorderSide(color: p.borderStrong, width: CbrBorder.hairline),
      ),
      dialogTheme: DialogThemeData(
        backgroundColor: p.surfaceRaised,
        surfaceTintColor: Colors.transparent,
        shape: const RoundedRectangleBorder(borderRadius: CbrRadius.lgAll),
        titleTextStyle: CbrType.headline2.copyWith(color: p.textPrimary),
        contentTextStyle: CbrType.body.copyWith(color: p.textSecondary),
      ),
      popupMenuTheme: PopupMenuThemeData(
        color: p.surfaceRaised,
        surfaceTintColor: Colors.transparent,
        textStyle: CbrType.body.copyWith(color: p.textPrimary),
        shape: RoundedRectangleBorder(
          borderRadius: CbrRadius.mdAll,
          side: BorderSide(color: p.borderDefault, width: CbrBorder.hairline),
        ),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: p.textSecondary,
        textColor: p.textPrimary,
        selectedColor: p.textPrimary,
        selectedTileColor: p.surfaceHover,
        minVerticalPadding: CbrSpace.s3,
        shape: const RoundedRectangleBorder(borderRadius: CbrRadius.smAll),
      ),
      // 阴影：卡片靠描边，不用 elevation。
      shadowColor: isDark ? Colors.black : const Color(0xFF111827),
    );
  }

  static TextTheme _textTheme(CbrPalette p) {
    final Color primary = p.textPrimary;
    final Color secondary = p.textSecondary;
    return TextTheme(
      displayLarge: CbrType.display1.copyWith(color: primary),
      displayMedium: CbrType.display2.copyWith(color: primary),
      displaySmall: CbrType.headline1.copyWith(color: primary),
      headlineMedium: CbrType.headline1.copyWith(color: primary),
      headlineSmall: CbrType.headline2.copyWith(color: primary),
      titleLarge: CbrType.title.copyWith(color: primary),
      titleMedium: CbrType.bodyStrong.copyWith(color: primary),
      titleSmall: CbrType.labelStrong.copyWith(color: primary),
      bodyLarge: CbrType.body.copyWith(color: primary),
      bodyMedium: CbrType.body.copyWith(color: primary),
      bodySmall: CbrType.caption.copyWith(color: secondary),
      labelLarge: CbrType.labelStrong.copyWith(color: primary),
      labelMedium: CbrType.label.copyWith(color: secondary),
      labelSmall: CbrType.micro.copyWith(color: secondary),
    );
  }
}
