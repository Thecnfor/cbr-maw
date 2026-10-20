# 故障排查（FAQ）

> 按「现象 → 原因 → 处理」组织。每条命令都可在仓库根目录直接执行（Windows PowerShell；Linux 把 `.venv\Scripts\python.exe` 换成 `.venv/bin/python`）。
> 先做一次基础自检：

```powershell
.venv\Scripts\python.exe -m pytest -q            # 环境与核心逻辑
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5   # 服务状态
```

---

## 1. LLM 相关

### Q1：为什么系统一直在用 Mock，不调用 DeepSeek？

**原因**：没有找到 key，或 key 名不对。系统按 `DEEPSEEK_API_KEY` 环境变量 → `.env` → `secrets/deepseek.key` 顺序查找；`configs/app.yaml` 的 `llm.mock: true` 表示「允许无 key 时 Mock」，有 key 会自动切真实模型。

**处理**：

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."      # 当前终端有效
Set-Content secrets\deepseek.key "sk-..."   # 或写入忽略文件
# 重启 uvicorn 后检查：
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5
```

看 `llm.mode` / `llm.model` 字段是否为真实模型。

### Q2：真实调用报 401 / 超时 / 重试？

- key 无效或余额不足：先用 `llm` 配置中的 `base_url`（默认 `https://api.deepseek.com`）单独验证；
- 网络或代理问题：`timeout_seconds`（默认 60）与 `max_retries`（默认 2）在 `configs/app.yaml` 可调；
- 偶发失败后系统会回退后端错误信息，前端展示中文 `detail`，不会白屏。

### Q3：Mock 下为什么没看到"真实"文本差异？

Mock LLM 是确定性规则模式：数值全部抄自工具证据，文本按模板生成。这是设计行为，用于离线复现与测试，不代表真实 LLM 表现（见 [pilot_results_real_llm.md](../techdoc/pilot_results_real_llm.md)）。

---

## 2. 服务与 API

### Q4：业务端点返回 503？

**原因**：核心模块（data/knowledge/tools/llm/orchestration）未装配成功，或装配过程报错。

**处理**：

1. 看 `/api/health` 响应体的 `core_ready` / `pending_modules` / `error` 字段；
2. 看 uvicorn 终端日志中的异常栈；
3. 常见根因：数据目录为空（跑 `scripts\build_sample_data.py`）、知识库索引缺失（跑 `scripts\build_knowledge.py`）、配置 YAML 语法错误。

### Q5：`ModuleNotFoundError: No module named 'cbr'`

**原因**：没做可编辑安装，或不在仓库根目录执行。

```powershell
.venv\Scripts\python.exe -m pip install -e . --no-deps
# 或临时（Windows PowerShell）：
$env:PYTHONPATH = "src"
```

并确认当前目录是仓库根（`pytest.ini` 的 `pythonpath = ["src"]` 只对 pytest 生效）。

### Q6：端口 8000 被占用？

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess
Get-Process -Id (Get-NetTCPConnection -LocalPort 8000 -State Listen).OwningProcess
Stop-Process -Id <PID> -Force        # 确认是自己启动的进程再执行
```

或换端口：`--port 8010`；前端开发模式下需同步改 `web/vite.config.ts` 的代理 `target`。

### Q7：`uvicorn` 命令找不到？

用模块方式启动，不依赖 PATH：

```powershell
.venv\Scripts\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000
```

---

## 3. 数据相关

### Q8：启动后没有数据 / 决策卡报"数据缺失"

```powershell
.venv\Scripts\python.exe scripts\build_sample_data.py
.venv\Scripts\python.exe scripts\build_knowledge.py
```

- `data/samples/` 是 SYNTHETIC 样例（已入库，通常不需要重建）；
- `data/pit.duckdb` 是运行时产物（忽略）；没有它时数据层会回退 `data/samples`，功能可用但首次请求偏慢；
- 想更快：`.venv\Scripts\python.exe scripts\build_dataset.py`。

### Q9：怎么确认当前用的是仿真还是真实数据？

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/data-cards | ConvertTo-Json -Depth 3
```

看每个序列的 `source`、`pit_grade`、`notes`；出现「SYNTHETIC 仿真数据回退」说明混入了仿真值。真实数据接入见 [real-data.md](real-data.md)。

### Q10：`as_of` 日期没有结果？

`as_of` 必须在数据覆盖期内且早于最新发布时点；情景日期可取 `configs/scenarios.yaml` 的 `as_of`（如 `2024-08-05`）。越界通常返回 503/422 与中文说明。

---

## 4. 前端与构建

### Q11：`/ui/` 404、只有 API 能用？

**原因**：`web/dist` 不存在（未构建或构建失败）。FastAPI 只在 dist 存在时挂载 `/ui/`。

```powershell
cd web
bun install
bun run build
cd ..
```

重启 uvicorn 后访问 <http://127.0.0.1:8000/ui/>。只跑 API/Streamlit 时忽略此项。

### Q12：没有 bun / bun 版本过低？

要求 Bun ≥ 1.2（验证于 1.3.13）。没有 bun 时无法构建 React 前端，但 **Streamlit 回退 UI 仍可用**：

```powershell
.venv\Scripts\python.exe -m streamlit run app\dashboard.py --server.port 8501
```

### Q13：`bun run build` 报 TypeScript 错误？

- `tsc --noEmit` 是构建的一部分（`bun run build` = `tsc --noEmit && vite build`）；
- 先单独跑 `bunx tsc --noEmit` 定位文件与行号；
- 依赖损坏时删除 `web/node_modules` 与 `bun.lock` 后重新 `bun install`；
- 构建 `base` 固定 `/ui/`，不要改成 `/`。

### Q14：开发模式前端调不到后端（/api 404 / CORS）？

Vite 把 `/api` 代理到 `127.0.0.1:8000`，前提是后端已启动；端口被 `strictPort` 锁定时不会自动换端口，先释放 5173/4173。生产 `/ui/` 与 API 同源，不存在 CORS。

---

## 5. SSE 流式

### Q15：运行面板显示「同步回退」？

**原因**：`/api/decision/stream` / `/api/chat/stream` 不可达（旧后端 404、代理缓冲/拦截、网络错误）。前端会自动回退同步端点，功能正常，只是没有实时阶段与 trace。

**处理**：

1. 确认后端包含 `src/cbr/api/streaming.py`（v1.0+）；
2. 反向代理关闭缓冲并放宽超时（见 [deployment.md §5](deployment.md#5-反向代理nginx-参考示例未在-ci-验证)）；
3. 验收脚本：

```powershell
.venv\Scripts\python.exe scripts\verify_stream.py --base http://127.0.0.1:8000
```

### Q16：流式请求 300 秒超时 / 断流？

- `CBR_STREAM_TIMEOUT`（默认 300s）保护 SSE 连接；真实 LLM 单次 12–18s，正常不会触发；
- 超时只关闭连接、不取消后台 worker（LIM-11）；高并发/慢模型时应加限流。

---

## 6. 测试与脚本

### Q17：`pytest` 大量报错？

按顺序排查：

1. 是否在仓库根目录执行、是否 `pip install -e . --no-deps`；
2. 是否缺样例数据（`scripts\build_sample_data.py`、`scripts\build_knowledge.py`）；
3. `.pytest_cache`/`__pycache__` 损坏：删除后重跑；
4. 只跑单文件定位：`.venv\Scripts\python.exe -m pytest tests\test_data.py -q`；
5. 部分测试需要真实 DeepSeek key；未设 key 时应自动走 Mock（若失败会明确跳过或失败信息含 key 相关提示）。

### Q18：`scripts/` 下脚本 import 失败？

脚本需要在**仓库根目录**执行（脚本内部把 `src/` 加入 `sys.path`，但相对路径参数如 `configs/...` 按当前目录解析）：

```powershell
cd D:\recently\commorcial
.venv\Scripts\python.exe scripts\run_experiment.py --kind p1 --p1-max-days 60
```

### Q19：Windows 终端中文乱码？

用 Windows Terminal / PowerShell 7，必要时 `chcp 65001`；文件读写统一 UTF-8。

### Q20：`render_mermaid.py` 失败？

该脚本通过 mermaid.ink 在线渲染，需要联网；离线时第四章 DOCX 中的图会退化为代码块占位，不影响正文。

---

## 7. 还解决不了？

1. 收集：命令、完整报错栈、`/api/health` 响应、`git rev-parse --short HEAD`；
2. 按 [SECURITY.md](../../SECURITY.md) 的说明报告敏感问题（不要公开贴 key）；
3. 其它问题走 Issue（附复现步骤与期望行为），见 [CONTRIBUTING.md](../../CONTRIBUTING.md)。
