import '../ui.dart';
import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';

/// 设计 token（docs/06 §2）——**兼容层**。
///
/// 真源是 `cbr_maw_design_system`；本类只把包里的 token 以旧名称导出，
/// 让 `app/` 与 `features/` 的既有调用点无需改名即可完成单一真源收口
/// （docs/12 P1-5）。新代码请直接使用 `CbrPalette` / `CbrSpace` / `CbrRadius`。
abstract final class Tokens {
  // 中性灰阶（浅 / 深）。
  static final n0 = CbrPalette.light.neutral[0];
  static final n1 = CbrPalette.light.neutral[1];
  static final n2 = CbrPalette.light.neutral[2];
  static final n3 = CbrPalette.light.neutral[3];
  static final n4 = CbrPalette.light.neutral[4];
  static final n5 = CbrPalette.light.neutral[5];
  static final n6 = CbrPalette.light.neutral[6];
  static final n7 = CbrPalette.light.neutral[7];
  static final n8 = CbrPalette.light.neutral[8];
  static final n9 = CbrPalette.light.neutral[9];
  static final n10 = CbrPalette.light.neutral[10];
  static final n0d = CbrPalette.dark.neutral[0];
  static final n1d = CbrPalette.dark.neutral[1];
  static final n2d = CbrPalette.dark.neutral[2];
  static final n3d = CbrPalette.dark.neutral[3];
  static final n4d = CbrPalette.dark.neutral[4];
  static final n5d = CbrPalette.dark.neutral[5];
  static final n6d = CbrPalette.dark.neutral[6];
  static final n7d = CbrPalette.dark.neutral[7];
  static final n8d = CbrPalette.dark.neutral[8];
  static final n9d = CbrPalette.dark.neutral[9];
  static final n10d = CbrPalette.dark.neutral[10];

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

  // 圆角与间距（docs/06 §4）。
  static const radiusCard = CbrRadius.lg;
  static const radiusControl = CbrRadius.md;
  static const space1 = CbrSpace.s2;
  static const space2 = CbrSpace.s3;
  static const space3 = CbrSpace.s4;
  static const space4 = CbrSpace.s5;
  static const space5 = CbrSpace.s6;
  static const space6 = CbrSpace.s7;
  static const space8 = CbrSpace.s8;

  // 动效（docs/06 §7.1）。
  static const motionFast = CbrMotion.fast;
  static const motionBase = CbrMotion.base;
  static const motionSlow = CbrMotion.slow;

  // 焦点环（docs/06 §5.2：2dp + 2dp offset，不依赖 hover）。
  static const focusRing = Color(0xFF2563EB);
  static const focusRingD = Color(0xFF60A5FA);
  static const focusRingWidth = CbrBorder.focus;
}
