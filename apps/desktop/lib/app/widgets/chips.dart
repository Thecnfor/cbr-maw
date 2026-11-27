import 'package:cbr_maw_contracts/contracts_dart.dart';

import '../ui.dart';
import '../theme/theme.dart';
import '../theme/tokens.dart';
import 'states.dart';

/// 来源状态五态（docs/08 §5.1）。
///
/// 文案自足：不依赖颜色也能读出状态。
final class SourceStateChip extends StatelessWidget {
  /// 创建状态条。
  const SourceStateChip({required this.state, this.stale = false, super.key});

  /// 可达性状态。
  final SourceState state;

  /// 是否陈旧。
  final bool stale;

  /// 界面标签（「不可达」不是独立标签，是反爬受限的原因）。
  static String labelFor(SourceState state, {bool stale = false}) {
    if (stale && state == SourceState.reachable) {
      return '已过期';
    }
    return switch (state) {
      SourceState.reachable => '已获取',
      SourceState.needAuth => '需授权',
      SourceState.needLogin => '需登录',
      SourceState.restricted => '反爬受限',
      SourceState.unreachable => '反爬受限',
    };
  }

  @override
  Widget build(BuildContext context) {
    final label = labelFor(state, stale: stale);
    final tone = switch (label) {
      '已获取' => BannerTone.ok,
      '已过期' => BannerTone.error,
      _ => BannerTone.warn,
    };
    final icon = switch (label) {
      '已获取' => Icons.check_circle_outline,
      '需授权' || '需登录' => Icons.lock_outline,
      '反爬受限' => Icons.shield_outlined,
      _ => Icons.schedule,
    };
    return StatusTag(label: label, tone: tone, icon: icon);
  }
}

/// 风险等级徽章（低 / 中 / 高 / 极高）。
final class RiskLevelBadge extends StatelessWidget {
  /// 创建徽章。
  const RiskLevelBadge({required this.level, super.key});

  /// 风险等级。
  final RiskLevel level;

  /// 中文标签。
  static String labelOf(RiskLevel level) => switch (level) {
    RiskLevel.low => '低',
    RiskLevel.medium => '中',
    RiskLevel.high => '高',
    RiskLevel.critical => '极高',
  };

  @override
  Widget build(BuildContext context) {
    final label = labelOf(level);
    final tone = switch (level) {
      RiskLevel.low => BannerTone.ok,
      RiskLevel.medium => BannerTone.warn,
      RiskLevel.high || RiskLevel.critical => BannerTone.error,
    };
    final icon = switch (level) {
      RiskLevel.low => Icons.check_circle_outline,
      RiskLevel.medium => Icons.error_outline,
      RiskLevel.high => Icons.warning_amber,
      RiskLevel.critical => Icons.dangerous_outlined,
    };
    return StatusTag(label: '风险等级：$label', tone: tone, icon: icon);
  }
}

/// 风险等级解析（未知值不猜测，回落为「低」并在文案侧说明缺失）。
RiskLevel riskLevelFromWire(String? wire) => switch (wire) {
  'medium' => RiskLevel.medium,
  'high' => RiskLevel.high,
  'critical' => RiskLevel.critical,
  _ => RiskLevel.low,
};

/// 角色色（docs/06 §2.6）。
Color roleColor(String role) => switch (role) {
  'financing' => Tokens.roleFinancing,
  'investor' => Tokens.roleInvestor,
  'regulator' => Tokens.roleRegulator,
  // RoleId.crossValidator.wire 是 'crossValidator'（驼峰），不是
  // 'cross_validation'——按后者匹配会让该角色在界面上显示英文并掉成灰点。
  'crossValidator' || 'cross_validation' => Tokens.roleCrossValidation,
  'coordinator' => Tokens.infoSolid,
  _ => Tokens.idleSolid,
};

/// 角色中文名。
String roleLabel(String role) => switch (role) {
  'financing' => '融资方',
  'investor' => '投资方',
  'regulator' => '监管方',
  'crossValidator' || 'cross_validation' => '交叉验证',
  'coordinator' => '编排器',
  _ => role,
};

/// 角色徽章（图标 + 颜色 + 文字三重编码）。
final class RoleBadge extends StatelessWidget {
  /// 创建角色徽章。
  const RoleBadge({required this.role, super.key});

  /// 角色 id。
  final String role;

  @override
  Widget build(BuildContext context) {
    final color = roleColor(role);
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
        const SizedBox(width: 6),
        Text(
          roleLabel(role),
          style: TextStyle(
            fontSize: 12,
            color: color,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

/// 语义色工具再导出（供页面直接用 ink 色）。
typedef Semantic = SemanticColors;
