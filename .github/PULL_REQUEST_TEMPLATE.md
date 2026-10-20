# CBR-MAW · Pull Request 模板
#
# 填写要点：一次 PR 只做一件事；验证命令与结果必须可复现；不要夹带无关文件。

## 变更类型

<!-- 勾选一个或多个 -->
- [ ] `feat` 新功能
- [ ] `fix` 缺陷修复
- [ ] `docs` 文档
- [ ] `test` 测试
- [ ] `chore` 构建/依赖/工程化
- [ ] `refactor` 重构（不改变行为）

## 关联任务 / Issue

<!-- 例：task-3 / #12；无则写“无” -->

## 变更说明

<!-- 为什么改、改了什么、有什么取舍。涉及 API/schema/配置/数据口径变更时必须写明兼容性影响。 -->

## 验证记录

<!-- 粘贴实际执行的命令与关键输出（不要只写“已测试”） -->

```powershell
.venv\Scripts\python.exe -m pytest -q
# 结果：

cd web; bun run build; cd ..
# 结果：

.venv\Scripts\python.exe scripts\repo\check_repo.py
# 结果：
```

## 检查清单

- [ ] 只改动了本任务写入范围内的文件（未越界修改他人负责的文件）
- [ ] 行为变更附带测试；全量 pytest 通过（或明确列出环境性例外）
- [ ] 前端改动已 `bun run build`，`web/dist` 与源码一致（如适用）
- [ ] 文档/CHANGELOG 已同步（用户可见变更）
- [ ] 未提交密钥、`.env`、原始数据（`data/custom/`、`data/raw/`）、`artifacts/`、大文件
- [ ] 新增/修改的 Markdown 相对链接可解析
- [ ] 截图/录屏（UI 变更）：<!-- 路径或“不适用” -->

## 风险与回滚

<!-- 可能影响的范围、回滚方式；无则写“无” -->
