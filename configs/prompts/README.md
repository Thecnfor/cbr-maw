# configs/prompts — 角色 Prompt 模板

本目录存放 CBR-MAW 角色智能体的 prompt 模板，由 `src/cbr/agents/prompts.py`
在运行时加载并与 `configs/roles.yaml` 的 `RoleSpec` 渲染合并（`{{placeholder}}`）。

| 文件 | 用途 | 主要占位符 |
|------|------|------------|
| `common_rules.md` | 三角色共享的证据规则 / JSON 输出 schema / 反幻觉约束 | 无 |
| `regulator.md` | 监管主体 system prompt | objective / focus / info_permissions / tool_permissions / thresholds / decision_loss_weights / forbidden_actions / output_style |
| `investor.md` | 投资主体 system prompt | 同上 |
| `financing.md` | 融资主体 system prompt | 同上 |
| `cross_validation.md` | R2 交叉验证轮 system prompt（复核 peer 证据） | display_name / tool_permissions / forbidden_actions |
| `single_agent.md` | 单智能体基线（P3 对照）system prompt | regulator_objective / investor_objective / financing_objective |

## 约定

- 修改本目录文件即可调整 prompt，无需改代码；`src/cbr/agents/prompts.py`
  会优先读取本目录，文件缺失时回退到内置最小模板；
- 模板中 `{{name}}` 形式的占位符由 `RoleSpec` 字段渲染；未知占位符保持原样，
  便于发现配置问题；
- prompt 只负责"解释与建议"，数值一律由确定性工具产生并由 RoleAgent 回填，
  因此 prompt 中出现的阈值仅用于解释，不得被模型用于生成未经证据支持的数字；
- 修改 prompt 后请运行 `pytest tests/test_agents.py`（含 prompt 差异性与占位符检查）。
