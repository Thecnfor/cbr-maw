import '../ui.dart';
import 'tokens.dart';

/// 主题（docs/06 §2–§3）。
///
/// 语义色只表状态；实心态与文字态分离（正文一律走 `*.ink`）。
abstract final class AppTheme {
  /// 浅色主题。
  static ThemeData light() => _build(Brightness.light);

  /// 深色主题。
  static ThemeData dark() => _build(Brightness.dark);

  static ThemeData _build(Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    final scheme =
        ColorScheme.fromSeed(
          seedColor: Tokens.infoSolid,
          brightness: brightness,
          surface: isDark ? Tokens.n2d : Tokens.n0,
          onSurface: isDark ? Tokens.n10d : Tokens.n10,
        ).copyWith(
          primary: isDark ? Tokens.infoInkD : Tokens.infoSolid,
          error: isDark ? Tokens.dangerInkD : Tokens.dangerInk,
          outline: isDark ? Tokens.n5d : Tokens.n5,
          outlineVariant: isDark ? Tokens.n4d : Tokens.n4,
        );
    final base = ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: isDark ? Tokens.n0d : Tokens.n2,
      visualDensity: VisualDensity.compact,
    );
    return base.copyWith(
      textTheme: base.textTheme.apply(
        bodyColor: isDark ? Tokens.n10d : Tokens.n10,
        displayColor: isDark ? Tokens.n10d : Tokens.n10,
      ),
      dividerTheme: DividerThemeData(
        color: isDark ? Tokens.n4d : Tokens.n4,
        thickness: 1,
        space: 1,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: isDark ? Tokens.n2d : Tokens.n0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(Tokens.radiusCard),
          side: BorderSide(color: isDark ? Tokens.n5d : Tokens.n4),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        isDense: true,
        filled: true,
        fillColor: isDark ? Tokens.n1d : Tokens.n1,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(Tokens.radiusControl),
          borderSide: BorderSide(color: isDark ? Tokens.n5d : Tokens.n5),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(Tokens.radiusControl),
          borderSide: BorderSide(color: isDark ? Tokens.n5d : Tokens.n5),
        ),
      ),
      tooltipTheme: const TooltipThemeData(
        waitDuration: Duration(milliseconds: 400),
      ),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
      ),
      // 统一焦点环：不依赖 hover，任何背景可见（docs/06 §5.2、docs/07 §5.3）。
      focusColor: (isDark ? Tokens.focusRingD : Tokens.focusRing).withValues(
        alpha: 0.24,
      ),
    );
  }
}

/// 语义色三态（solid / ink / tint），按亮度取。
final class SemanticColors {
  const SemanticColors._({
    required this.okInk,
    required this.okTint,
    required this.warnInk,
    required this.warnTint,
    required this.dangerInk,
    required this.dangerTint,
    required this.infoInk,
    required this.infoTint,
    required this.idleInk,
    required this.idleTint,
  });

  /// 按亮度取。
  factory SemanticColors.of(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark
      ? const SemanticColors._(
          okInk: Tokens.okInkD,
          okTint: Tokens.okTintD,
          warnInk: Tokens.warnInkD,
          warnTint: Tokens.warnTintD,
          dangerInk: Tokens.dangerInkD,
          dangerTint: Tokens.dangerTintD,
          infoInk: Tokens.infoInkD,
          infoTint: Tokens.infoTintD,
          idleInk: Tokens.idleInkD,
          idleTint: Tokens.idleTintD,
        )
      : const SemanticColors._(
          okInk: Tokens.okInk,
          okTint: Tokens.okTint,
          warnInk: Tokens.warnInk,
          warnTint: Tokens.warnTint,
          dangerInk: Tokens.dangerInk,
          dangerTint: Tokens.dangerTint,
          infoInk: Tokens.infoInk,
          infoTint: Tokens.infoTint,
          idleInk: Tokens.idleInk,
          idleTint: Tokens.idleTint,
        );

  /// 正常。
  final Color okInk;

  /// 正常底。
  final Color okTint;

  /// 注意。
  final Color warnInk;

  /// 注意底。
  final Color warnTint;

  /// 风险。
  final Color dangerInk;

  /// 风险底。
  final Color dangerTint;

  /// 进行中。
  final Color infoInk;

  /// 进行中底。
  final Color infoTint;

  /// 空闲。
  final Color idleInk;

  /// 空闲底。
  final Color idleTint;
}
