import '../ui.dart';

/// 设计 token（docs/06 §2）。
///
/// shortcut: `packages/design_system` 尚未落地（并行开发中），此处先内置最小
/// 可用子集；它落地后整体替换为 `cbr_maw_design_system` 的导出，调用方不变。
abstract final class Tokens {
  // 中性灰阶（浅 / 深）。
  static const n0 = Color(0xFFFFFFFF);
  static const n0d = Color(0xFF0B0F17);
  static const n1 = Color(0xFFF9FAFB);
  static const n1d = Color(0xFF0E141D);
  static const n2 = Color(0xFFF4F5F7);
  static const n2d = Color(0xFF131A24);
  static const n3 = Color(0xFFEDEEF1);
  static const n3d = Color(0xFF182031);
  static const n4 = Color(0xFFE5E7EB);
  static const n4d = Color(0xFF1E2634);
  static const n5 = Color(0xFFD1D5DB);
  static const n5d = Color(0xFF232C39);
  static const n6 = Color(0xFF9CA3AF);
  static const n6d = Color(0xFF2E3947);
  static const n7 = Color(0xFF6B7280);
  static const n7d = Color(0xFF475364);
  static const n8 = Color(0xFF4B5563);
  static const n8d = Color(0xFF8B95A5);
  static const n9 = Color(0xFF1F2937);
  static const n9d = Color(0xFFA9B2C0);
  static const n10 = Color(0xFF111827);
  static const n10d = Color(0xFFE8ECF2);

  // 语义色（solid / ink / tint），docs/06 §2.4。
  static const okSolid = Color(0xFF16A34A);
  static const okInk = Color(0xFF15803D);
  static const okTint = Color(0xFFECFDF3);
  static const warnSolid = Color(0xFFD97706);
  static const warnInk = Color(0xFFB45309);
  static const warnTint = Color(0xFFFFFBEB);
  static const dangerSolid = Color(0xFFDC2626);
  static const dangerInk = Color(0xFFB91C1C);
  static const dangerTint = Color(0xFFFEF2F2);
  static const infoSolid = Color(0xFF2563EB);
  static const infoInk = Color(0xFF1D4ED8);
  static const infoTint = Color(0xFFEFF6FF);
  static const idleSolid = Color(0xFF9CA3AF);
  static const idleInk = Color(0xFF656E7B);
  static const idleTint = Color(0xFFF1F3F5);

  // 深色语义色。
  static const okInkD = Color(0xFF4ADE80);
  static const okTintD = Color(0x244ADE80);
  static const warnInkD = Color(0xFFFBBF24);
  static const warnTintD = Color(0x24FBBF24);
  static const dangerInkD = Color(0xFFF87171);
  static const dangerTintD = Color(0x24F87171);
  static const infoInkD = Color(0xFF60A5FA);
  static const infoTintD = Color(0x2460A5FA);
  static const idleInkD = Color(0xFF9CA3AF);
  static const idleTintD = Color(0x249CA3AF);

  // 角色色（docs/06 §2.6）。
  static const roleFinancing = Color(0xFF0891B2);
  static const roleInvestor = Color(0xFF7C3AED);
  static const roleRegulator = Color(0xFF2563EB);
  static const roleCrossValidation = Color(0xFFD97706);

  // 圆角与间距。
  static const radiusCard = 12.0;
  static const radiusControl = 8.0;
  static const space1 = 4.0;
  static const space2 = 8.0;
  static const space3 = 12.0;
  static const space4 = 16.0;
  static const space5 = 20.0;
  static const space6 = 24.0;
  static const space8 = 32.0;

  // 动效（docs/06 §7.1）。
  static const motionFast = Duration(milliseconds: 120);
  static const motionBase = Duration(milliseconds: 200);
  static const motionSlow = Duration(milliseconds: 320);

  // 焦点环（docs/06 §5.2：2dp + 2dp offset，不依赖 hover）。
  static const focusRing = Color(0xFF2563EB);
  static const focusRingD = Color(0xFF60A5FA);
  static const focusRingWidth = 2.0;
}
