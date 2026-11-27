/// 动作风险分级（docs/03 §5）。
///
/// 组件白名单（渲染安全边界）已收口到 `lib/genui/adapter/surface_bridge.dart`，
/// 真源是 `cbrRegisteredComponentNames`（docs/12 P1-5）；本文件只保留
/// 动作风险级，供 `ActionDispatcher` 使用，不再维护第二份组件名单。
library;

/// 组件风险声明（组件被点击时的默认动作风险级）。
enum ActionRisk {
  l0('L0', 0),
  l1('L1', 1),
  l2('L2', 2);

  const ActionRisk(this.wire, this.order);

  /// JSON 字面量。
  final String wire;

  /// 强度序。
  final int order;

  /// 从字面量解析。
  static ActionRisk parse(String raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    throw ArgumentError('非法动作风险级：$raw');
  }
}

/// 取更强风险级（缺省按 L1 保守处理）。
ActionRisk strongerRisk(ActionRisk? a, ActionRisk? b) {
  final left = a ?? ActionRisk.l1;
  final right = b ?? ActionRisk.l1;
  return left.order >= right.order ? left : right;
}
