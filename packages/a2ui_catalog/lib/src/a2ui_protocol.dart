/// A2UI 协议消息类型（`a2ui_core` 的最小透出）。
///
/// `genui` 只重导出渲染 widget 与 `SurfaceController`，不重导出 `a2ui_core`
/// 的消息类型；而 `apps/desktop/lib/genui/adapter/`（唯一允许依赖 `genui`
/// 的层）需要构造/接收协议消息。这里统一透出，避免桌面端直接依赖一个
/// 传递依赖（`depend_on_referenced_packages`）。
library;

export 'package:a2ui_core/a2ui_core.dart'
    show
        A2uiMessage,
        A2uiValidationError,
        CreateSurfaceMessage,
        DeleteSurfaceMessage,
        UpdateComponentsMessage,
        UpdateDataModelMessage;
