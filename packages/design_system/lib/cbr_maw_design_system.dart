/// CBR-MAW 设计系统。
///
/// 真源：[docs/06-设计系统与美学规范.md]（颜色 / 排版 / 间距 / 圆角 / 动效 /
/// 图表色板 / 语义 token）与 [docs/07-交互与响应式规范.md]（断点 / 布局矩阵 /
/// 交互与无障碍）。
///
/// - token：[CbrPalette] / [CbrType] / [CbrSpace] / [CbrRadius] / [CbrMotion] 等
/// - 主题：[CbrTheme.light] / [CbrTheme.dark]（Material 3，焦点不依赖 hover）
/// - 断点：[CbrBreakpoint] + [CbrLayoutBuilder] + [CbrBreakpointScope]
/// - 组件：外壳 / 导航 / 顶栏 / 检视区 / 卡片 / 表格 / 图表 / 状态 / Toast
library;

export 'src/components/badges.dart';
export 'src/components/cards.dart';
export 'src/components/chart.dart';
export 'src/components/data_table.dart';
export 'src/components/icons.dart';
export 'src/components/inspector.dart';
export 'src/components/navigation.dart';
export 'src/components/panels.dart';
export 'src/components/pressable.dart';
export 'src/components/shell.dart';
export 'src/components/states.dart';
export 'src/components/toast.dart';
export 'src/layout/breakpoints.dart';
export 'src/layout/motion_scope.dart';
export 'src/theme/theme.dart';
export 'src/tokens/colors.dart';
export 'src/tokens/tokens.dart';
