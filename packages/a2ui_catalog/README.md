# cbr_maw_a2ui_catalog

CBR-MAW 自有 A2UI 组件目录，是**安全边界**：Agent 只能渲染登记过的组件，且只能传语义参数。真源是 [`docs/06-设计系统与美学规范.md §9`](../../docs/06-设计系统与美学规范.md)（VC-1~VC-8）与 [`docs/04-动态UI与Agent-Native设计.md §5`](../../docs/04-动态UI与Agent-Native设计.md)。

依赖 `genui ^0.10.4`。组件实现**全部复用** `cbr_maw_design_system` 的同一份 widget（VC-1），本包不另写皮肤。

```dart
import 'package:cbr_maw_a2ui_catalog/cbr_maw_a2ui_catalog.dart';
```

## 1. 组件清单

| 组件名（UpperCamelCase） | kebab id | props 要点 | 状态 |
|---|---|---|---|
| `RoleCard` | `role-card` | `role` `riskLevel` `horizonDays` `headline` `claimIds[]` `evidenceIds[]` `degraded` | state |
| `MetricTable` | `metric-table` | `columns[]`(key/title/unit/align/format/priority) `rows[]` `density` | state |
| `ClaimTable` | `claim-table` | `claims[]`(text/verdict/evidenceIds[]/confidence) | state |
| `DataCardList` | `data-card-list` | `cards[]`(title/value/unit/trend/trendDirection/stale/level/status/sourceName) | state |
| `EvidenceList` | `evidence-list` | `items[]`(title/excerpt/source/timestamp/reachable/reason/expanded) | state |
| `ConflictDiff` | `conflict-diff` | `roleA` `roleB` `viewA` `viewB` `evidenceA[]` `evidenceB[]` `resolution` | state |
| `CrossValidationList` | `cross-validation-list` | `findings[]`(verdict ∈ confirmed/refuted/uncertain, note, claimId) | state |
| `VerificationSummary` | `verification-summary` | `confirmed` `refuted` `uncertain` `coverage` `gaps[]` | state |
| `DecisionSummary` | `decision-summary` | `conclusion` `riskLevel` `supports[]` `limitations[]` | state |
| `CostMeter` | `cost-meter` | `tokens` `toolCalls` `coordinationCost` `budget` | state |
| `ConfirmCard` | `confirm-card` | `title` `actionRisk` `body[]` `confirmLabel` `cancelLabel` `action` | state |
| `ChartCard` | `chart-card` | `title` `series[]`(name/points[]/colorIndex 1..8/dashed) | state |
| `DataTable` | `data-table` | `columns[]`(key/title/priority/align/format) `rows[]` | state |
| `SourceChip` | `source-chip` | `source` `status`(五态) `lastSuccessAt` `reason` | state |
| `EmptyState` | `empty-state` | `icon`(白名单名) `title` `description` `primaryAction` `secondaryAction` `action` | — |
| `ErrorState` | `error-state` | `title` `reason` `nextStep` `retryable` `action` | — |
| `AccessRequired` | `access-required` | `source` `reason` `status` `actionLabel` `action` | — |
| `ProgressBar` | `progress-bar` | `value` `total` `label` | state |
| `Tag` | `tag` | `text` `tone`(ok/warn/danger/info/idle) | — |
| `Divider` | `divider` | `inset` | — |
| `Text` | `text` | `text` `variant`(body/title/caption/code) `emphasis` | — |

`state` 取值固定为 `ready | loading | empty | error | disabled`；组件统一经 `CbrCatalogStateHost` 渲染（`disabled` 用 `IgnorePointer` + `Semantics(enabled:false)`，内容仍在）。

## 2. 安全边界

```dart
final result = cbrValidateStrict(surfaceId: 's1', components: [
  (id: 'root', type: 'RoleCard', props: {'role': 'financing', 'headline': '…'}),
]);
if (!result.isAccepted) {
  // 拒绝该 surface 并写 renderError{surfaceId}；对话流只追加纯文本摘要。
  audit.log(result.violation.toString());
}
```

拒绝的三类（**全部显式失败，不静默丢弃**，docs/02 F3-2、docs/06 VC-5）：

| kind | 触发 |
|---|---|
| `unknownComponent` | 组件名不在 `cbrRegisteredComponentNames` |
| `unknownProperty` | 参数名不在该组件 schema 的 `properties` 里（颜色 / 字号 / 间距等天然被拒） |
| `invalidComponentId` | 节点 id 不是 kebab-case（docs/03 §10） |

允许的参数集由组件 schema **推导**（`cbrAllowedPropsFor`），不另维护一份白名单，避免漂移。

## 3. 接入 genui

```dart
final catalog = buildCbrCatalog();          // 含 systemPromptFragments
final controller = SurfaceController(catalogs: [catalog]);
final clientCaps = controller.clientCapabilities; // 含全部组件 schema
```

- `cbrCatalogId = 'cn.cbrmaw.a2ui.catalog'`；`cbrCatalogVersion = '1.0.0'`，**独立于 A2UI 协议版本**（VC-6）。升级 catalog 必须同步更新 Agent 系统提示并记变更日志。
- 图标只接受 `CbrIcons.byName` 白名单里的 kebab-case 名（VC-7）；未知名字回退 `CbrIcons.fallback` 并可由调用方记 trace。
- 动作统一走 `UserActionEvent`（`cbrDispatch`），由上层 `ActionDispatcher` 做白名单与风险分级（docs/04 §6），组件不直接执行。

## 4. 新增组件

1. 先在 `docs/06 §9.2` 登记组件名与可传参数（真源先行）。
2. 在 `cbr_maw_design_system` 里实现对应 `Cbr*` widget（若已有则复用）。
3. 在 `lib/src/components_domain.dart`（领域）或 `components_basic.dart`（通用）加 `CatalogItem`：
   - `name` 用 UpperCamelCase；
   - `dataSchema` 只声明语义字段，含 `state`；
   - `widgetBuilder` 经 `cbrStateful(ctx, …)` 包一层。
4. 在 `catalog_registry.dart` 的 `cbrCatalogItems` 与 `cbrComponentKebabIds` 各加一行。
5. 在 `test/catalog_test.dart` 与 `test/render_test.dart` 补断言（登记、拒绝、状态、a11y）。

## 5. 验证

```bash
cd /mnt/shared/recently/CBR
dart analyze packages/a2ui_catalog
flutter test packages/a2ui_catalog
```
