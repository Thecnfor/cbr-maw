# CBR-MAW · 桌面端（Flutter）

> 本文件面向**接手外壳/页面**的开发者：路由表、目录结构、如何加一页。
> 设计真源：`docs/06-设计系统与美学规范.md`、`docs/07-交互与响应式规范.md`、`docs/08-文案标准与术语表.md`。

## 1. 启动与验证

```bash
cd /mnt/shared/recently/CBR
flutter pub get
flutter analyze apps/desktop      # 零 error 零 warning
flutter test apps/desktop
flutter run -d linux              # 或 -d windows
```

启动参数（覆盖默认路径，仅调试用）：

```bash
# flutter run 不支持传位置参数，桌面端调试用环境变量：
CBR_DATA_HOME=/tmp/cbr CBR_HOME=$PWD flutter run -d linux
# 真实二进制（安装包布局）：
CBR-MAW --data-home /tmp/cbr --resource-home /path/to/repo
```

- `--data-home`：可写根（`workspaces/ inbox/ traces/ logs/ secrets/ configs/`）。
- `--resource-home`：只读资源根（`configs/ contracts/`）。
- 无参数时：Windows 用 `%LOCALAPPDATA%\CBR-MAW`，Linux 用 `$XDG_DATA_HOME/cbr-maw`。
- 优先级：命令行参数 > `CBR_DATA_HOME` / `CBR_HOME` > 平台默认目录。

## 2. 路由表

路径一律**英文 kebab-case**。顶层用 `StatefulShellRoute.indexedStack` 承载四条分支，
顺序即底部导航顺序。

| 路由 | 页面 | 位置 |
|---|---|---|
| `/overview` | 概览 | 分支 1 / 底部导航 |
| `/investigation` | 对话式研判 | 分支 2 / 底部导航 |
| `/risk-cards` | 风险卡 | 分支 3 / 底部导航 |
| `/risk-cards/:claimId` | 风险卡详情 | 分支 3 子路由 |
| `/timeline` | 时间线 | 分支 4 / 底部导航 |
| `/timeline/:runId` | 研判详情 | 分支 4 子路由 |
| `/evidence/:evidenceId` | 证据详情 | 根导航（从结论跳转） |
| `/sources` | 来源台账 | 侧栏 · 数据 |
| `/data-cards` | 数据卡 | 侧栏 · 数据 |
| `/inbox` | 投递箱 | 侧栏 · 数据 |
| `/scenarios` | 情景 | 侧栏 · 分析 |
| `/spatial` | 时空（v2 占位） | 侧栏 · 分析 |
| `/onboarding` | 新手引导 | 侧栏 · 系统 |
| `/diagnostics` | 诊断 | 侧栏 · 系统 |
| `/settings` | 设置 | 侧栏 · 系统 |
| `/settings/first-run` | 首次运行向导 | 设置子路由 |

- **redirect**：未配置主模型密钥 → 一律引导到 `/settings/first-run`。
- **errorBuilder**：未知路径渲染中文 404（`_NotFoundPage`）。
- **深链**：`cbr-maw://risk-cards/ev_1` 与 `https://host/timeline/run_1` 都经
  `normalizeDeepLink()` 规范化到内部路径（见 `app/routes.dart`）。

导航形态由**内容宽度**推导（不依赖设备类型）：

| 断点 | 宽度 | 导航 |
|---|---|---|
| compact | < 600 | 底部导航 4 项 |
| medium / expanded | 600–1099 | `NavigationRail` 72dp |
| large / xlarge / xxlarge | ≥ 1100 | 侧栏 248dp，可折叠为 64dp |

折叠偏好持久化到 `shared_preferences`，键 `ui.nav_collapsed`。

## 3. 目录结构

```
lib/
├─ main.dart                    # 入口：窗口装配 → 状态装配 → 控制器装配 → runApp
├─ app/
│  ├─ app.dart                  # 根组件、全局快捷键（Ctrl+K / Ctrl+1..9）、窗口装配
│  ├─ app_scope.dart            # AppStateScope（InheritedNotifier，替代 Riverpod）
│  ├─ app_state.dart            # 配置/密钥/内核/审计 的应用级状态
│  ├─ agent_bootstrap.dart      # 把 Agent 层接到门卫 + sidecar（唯一装配点）
│  ├─ router.dart               # go_router 装配（分支、redirect、404）
│  ├─ routes.dart               # 路由常量 + 导航清单 + 深链规范化
│  ├─ preferences.dart          # 界面偏好（折叠、主题、窗口几何）
│  ├─ ui.dart                   # 唯一 Material 入口（re-export material_ui）
│  ├─ layout/breakpoints.dart   # 断点、导航形态、导航尺寸
│  ├─ shell/                    # AppShell / AppSidebar / AppRail / AppBottomNav / 顶栏 / 命令面板
│  ├─ theme/                    # token 与主题
│  └─ widgets/                  # 共享组件（状态视图、页头、卡片、状态标签）
├─ core/                        # 基础设施：errors / paths / app_config / app_log / clock / secret_store / result
├─ data/
│  ├─ sidecar/                  # 传输抽象 + stdio 实现 + supervisor（懒启动/心跳/重启/退出）
│  ├─ gate/                     # 权限门卫 + 带门卫的工具调用器
│  ├─ inbox/                    # 拖入文件 → inbox/ → inbox.ingest
│  └─ workspace_repository.dart # 只读真实数据（sources/health/db.query/inbox.ingest）
├─ features/                    # 一页一目录（overview / investigation / risk_cards / evidence / timeline / …）
└─ agents/ · genui/             # 由其他 agent 负责（外壳只依赖固定接口）
```

**分层约束**（`docs/09`）：`core` 不依赖其它 `lib/` 目录；`data` 不 import `app/`/`features/`；
`features` 只通过 `AppStateScope` 与 `AppShellNavigator` 和外壳交互。

## 4. 如何加一页

1. **定义路由**：在 `app/routes.dart` 加常量，并在 `navItems` 里加一项（决定侧栏分组与命令面板）。
   底部导航只有 4 项，新页面默认进侧栏。
2. **写页面**：`lib/features/<feature>/<feature>_page.dart`。
   - 拿状态：`AppStateScope.of(context)`（订阅变化）或 `AppStateScope.read(context)`（只读一次）。
   - 拿数据：`state.repository.<method>()`；**失败就渲染错误态，不要编数值**。
   - 空态用 `EmptyState`、错误态用 `ErrorStateView`、需授权用 `AccessRequiredState`。
3. **挂路由**：
   - 属于四条分支之一 → 加到对应 `StatefulShellBranch` 的 `routes`；
   - 否则 → 加到根 `routes`（与 `/sources` 同级）。
4. **加测试**：在 `test/` 里断言路由表（`routes_test.dart` 的模式）或页面状态分支。

### 加一页的最小示例

```dart
// app/routes.dart
static const reports = '/reports';
// navItems 里加：
NavItem(path: Routes.reports, label: '报告', icon: Icons.description_outlined, group: '分析'),

// features/reports/reports_page.dart
final class ReportsPage extends StatelessWidget {
  const ReportsPage({required this.state, super.key});
  final AppState state;
  @override
  Widget build(BuildContext context) => const EmptyState(
        title: '尚无报告',
        message: '完成研判后可导出报告。',
        icon: Icons.description_outlined,
      );
}

// app/router.dart 根 routes 里加：
GoRoute(path: Routes.reports, builder: (_, _) => ReportsPage(state: state)),
```

## 5. 红线（违反即失败）

- 页面里**不得出现任何硬编码示例行情、新闻正文、遥感像元、情绪分**。
- 拿不到数据 → 显式「需授权 / 需登录 / 反爬受限 / 已过期 / 数据不足」五态；**缺失 ≠ 零值**。
- 模型不可用 → 显式失败并引导到设置页；**禁止规则模板冒充模型结论**。
- 权限判定在 Dart（`data/gate`）：越权**只记审计、不发 RPC、工具不执行**。
- 导出物与概览必须带 SYNTHETIC 标记（若数据为仿真）。

## 6. 已知依赖缺口（需 Lead 统一处理）

1. **`riverpod` 是纯 Dart 包**（`pubspec.yaml` 里是 `riverpod: ^3.5.0`，不是 `flutter_riverpod`），
   不含 `ProviderScope`/`ConsumerWidget`/`WidgetRef`。因此外壳用 `InheritedNotifier`
   （`AppStateScope`）+ `ChangeNotifier` 实现同等能力。若要换回 Riverpod，加
   `flutter_riverpod: ^3.5.0` 并把 `AppStateScope` 换成 `ProviderScope` 即可，页面调用点不变。
2. **`material_ui`** 是 Flutter 3.50 的 Material 入口，但未在 `pubspec.yaml` 直接声明
   （`flutter analyze` 报 `depend_on_referenced_packages` info）。建议 Lead 加
   `material_ui: ^1.11.1` 到依赖，或统一改用 `package:flutter/material.dart`。
3. **`packages/design_system` 与 `packages/a2ui_catalog` 仍为空**（并行开发中）。

   外壳的 token/组件先在 `lib/app/theme`、`lib/app/widgets` 内置最小子集，
   待 design_system 落地后整体替换，调用方不变。
