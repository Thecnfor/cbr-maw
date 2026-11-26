import 'package:flutter/widgets.dart';

/// 间距 token（docs/06 §4.1）。只用档位，禁止 5/10/15/18 这类随手值。
abstract final class CbrSpace {
  static const double s0 = 0;
  static const double s1 = 2;
  static const double s2 = 4;
  static const double s3 = 8;
  static const double s4 = 12;
  static const double s5 = 16;
  static const double s6 = 20;
  static const double s7 = 24;
  static const double s8 = 32;
  static const double s9 = 40;
  static const double s10 = 48;
  static const double s11 = 64;
}

/// 圆角 token（docs/06 §4.2）。数据容器不得超过 16dp。
abstract final class CbrRadius {
  static const double none = 0;
  static const double xs = 4;
  static const double sm = 6;
  static const double md = 8;
  static const double lg = 12;
  static const double xl = 16;
  static const double pill = 999;

  static const BorderRadius noneAll = BorderRadius.zero;
  static const BorderRadius xsAll = BorderRadius.all(Radius.circular(xs));
  static const BorderRadius smAll = BorderRadius.all(Radius.circular(sm));
  static const BorderRadius mdAll = BorderRadius.all(Radius.circular(md));
  static const BorderRadius lgAll = BorderRadius.all(Radius.circular(lg));
  static const BorderRadius xlAll = BorderRadius.all(Radius.circular(xl));
  static const BorderRadius pillAll = BorderRadius.all(Radius.circular(pill));
}

/// 描边 token（docs/06 §4.4）。分隔线一律 1dp。
abstract final class CbrBorder {
  static const double hairline = 1;
  static const double focus = 2;
  static const double emphasis = 1;
  static const double none = 0;

  /// 焦点环偏移（docs/07 §5.3）。
  static const double focusOffset = 2;
}

/// 动效 token（docs/06 §7.1 / §7.2）。
abstract final class CbrMotion {
  static const Duration fast = Duration(milliseconds: 120);
  static const Duration base = Duration(milliseconds: 200);
  static const Duration slow = Duration(milliseconds: 320);
  static const Duration slower = Duration(milliseconds: 480);

  static const Curve easeStandard = Cubic(0.2, 0, 0, 1);
  static const Curve easeEnter = Cubic(0, 0, 0, 1);
  static const Curve easeExit = Cubic(0.3, 0, 1, 1);
  static const Curve easeEmphasized = Cubic(0.2, 0, 0, 1);
}

/// 布局尺度（docs/07 §1.2）。
abstract final class CbrLayout {
  static const double sidebarExpanded = 248;
  static const double sidebarCollapsed = 64;
  static const double railWidth = 72;
  static const double topBarTall = 56;
  static const double topBarShort = 52;
  static const double inspectorAnchored = 380;
  static const double inspectorOverlayWide = 420;
  static const double commandPalette = 560;
  static const double commandPaletteWide = 640;
  static const double touchTarget = 48;
  static const double mouseTarget = 32;

  /// `xxlarge` 内容最大宽度（docs/07 §12 I-7 倾向值）。
  static const double contentMaxWidth = 1760;
}

/// 图标尺寸阶梯（docs/06 §5.2）。
abstract final class CbrIconSize {
  static const double xs = 12;
  static const double sm = 14;
  static const double md = 16;
  static const double lg = 20;
  static const double xl = 24;
  static const double xxl = 32;
  static const double xxxl = 40;
}

/// 字号阶梯（docs/06 §3.2）。数值样式统一 tabular figures。
abstract final class CbrType {
  static const String latinFamily = 'Inter';
  static const String monoFamily = 'JetBrains Mono';

  static const TextStyle display1 = TextStyle(
    fontSize: 32,
    height: 1.15,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.32,
  );
  static const TextStyle display2 = TextStyle(
    fontSize: 26,
    height: 1.2,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.26,
  );
  static const TextStyle headline1 = TextStyle(
    fontSize: 22,
    height: 1.25,
    fontWeight: FontWeight.w700,
    letterSpacing: -0.22,
  );
  static const TextStyle headline2 = TextStyle(
    fontSize: 18,
    height: 1.3,
    fontWeight: FontWeight.w600,
    letterSpacing: -0.09,
  );
  static const TextStyle title = TextStyle(
    fontSize: 16,
    height: 1.35,
    fontWeight: FontWeight.w600,
    letterSpacing: -0.08,
  );
  static const TextStyle body = TextStyle(
    fontSize: 14,
    height: 1.5,
    fontWeight: FontWeight.w400,
  );
  static const TextStyle bodyStrong = TextStyle(
    fontSize: 14,
    height: 1.5,
    fontWeight: FontWeight.w600,
  );
  static const TextStyle label = TextStyle(
    fontSize: 13,
    height: 1.4,
    fontWeight: FontWeight.w400,
  );
  static const TextStyle labelStrong = TextStyle(
    fontSize: 13,
    height: 1.4,
    fontWeight: FontWeight.w600,
  );
  static const TextStyle caption = TextStyle(
    fontSize: 12,
    height: 1.35,
    fontWeight: FontWeight.w400,
  );
  static const TextStyle micro = TextStyle(
    fontSize: 11,
    height: 1.3,
    fontWeight: FontWeight.w500,
  );
  static const TextStyle code = TextStyle(
    fontFamily: monoFamily,
    fontSize: 13,
    height: 1.5,
    fontWeight: FontWeight.w400,
  );
  static const TextStyle numericLarge = TextStyle(
    fontSize: 28,
    height: 1.1,
    fontWeight: FontWeight.w700,
    fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
  );
  static const TextStyle numeric = TextStyle(
    fontSize: 16,
    height: 1.25,
    fontWeight: FontWeight.w600,
    fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
  );
  static const TextStyle numericSmall = TextStyle(
    fontSize: 13,
    height: 1.3,
    fontWeight: FontWeight.w400,
    fontFeatures: <FontFeature>[FontFeature.tabularFigures()],
  );

  static const Map<String, TextStyle> all = <String, TextStyle>{
    'display1': display1,
    'display2': display2,
    'headline1': headline1,
    'headline2': headline2,
    'title': title,
    'body': body,
    'bodyStrong': bodyStrong,
    'label': label,
    'labelStrong': labelStrong,
    'caption': caption,
    'micro': micro,
    'code': code,
    'numericLarge': numericLarge,
    'numeric': numeric,
    'numericSmall': numericSmall,
  };
}

/// 阴影 token（docs/06 §4.3）。深色下阴影弱化，层级交给 surface 明度差。
abstract final class CbrElevation {
  static const List<BoxShadow> none = <BoxShadow>[];

  static const List<BoxShadow> light1 = <BoxShadow>[
    BoxShadow(color: Color(0x0D111827), offset: Offset(0, 1), blurRadius: 2),
    BoxShadow(color: Color(0x0F111827), offset: Offset(0, 1), blurRadius: 3),
  ];

  static const List<BoxShadow> light3 = <BoxShadow>[
    BoxShadow(
      color: Color(0x29111827),
      offset: Offset(0, 8),
      blurRadius: 24,
      spreadRadius: -8,
    ),
    BoxShadow(color: Color(0x0F111827), offset: Offset(0, 2), blurRadius: 6),
  ];

  static const List<BoxShadow> light4 = <BoxShadow>[
    BoxShadow(
      color: Color(0x47111827),
      offset: Offset(0, 24),
      blurRadius: 64,
      spreadRadius: -24,
    ),
  ];

  /// 深色下阴影不透明度压到约 25%（docs/06 §8.2）。
  static const List<BoxShadow> dark3 = <BoxShadow>[
    BoxShadow(
      color: Color(0x2E000000),
      offset: Offset(0, 8),
      blurRadius: 24,
      spreadRadius: -8,
    ),
  ];

  static List<BoxShadow> forBrightness(Brightness brightness, int level) {
    if (brightness == Brightness.dark) {
      return switch (level) {
        0 => none,
        1 || 2 || 3 => dark3,
        _ => const <BoxShadow>[
          BoxShadow(
            color: Color(0x38000000),
            offset: Offset(0, 24),
            blurRadius: 64,
            spreadRadius: -20,
          ),
        ],
      };
    }
    return switch (level) {
      0 => none,
      1 || 2 => light1,
      3 => light3,
      _ => light4,
    };
  }
}
