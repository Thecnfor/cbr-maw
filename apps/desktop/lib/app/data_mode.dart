/// 数据模式（docs/22 屏 2）：三选一，决定全局是否携带 SYNTHETIC 标记。
///
/// 只描述"用户选了哪一种"，不代表数据真实可用；拿不到数据时仍按来源台账
/// 显式标注「需授权 / 不可达」，绝不填充。
enum DataMode {
  /// 投喂我的数据（推荐）。
  myData('my_data', '投喂我的数据', '拖入 CSV / Excel / ZIP，自动清洗入库'),

  /// 先看示例（SYNTHETIC）。
  sample('sample', '先看示例', '仿真数据，仅供演示，不可用于投资或监管决策'),

  /// 打开已有工作区。
  existingWorkspace('existing_workspace', '打开已有工作区', '读取本机工作区里已入库的数据');

  const DataMode(this.wire, this.label, this.description);

  /// 持久化与审计用的字面量。
  final String wire;

  /// 卡片标题。
  final String label;

  /// 卡片说明。
  final String description;

  /// 该模式是否必须全局携带 SYNTHETIC 标记。
  bool get synthetic => this == DataMode.sample;

  /// 从字面量解析；未知值返回 null（不猜）。
  static DataMode? parse(String? raw) {
    for (final value in values) {
      if (value.wire == raw) {
        return value;
      }
    }
    return null;
  }
}
