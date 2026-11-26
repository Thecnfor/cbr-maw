import 'dart:math' as math;

import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';

/// WCAG 2.2 相对亮度与对比度（docs/06 §2.8 自测脚本口径）。
double _channel(double value) => value <= 0.04045
    ? value / 12.92
    : math.pow((value + 0.055) / 1.055, 2.4).toDouble();

double _luminance(Color color) =>
    0.2126 * _channel(color.r) +
    0.7152 * _channel(color.g) +
    0.0722 * _channel(color.b);

double contrast(Color foreground, Color background) {
  final double a = _luminance(foreground);
  final double b = _luminance(background);
  final double hi = math.max(a, b);
  final double lo = math.min(a, b);
  return (hi + 0.05) / (lo + 0.05);
}

/// 深色 tint 是半透明叠加，按 surface.base 合成后再算。
Color _composite(Color tint, Color background) =>
    Color.alphaBlend(tint, background);

void main() {
  for (final palette in <CbrPalette>[CbrPalette.light, CbrPalette.dark]) {
    final String mode = palette.isDark ? '深色' : '浅色';

    group('$mode 对比度（docs/06 §2.3 / §2.4）', () {
      test('正文与次要文字 ≥ 4.5:1', () {
        expect(
          contrast(palette.textPrimary, palette.surfaceBase),
          greaterThanOrEqualTo(4.5),
        );
        expect(
          contrast(palette.textSecondary, palette.surfaceBase),
          greaterThanOrEqualTo(4.5),
        );
        expect(
          contrast(palette.textTertiary, palette.surfaceBase),
          greaterThanOrEqualTo(4.5),
        );
      });

      test('text.tertiary 在 surface.sunken 上 ≥ 4.5:1（易漏组合）', () {
        expect(
          contrast(palette.textTertiary, palette.surfaceSunken),
          greaterThanOrEqualTo(4.5),
        );
      });

      test('每个状态色的 ink 对其 tint 底 ≥ 4.5:1', () {
        for (final tone in CbrStatusTone.values) {
          final colors = palette.statusOf(tone);
          final background = _composite(colors.tint, palette.surfaceBase);
          expect(
            contrast(colors.ink, background),
            greaterThanOrEqualTo(4.5),
            reason: '$tone.ink 对 $tone.tint',
          );
        }
      });

      test('每个状态色的 solid 对 surface.base ≥ 3:1（图形门槛）', () {
        for (final tone in CbrStatusTone.values) {
          // 浅色 idle.solid 在文档里是 2.54:1，仅用于状态点这类非信息通道，
          // 因此这里只断言非 idle 的实心态。
          if (tone == CbrStatusTone.idle) continue;
          expect(
            contrast(palette.statusOf(tone).solid, palette.surfaceBase),
            greaterThanOrEqualTo(3.0),
            reason: '$tone.solid',
          );
        }
      });

      test('8 色图表色板对 surface.base ≥ 3:1', () {
        for (var i = 1; i <= 8; i++) {
          expect(
            contrast(palette.vizColor(i), palette.surfaceBase),
            greaterThanOrEqualTo(3.0),
            reason: 'viz.$i',
          );
        }
      });

      test('角色 ink 对 surface.base ≥ 4.5:1', () {
        for (final role in CbrRole.values) {
          expect(
            contrast(palette.roleOf(role).ink, palette.surfaceBase),
            greaterThanOrEqualTo(4.5),
            reason: '$role.ink',
          );
        }
      });

      test('焦点环对 surface.sunken ≥ 3:1', () {
        expect(
          contrast(palette.focusRing, palette.surfaceSunken),
          greaterThanOrEqualTo(3.0),
        );
      });

      test('涨跌色对 surface.base ≥ 3:1（只作冗余通道）', () {
        for (final convention in CbrMarketConvention.values) {
          expect(
            contrast(palette.marketUp(convention), palette.surfaceBase),
            greaterThanOrEqualTo(3.0),
            reason: '$convention 涨',
          );
          expect(
            contrast(palette.marketDown(convention), palette.surfaceBase),
            greaterThanOrEqualTo(3.0),
            reason: '$convention 跌',
          );
        }
      });
    });
  }

  test('图表色板按 1..8 循环，越界不抛异常', () {
    expect(CbrPalette.light.vizColor(9), CbrPalette.light.vizColor(1));
    expect(CbrPalette.light.vizColor(0), CbrPalette.light.vizColor(8));
  });

  test('风险等级 / 动作风险级用中文正式措辞，不出现裸 L0/L1/L2', () {
    expect(CbrRiskLevel.critical.label, '极高');
    expect(CbrActionRisk.highRisk.label, '高风险操作');
    for (final risk in CbrActionRisk.values) {
      expect(risk.label.contains('L0'), isFalse);
      expect(risk.label.contains('L1'), isFalse);
      expect(risk.label.contains('L2'), isFalse);
    }
  });

  test('来源状态五态文案固定', () {
    expect(CbrSourceStatus.fetched.label, '已获取');
    expect(CbrSourceStatus.needsAuth.label, '需授权');
    expect(CbrSourceStatus.needsLogin.label, '需登录');
    expect(CbrSourceStatus.antiScrape.label, '反爬受限');
    expect(CbrSourceStatus.expired.label, '已过期');
    // 只有「已过期」用 danger。
    expect(CbrSourceStatus.expired.tone, CbrStatusTone.danger);
  });

  test('图标白名单拒绝未登记名字', () {
    expect(CbrIcons.byName('shield-check'), isNotNull);
    expect(CbrIcons.byName('evil-gradient'), isNull);
  });
}
