import 'package:material_ui/material_ui.dart';

/// 状态语义（docs/06 §2.4）。颜色只是冗余通道，组件必须同时给图标或文字。
enum CbrStatusTone { ok, warn, danger, info, idle }

/// 涨跌配色约定（docs/06 §2.7）。
enum CbrMarketConvention { cn, intl, mono }

/// 四个 Agent 角色（docs/06 §2.6、docs/08 §3）。
enum CbrRole { financing, investor, regulator, crossValidator }

/// 角色对主体给出的综合风险等级（docs/08 §4）。四档，不是动作风险级。
enum CbrRiskLevel { low, medium, high, critical }

/// 动作风险级（docs/08 §4）。界面只出现白话措辞，不出现裸 L0/L1/L2。
enum CbrActionRisk { viewOnly, confirmRequired, highRisk }

/// 一个状态色的三形态：solid 只用于图形/填充，ink 才允许作为文字色。
@immutable
class CbrStatusColors {
  const CbrStatusColors({
    required this.solid,
    required this.ink,
    required this.tint,
  });

  final Color solid;
  final Color ink;
  final Color tint;
}

@immutable
class CbrRoleColors {
  const CbrRoleColors({required this.solid, required this.ink});

  final Color solid;
  final Color ink;
}

/// 颜色 token 的当前亮度快照（docs/06 §2）。
///
/// 不继承 `ThemeExtension`：token 按亮度是两套常量，没有插值需求。
/// 组件用 `CbrPalette.of(context)` 取当前亮度的一套。
@immutable
class CbrPalette {
  const CbrPalette({
    required this.brightness,
    required this.neutral,
    required this.surfaceSunken,
    required this.surfaceBase,
    required this.surfaceRaised,
    required this.surfaceInset,
    required this.surfaceHover,
    required this.surfaceOverlay,
    required this.borderSubtle,
    required this.borderDefault,
    required this.borderStrong,
    required this.focusRing,
    required this.textPrimary,
    required this.textSecondary,
    required this.textTertiary,
    required this.textInverse,
    required this.textDisabled,
    required this.textOnStatus,
    required this.status,
    required this.viz,
    required this.roles,
  });

  final Brightness brightness;

  /// 11 级中性灰阶（`neutral.0` … `neutral.10`）。
  final List<Color> neutral;

  final Color surfaceSunken;
  final Color surfaceBase;
  final Color surfaceRaised;
  final Color surfaceInset;
  final Color surfaceHover;
  final Color surfaceOverlay;
  final Color borderSubtle;
  final Color borderDefault;
  final Color borderStrong;
  final Color focusRing;
  final Color textPrimary;
  final Color textSecondary;
  final Color textTertiary;
  final Color textInverse;
  final Color textDisabled;
  final Color textOnStatus;
  final Map<CbrStatusTone, CbrStatusColors> status;

  /// 8 色色盲友好图表色板（`viz.1` … `viz.8`），按顺序循环。
  final List<Color> viz;

  final Map<CbrRole, CbrRoleColors> roles;

  bool get isDark => brightness == Brightness.dark;

  CbrStatusColors statusOf(CbrStatusTone tone) => status[tone]!;

  CbrRoleColors roleOf(CbrRole role) => roles[role]!;

  /// `colorIndex` 取 1..8，越界按色板循环（docs/06 §2.5）。
  Color vizColor(int colorIndex) => viz[(colorIndex - 1) % viz.length];

  /// 涨：颜色只是冗余通道，调用方必须同时给 ▲ 与正号。
  Color marketUp(CbrMarketConvention convention) => switch (convention) {
    CbrMarketConvention.cn => const Color(0xFFC62828),
    CbrMarketConvention.intl => const Color(0xFF2E7D32),
    CbrMarketConvention.mono =>
      isDark ? const Color(0xFFE8ECF2) : const Color(0xFF1F2937),
  };

  /// 跌。
  Color marketDown(CbrMarketConvention convention) => switch (convention) {
    CbrMarketConvention.cn => const Color(0xFF2E7D32),
    CbrMarketConvention.intl => const Color(0xFFC62828),
    CbrMarketConvention.mono =>
      isDark ? const Color(0xFFA9B2C0) : const Color(0xFF6B7280),
  };

  static CbrPalette of(BuildContext context) =>
      Theme.of(context).brightness == Brightness.dark ? dark : light;

  static const CbrPalette light = CbrPalette(
    brightness: Brightness.light,
    neutral: <Color>[
      Color(0xFFFFFFFF),
      Color(0xFFF9FAFB),
      Color(0xFFF4F5F7),
      Color(0xFFEDEEF1),
      Color(0xFFE5E7EB),
      Color(0xFFD1D5DB),
      Color(0xFF9CA3AF),
      Color(0xFF6B7280),
      Color(0xFF4B5563),
      Color(0xFF1F2937),
      Color(0xFF111827),
    ],
    surfaceSunken: Color(0xFFF4F5F7),
    surfaceBase: Color(0xFFFFFFFF),
    surfaceRaised: Color(0xFFFFFFFF),
    surfaceInset: Color(0xFFF9FAFB),
    surfaceHover: Color(0xFFEDEEF1),
    surfaceOverlay: Color(0x730B1220),
    borderSubtle: Color(0xFFE5E7EB),
    borderDefault: Color(0xFFD1D5DB),
    borderStrong: Color(0xFF9CA3AF),
    focusRing: Color(0xFF2563EB),
    textPrimary: Color(0xFF111827),
    textSecondary: Color(0xFF4B5563),
    textTertiary: Color(0xFF656E7B),
    textInverse: Color(0xFFFFFFFF),
    textDisabled: Color(0xFFB6BCC6),
    textOnStatus: Color(0xFFFFFFFF),
    status: <CbrStatusTone, CbrStatusColors>{
      CbrStatusTone.ok: CbrStatusColors(
        solid: Color(0xFF16A34A),
        ink: Color(0xFF15803D),
        tint: Color(0xFFECFDF3),
      ),
      CbrStatusTone.warn: CbrStatusColors(
        solid: Color(0xFFD97706),
        ink: Color(0xFFB45309),
        tint: Color(0xFFFFFBEB),
      ),
      CbrStatusTone.danger: CbrStatusColors(
        solid: Color(0xFFDC2626),
        ink: Color(0xFFB91C1C),
        tint: Color(0xFFFEF2F2),
      ),
      CbrStatusTone.info: CbrStatusColors(
        solid: Color(0xFF2563EB),
        ink: Color(0xFF1D4ED8),
        tint: Color(0xFFEFF6FF),
      ),
      CbrStatusTone.idle: CbrStatusColors(
        solid: Color(0xFF9CA3AF),
        ink: Color(0xFF656E7B),
        tint: Color(0xFFF1F3F5),
      ),
    },
    viz: <Color>[
      Color(0xFF3B6FD4),
      Color(0xFFD97706),
      Color(0xFF0E9384),
      Color(0xFF7C3AED),
      Color(0xFFC2410C),
      Color(0xFF4D7C0F),
      Color(0xFF0891B2),
      Color(0xFFA21CAF),
    ],
    roles: <CbrRole, CbrRoleColors>{
      CbrRole.financing: CbrRoleColors(
        solid: Color(0xFF0891B2),
        ink: Color(0xFF0E7490),
      ),
      CbrRole.investor: CbrRoleColors(
        solid: Color(0xFF7C3AED),
        ink: Color(0xFF7C3AED),
      ),
      CbrRole.regulator: CbrRoleColors(
        solid: Color(0xFF2563EB),
        ink: Color(0xFF2563EB),
      ),
      CbrRole.crossValidator: CbrRoleColors(
        solid: Color(0xFFD97706),
        ink: Color(0xFFB45309),
      ),
    },
  );

  static const CbrPalette dark = CbrPalette(
    brightness: Brightness.dark,
    neutral: <Color>[
      Color(0xFF0B0F17),
      Color(0xFF0E141D),
      Color(0xFF131A24),
      Color(0xFF182031),
      Color(0xFF1E2634),
      Color(0xFF232C39),
      Color(0xFF2E3947),
      Color(0xFF475364),
      Color(0xFF8B95A5),
      Color(0xFFA9B2C0),
      Color(0xFFE8ECF2),
    ],
    surfaceSunken: Color(0xFF0B0F17),
    surfaceBase: Color(0xFF131A24),
    surfaceRaised: Color(0xFF1A2230),
    surfaceInset: Color(0xFF0E141D),
    surfaceHover: Color(0xFF1E2634),
    surfaceOverlay: Color(0x9E000000),
    borderSubtle: Color(0xFF232C39),
    borderDefault: Color(0xFF2E3947),
    borderStrong: Color(0xFF475364),
    focusRing: Color(0xFF60A5FA),
    textPrimary: Color(0xFFE8ECF2),
    textSecondary: Color(0xFFA9B2C0),
    textTertiary: Color(0xFF8B95A5),
    textInverse: Color(0xFF0B0F17),
    textDisabled: Color(0xFF5C6675),
    textOnStatus: Color(0xFF0B0F17),
    status: <CbrStatusTone, CbrStatusColors>{
      CbrStatusTone.ok: CbrStatusColors(
        solid: Color(0xFF22C55E),
        ink: Color(0xFF4ADE80),
        tint: Color(0x244ADE80),
      ),
      CbrStatusTone.warn: CbrStatusColors(
        solid: Color(0xFFF59E0B),
        ink: Color(0xFFFBBF24),
        tint: Color(0x24FBBF24),
      ),
      CbrStatusTone.danger: CbrStatusColors(
        solid: Color(0xFFEF4444),
        ink: Color(0xFFF87171),
        tint: Color(0x24F87171),
      ),
      CbrStatusTone.info: CbrStatusColors(
        solid: Color(0xFF3B82F6),
        ink: Color(0xFF60A5FA),
        tint: Color(0x2460A5FA),
      ),
      CbrStatusTone.idle: CbrStatusColors(
        solid: Color(0xFF6B7280),
        ink: Color(0xFF9CA3AF),
        tint: Color(0x249CA3AF),
      ),
    },
    viz: <Color>[
      Color(0xFF6C9BE8),
      Color(0xFFF0A44B),
      Color(0xFF34C2B0),
      Color(0xFFA78BFA),
      Color(0xFFF08A5D),
      Color(0xFF9DC15A),
      Color(0xFF4FC3E8),
      Color(0xFFE17FD0),
    ],
    roles: <CbrRole, CbrRoleColors>{
      CbrRole.financing: CbrRoleColors(
        solid: Color(0xFF4FC3E8),
        ink: Color(0xFF4FC3E8),
      ),
      CbrRole.investor: CbrRoleColors(
        solid: Color(0xFFA78BFA),
        ink: Color(0xFFA78BFA),
      ),
      CbrRole.regulator: CbrRoleColors(
        solid: Color(0xFF60A5FA),
        ink: Color(0xFF60A5FA),
      ),
      CbrRole.crossValidator: CbrRoleColors(
        solid: Color(0xFFFBBF24),
        ink: Color(0xFFFBBF24),
      ),
    },
  );
}

/// 中文正式名称（docs/08 §3.1、§4.1）。界面只允许用这些措辞。
extension CbrRiskLevelLabel on CbrRiskLevel {
  String get label => switch (this) {
    CbrRiskLevel.low => '低',
    CbrRiskLevel.medium => '中',
    CbrRiskLevel.high => '高',
    CbrRiskLevel.critical => '极高',
  };

  CbrStatusTone get tone => switch (this) {
    CbrRiskLevel.low => CbrStatusTone.ok,
    CbrRiskLevel.medium => CbrStatusTone.warn,
    CbrRiskLevel.high => CbrStatusTone.danger,
    CbrRiskLevel.critical => CbrStatusTone.danger,
  };
}

extension CbrActionRiskLabel on CbrActionRisk {
  /// 禁止出现裸 `L0/L1/L2`（docs/08 §4.1）。
  String get label => switch (this) {
    CbrActionRisk.viewOnly => '仅查看',
    CbrActionRisk.confirmRequired => '需确认的操作',
    CbrActionRisk.highRisk => '高风险操作',
  };

  CbrStatusTone get tone => switch (this) {
    CbrActionRisk.viewOnly => CbrStatusTone.idle,
    CbrActionRisk.confirmRequired => CbrStatusTone.warn,
    CbrActionRisk.highRisk => CbrStatusTone.danger,
  };
}

extension CbrRoleLabel on CbrRole {
  String get label => switch (this) {
    CbrRole.financing => '融资方',
    CbrRole.investor => '投资方',
    CbrRole.regulator => '监管方',
    CbrRole.crossValidator => '交叉验证',
  };
}

extension CbrMarketConventionLabel on CbrMarketConvention {
  String get label => switch (this) {
    CbrMarketConvention.cn => '中国惯例（红涨绿跌）',
    CbrMarketConvention.intl => '国际惯例（绿涨红跌）',
    CbrMarketConvention.mono => '单色',
  };
}
