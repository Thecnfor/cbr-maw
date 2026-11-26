# cbr_maw_design_system

CBR-MAW 设计系统的 Dart 实现。真源是 [`docs/06-设计系统与美学规范.md`](../../docs/06-设计系统与美学规范.md)（颜色 / 排版 / 间距 / 圆角 / 动效 / 图表色板 / 语义 token）与 [`docs/07-交互与响应式规范.md`](../../docs/07-交互与响应式规范.md)（断点 / 布局矩阵 / 交互与无障碍）。

**本包不含业务逻辑，也不读取数据。** 界面里出现的每个数值都由调用方传入；本包只负责「长什么样、怎么响应宽度、怎么被读屏读出来」。

```dart
import 'package:cbr_maw_design_system/cbr_maw_design_system.dart';
```

## 1. Token 速查

### 颜色 `CbrPalette`（浅 / 深两套常量）

| 类别 | 取法 | 说明 |
|---|---|---|
| 中性灰阶 11 级 | `palette.neutral[0..10]` | `neutral.0` 最浅 |
| 表面 | `surfaceSunken` / `surfaceBase` / `surfaceRaised` / `surfaceInset` / `surfaceHover` / `surfaceOverlay` | 层级靠明度差 + 1dp 描边，不靠阴影 |
| 描边 | `borderSubtle` / `borderDefault` / `borderStrong` | 分隔线一律 1dp |
| 焦点 | `focusRing` | 2dp 环 + 2dp 偏移 |
| 文字 | `textPrimary` / `textSecondary` / `textTertiary` / `textInverse` / `textDisabled` / `textOnStatus` | 全部实测 ≥ 4.5:1（`textTertiary` 对 `surfaceSunken` 4.73:1） |
| 状态 | `statusOf(CbrStatusTone.ok/warn/danger/info/idle)` → `.solid` / `.ink` / `.tint` | **`.solid` 只能用于图形/填充，文字一律 `.ink`** |
| 图表 | `vizColor(1..8)` | 8 色色盲友好；越界循环 |
| 角色 | `roleOf(CbrRole.financing/investor/regulator/crossValidator)` → `.solid` / `.ink` | 角色色与状态色互不重叠 |
| 涨跌 | `marketUp(CbrMarketConvention)` / `marketDown(...)` | 颜色只是冗余通道，必须同时给 ▲/▼ 与 +/− |

`CbrPalette.of(context)` 按 `Theme.brightness` 返回当前一套。

### 排版 `CbrType`

`display1` / `display2` / `headline1` / `headline2` / `title` / `body` / `bodyStrong` / `label` / `labelStrong` / `caption` / `micro` / `code` / `numericLarge` / `numeric` / `numericSmall`。
数值类已内置 `FontFeature.tabularFigures()`。字重只用 400/500/600/700。

### 尺度

| Token | 值 |
|---|---|
| `CbrSpace.s0…s11` | 0, 2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64 |
| `CbrRadius.none/xs/sm/md/lg/xl/pill` | 0, 4, 6, 8, 12, 16, 999 |
| `CbrBorder.hairline/focus/emphasis/focusOffset` | 1 / 2 / 1 / 2 |
| `CbrIconSize.xs…xxxl` | 12, 14, 16, 20, 24, 32, 40 |
| `CbrLayout` | 侧栏 248 / 折叠 64 / rail 72 / 顶栏 56·52 / 检视区 380·420 / 内容上限 1760 |
| `CbrMotion.fast/base/slow/slower` | 120 / 200 / 320 / 480 ms + 四条曲线 |

### 语义枚举

`CbrRiskLevel`（低/中/高/极高）、`CbrActionRisk`（仅查看/需确认的操作/高风险操作）、`CbrSourceStatus`（已获取/需授权/需登录/反爬受限/已过期）、`CbrRole`、`CbrMarketConvention`（cn/intl/mono）。
`.label` 扩展给出中文正式措辞；**界面不得出现裸 `L0/L1/L2`**。

## 2. 主题与断点

```dart
MaterialApp(
  theme: CbrTheme.light(),
  darkTheme: CbrTheme.dark(),
  themeMode: ThemeMode.system, // ui.theme_mode 三态
  home: CbrAppShell(/* … */),
);
```

- 焦点样式来自 `focusRing`，`focusColor` 设为透明：**焦点不依赖 hover**。
- `CbrBreakpoint.fromWidth(width)`：`compact <600` / `medium 600–839` / `expanded 840–1099` / `large 1100–1439` / `xlarge 1440–1919` / `xxlarge ≥1920`。
- 派生值：`navMode`、`inspectorMode`、`pageGutter`、`maxColumns`、`topBarHeight`、`tableRowHeight`、`chartHeight(width)`。
- **必须按内容宽度判定**：用 `CbrLayoutBuilder` 或 `LayoutBuilder` 的 `constraints.maxWidth`，不要用 `MediaQuery.sizeOf(context).width`（内嵌视图会取错）。
- 减少动画：`CbrMotionScope.duration(context, CbrMotion.slow)` 在 `disableAnimations` 时返回 `Duration.zero`。

## 3. 组件清单

| 组件 | 对应 docs/06 类名 | 要点 |
|---|---|---|
| `CbrAppShell` | `AppShell` | 侧栏/Rail/底部导航按断点切换；含「跳到主内容」 |
| `CbrSideNav` / `CbrMobileNavBar` / `CbrTopBar` / `CbrBreadcrumbs` | `SideNav` / `MobileNavBar` / `TopBar` | `Semantics(container:true, label:'主导航')`，当前项 `selected:true` |
| `CbrInspector` | `InspectorDrawer` | 常驻 / 覆盖 / 全屏三态 |
| `CbrCommandPalette` | `CommandPalette` | Esc 关闭，焦点由调用方归还 |
| `CbrKpiCard` / `CbrKpiCard.unavailable` | `KpiCard` | 不可得态**无任何占位数值** |
| `CbrMetricTile` / `CbrNumericText` | `NumericText` | tabular figures |
| `CbrEvidenceCard` | `EvidenceCard` | 引用块朗读「引用，来自〈来源〉，〈时间〉」 |
| `CbrRiskBadge` / `CbrActionRiskBadge` | `RiskBadge`（两套，不共用） | tint 底 + ink 字 + 图标 + 文字 |
| `CbrSourceStatusChip` / `CbrTag` / `CbrStaleBadge` / `CbrStatusDot` | `SourceStatusChip` / `Tag` / `StaleBadge` | 状态点有文字等价 |
| `CbrEmptyState` / `CbrErrorState` / `CbrAccessRequiredState` / `CbrSkeleton` / `CbrInlineBanner` | 同名 | 错误三段式；需授权态无占位数值 |
| `CbrDataTable<T>` | `DataTableVirtual` | `<600` 转卡片；按 `priority` 裁剪；`≥840` 冻结首列 |
| `CbrChartCard` / `CbrSeries` | `ChartCard` | 图例可切换 + 数据表等价通道 |
| `CbrConflictPanel` / `CbrDecisionPanel` / `CbrTimeline` / `CbrCostMeter` | `ConflictPanel` / `DecisionSummary` / — / `CostMeter` | 冲突双方各带证据；限制不得省略 |
| `CbrRoleCard` / `CbrMetricTable` / `CbrClaimTable` / `CbrVerificationSummary` | `AgentRoleCard` 等 | 判定窗口必须显式 |
| `CbrApprovalCard` | `ApprovalCard` | 标题「动词 + 对象」，主按钮文案具体 |
| `CbrPressable` / `CbrIconButton` | — | 焦点环 + 键盘 Enter/Space + 命中区；图标按钮强制中文 label |
| `CbrToast` | `Toast` | 成功/提示 4s，错误 8s |
| `CbrIcons` | — | Lucide 子集白名单，`byName` 拒绝未登记名 |

## 4. 新增 token

1. 先改 `docs/06`（颜色 / 尺度 / 动效的真源），确认对比度实测值。
2. 在 `lib/src/tokens/colors.dart` 或 `tokens.dart` 加常量。
3. 若是颜色，在 `test/contrast_test.dart` 补断言（ink ≥ 4.5:1、solid ≥ 3:1）。
4. 若新增状态色 / 角色色，同步 `CbrPalette` 的浅深两套。

## 5. 新增组件

1. 组件放 `lib/src/components/`，类名 `Cbr*`，只依赖 token 与 `CbrPalette.of(context)`。
2. 必须实现相关状态（加载 / 空 / 错误 / 禁用 / 无权限），错误态用三段式。
3. 无障碍：容器语义、`selected`、`expanded`、图标按钮 label、状态点文字等价。
4. 在 `lib/cbr_maw_design_system.dart` 导出。
5. 在 `test/` 补 widget 测试（含窄屏与语义断言）。

## 6. 验证

```bash
cd /mnt/shared/recently/CBR
dart analyze packages/design_system
flutter test packages/design_system
```
