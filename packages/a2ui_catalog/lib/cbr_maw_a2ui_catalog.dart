/// CBR-MAW 自有 A2UI 组件目录（安全边界）。
///
/// 真源：[docs/06-设计系统与美学规范.md §9]（VC-1~VC-8）与
/// [docs/04-动态UI与Agent-Native设计.md §5]。
///
/// - 组件集：[cbrCatalogItems] / [cbrRegisteredComponentNames]
/// - 构造 catalog：[buildCbrCatalog]（依赖 `genui`）
/// - 严格校验：[cbrValidateStrict]（未登记组件 → 拒绝并写 renderError）
/// - 版本：[cbrCatalogVersion]（独立于 A2UI 协议版本）
library;

export 'src/catalog_registry.dart';
export 'src/components_basic.dart';
export 'src/components_domain.dart';
export 'src/helpers.dart';
