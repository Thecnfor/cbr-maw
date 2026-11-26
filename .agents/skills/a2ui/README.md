# A2UI Claude Code Skill

这个 Skill 帮助 Claude Code 用户生成符合 A2UI 0.8 协议规范的前端 UI 代码。

## 快速开始

### 触发 Skill

在 Claude Code 中使用以下类型的请求会自动触发此 Skill：

```
"帮我生成一个 A2UI 登录表单"
"创建一个 A2UI 餐厅列表界面"
"生成 A2UI 预订确认对话框"
"使用 A2UI 协议创建用户资料卡片"
```

### 关键词

Skill 会在检测到以下关键词时激活：
- `A2UI`
- `UI 生成` / `UI generation`
- `组件` / `components`
- `界面` / `interface`
- `surfaceUpdate` / `dataModelUpdate` / `beginRendering`

## 使用示例

### 1. 生成简单表单

**请求：**
```
帮我用 A2UI 生成一个包含邮箱和密码的登录表单
```

**Claude 会生成：**
- 完整的 JSONL 消息流
- surfaceUpdate 定义组件结构
- dataModelUpdate 初始化表单数据
- beginRendering 触发渲染

### 2. 生成动态列表

**请求：**
```
用 A2UI 创建一个餐厅卡片列表，每个卡片显示名称、评分和图片
```

**Claude 会生成：**
- 使用 template 的动态列表
- Card 和 Row/Column 布局
- 数据绑定到 data model

### 3. 生成带操作的界面

**请求：**
```
生成一个 A2UI 预订表单，包含日期选择、人数滑块和确认按钮
```

**Claude 会生成：**
- DateTimeInput 日期选择器
- Slider 人数选择
- Button 带 action 和 context

## 目录结构

```
.claude/skills/a2ui/
├── SKILL.md                    # 核心指令
├── README.md                   # 本文件
├── reference/
│   ├── components.md           # 组件详细参考（含 weight 属性）
│   ├── data-binding.md         # 数据绑定指南
│   ├── api-integration.md      # API 集成说明（含传输层选项）
│   ├── schema.md               # JSON Schema 参考
│   ├── catalog-negotiation.md  # Catalog 协商机制
│   ├── surfaces.md             # 多 Surface 管理
│   ├── streaming.md            # 流式渲染优化
│   └── agent-prompting.md      # LLM Agent 开发指南
└── examples/
    ├── form.md                 # 表单示例
    ├── list.md                 # 列表示例
    ├── modal.md                # 模态框示例
    ├── booking-flow.md         # 完整业务流程示例
    ├── multi-surface.md        # 多 Surface 示例
    └── streaming.md            # 流式渲染示例
```

## 支持的组件

### 布局组件
| 组件 | 用途 |
|------|------|
| `Row` | 水平排列子组件 |
| `Column` | 垂直排列子组件 |
| `List` | 可滚动列表 |
| `Card` | 卡片容器 |
| `Tabs` | 标签页导航 |
| `Modal` | 模态对话框 |
| `Divider` | 分隔线 |

### 显示组件
| 组件 | 用途 |
|------|------|
| `Text` | 文本显示 |
| `Image` | 图片显示 |
| `Icon` | 图标显示 |
| `Video` | 视频播放 |
| `AudioPlayer` | 音频播放 |

### 输入组件
| 组件 | 用途 |
|------|------|
| `Button` | 按钮 |
| `TextField` | 文本输入 |
| `CheckBox` | 复选框 |
| `DateTimeInput` | 日期时间选择 |
| `MultipleChoice` | 多选/单选 |
| `Slider` | 滑块 |

## 核心概念

### 1. 消息类型

```jsonl
{"surfaceUpdate": {...}}      // 定义 UI 组件
{"dataModelUpdate": {...}}    // 设置数据模型
{"beginRendering": {...}}     // 触发渲染
{"deleteSurface": {...}}      // 删除界面
```

### 2. 数据绑定

```json
// 静态值
{"literalString": "Hello"}

// 动态绑定
{"path": "/user/name"}

// 带默认值的绑定
{"path": "/form/email", "literalString": "user@example.com"}
```

### 3. 用户操作

```json
{
  "action": {
    "name": "submit_form",
    "context": [
      {"key": "email", "value": {"path": "/form/email"}}
    ]
  }
}
```

## 高级主题

### Styles 配置

在 `beginRendering` 中自定义外观：

```json
{"beginRendering": {
  "surfaceId": "main",
  "root": "root",
  "styles": {
    "font": "Roboto",
    "primaryColor": "#1976D2"
  }
}}
```

### Flex 布局权重

使用 `weight` 属性控制子组件比例：

```json
{"id": "sidebar", "weight": 1, "component": {"Column": {...}}},
{"id": "content", "weight": 3, "component": {"Column": {...}}}
```

### 流式渲染

支持三种渐进式渲染策略：
1. **Skeleton First** - 先发送骨架，再填充数据
2. **Incremental Components** - 逐步添加组件
3. **Data Streaming** - 组件固定，只更新数据

详见 `reference/streaming.md` 和 `examples/streaming.md`。

### 多 Surface 架构

同时管理多个独立的 UI 区域：

```jsonl
{"beginRendering": {"surfaceId": "sidebar", "root": "nav"}}
{"beginRendering": {"surfaceId": "main", "root": "content"}}
{"beginRendering": {"surfaceId": "modal-add", "root": "form"}}
```

详见 `reference/surfaces.md` 和 `examples/multi-surface.md`。

### Agent 开发

使用 `---a2ui_JSON---` 分隔符集成 LLM Agent：

```
Here are some restaurants near you!

---a2ui_JSON---

[{"surfaceUpdate": {...}}, {"beginRendering": {...}}]
```

详见 `reference/agent-prompting.md`。

## 最佳实践

1. **使用唯一 ID**：每个组件需要唯一的 id
2. **扁平结构**：使用 ID 引用而非嵌套
3. **分离数据**：UI 结构和数据分开管理
4. **路径规范**：使用 JSON Pointer 格式（如 `/user/profile/name`）
5. **及时清理**：流程结束时使用 `deleteSurface` 清理
6. **渐进渲染**：尽早发送 `beginRendering`，数据可后续更新

## 常见问题

### Q: 如何处理空列表？

使用条件渲染或显示空状态组件。参见 `examples/list.md` 中的 "Empty State Handling" 部分。

### Q: 如何在模态框中收集表单数据？

在 Button 的 action.context 中使用 path 绑定表单字段。参见 `examples/modal.md` 中的 "Form Modal" 示例。

### Q: 如何实现分页？

在 data model 中跟踪页码状态，通过 action 传递分页信息。参见 `reference/api-integration.md` 中的 "Pagination" 部分。

## 相关资源

- [A2UI 协议规范](../../docs/specification/v0.8-a2ui.md)
- [快速开始指南](../../docs/quickstart.md)
- [组件库示例](../../samples/client/lit/)

## 反馈

如果遇到问题或有改进建议，请在项目仓库提交 Issue。
