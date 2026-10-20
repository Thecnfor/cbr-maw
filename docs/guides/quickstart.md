# 快速开始（从零跑起来）

> 目标：在一台干净机器上，用 15–30 分钟跑通「样例数据 → 测试 → API → React 驾驶台 / Streamlit 回退」。
> 适用于 Windows 10/11 与 Linux/macOS；本文命令可直接复制执行（Windows 用 PowerShell）。
> 需要更细的背景见 [README](../../README.md)；遇到报错先看 [troubleshooting](troubleshooting.md)。

---

## 1. 前置条件

| 依赖 | 版本要求 | 验证命令 | 说明 |
|---|---|---|---|
| Python | ≥ 3.11（验证于 3.12） | `python --version`（Linux 用 `python3 --version`） | 必须带 venv 模块 |
| pip | 随 Python 安装 | `python -m pip --version` | — |
| Bun | ≥ 1.2（验证于 1.3.13） | `bun --version` | 仅构建 React 驾驶台需要；不装则用 Streamlit 回退 |
| 磁盘 | ≥ 2 GB 空闲 | — | 依赖约数百 MB，`artifacts/` 会增长 |

> 前端构建只在与后端同机部署 `/ui/` 时需要。只做 API/算法开发可跳过第 4 步。
> 不需要提前准备数据：仓库自带 `data/samples/` 的 SYNTHETIC 仿真数据。

---

## 2. 安装（Windows / PowerShell）

在仓库根目录执行：

```powershell
# 1) 虚拟环境
python -m venv .venv

# 2) 安装依赖（-e . 让 `python -m uvicorn cbr.api.main:app` 能直接 import cbr）
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e . --no-deps

# 3) 构建 SYNTHETIC 样例数据与知识库索引（幂等，可重复执行）
.venv\Scripts\python.exe scripts\build_sample_data.py
.venv\Scripts\python.exe scripts\build_knowledge.py
```

## 2'. 安装（Linux / macOS）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e . --no-deps

python scripts/build_sample_data.py
python scripts/build_knowledge.py
```

预期产物：

- `data/samples/`：`market_daily.*`、`macro_monthly.*`、`documents.*`、`data_cards.json`、`series_catalog.json`、`MANIFEST.json`（含 SYNTHETIC 声明）；
- `data/knowledge/index/`：`documents.jsonl`、`chunks.jsonl`、`bm25.json`、`manifest.json`。

> 想快速验证 PIT 构建而不重训模型时，用 `python scripts/build_dataset.py --skip-signal`（见 §7）。

---

## 3. 跑测试（确认环境正确）

```powershell
.venv\Scripts\python.exe -m pytest -q
```

- 当前记录的基线为 **249 项通过**（2026-10-18）；你的 checkout 若有新增测试，以实际输出为准。
- 测试覆盖数据 / 模型 / 工具 / 知识库 / 智能体 / 编排 / 核验 / API / SSE 流式 / 端到端集成。
- 若只关心某块：`-m pytest tests\test_api.py -q`、`tests\test_orchestration.py` 等。

---

## 4. 构建并启动 React 驾驶台（可选但推荐）

```powershell
cd web
bun install
bun run build      # tsc --noEmit && vite build -> web/dist
cd ..
```

启动服务（仓库根目录）：

```powershell
.venv\Scripts\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000
```

访问：

| 入口 | 地址 | 说明 |
|---|---|---|
| React 驾驶台 | <http://127.0.0.1:8000/ui/> | 主界面；`?theme=dark` 深色，`?cmd=1` 打开命令面板 |
| API 文档 | <http://127.0.0.1:8000/docs> | OpenAPI |
| 健康检查 | <http://127.0.0.1:8000/api/health> | 永远 200；看核心模块与 LLM 模式 |

`web/dist` 不存在时 `/ui/` 不可用，但 API 与 Streamlit 仍可运行。

Linux/macOS 启动命令相同（激活 venv 后用 `python -m uvicorn ...`）。

---

## 5. 最小验收（3 条命令）

```powershell
# 健康检查：core_ready / llm 模式 / 数据源
Invoke-RestMethod http://127.0.0.1:8000/api/health | ConvertTo-Json -Depth 5

# 生成一次协同决策卡（Mock LLM，几秒内返回）
Invoke-RestMethod "http://127.0.0.1:8000/api/decision?as_of=2024-08-05&mode=collaborative" |
  Select-Object run_id, final_advice

# 流式接口（SSE）：应依次看到 run / stage / trace / decision 事件
.venv\Scripts\python.exe scripts\verify_stream.py --base http://127.0.0.1:8000
```

Linux/macOS：

```bash
curl -s http://127.0.0.1:8000/api/health
curl -s "http://127.0.0.1:8000/api/decision?as_of=2024-08-05&mode=collaborative" | head -c 500
python scripts/verify_stream.py --base http://127.0.0.1:8000
```

---

## 6. 不构建前端：Streamlit 回退 UI

```powershell
.venv\Scripts\python.exe -m streamlit run app\dashboard.py --server.port 8501
```

访问 <http://127.0.0.1:8501>。Streamlit 保留原信息架构（6 页签 + 对话页），与 React 驾驶台共用同一套 API 与服务装配。

---

## 7. 可选：构建 PIT 库与逐日信号（更快、更接近正式运行）

`scripts/build_dataset.py` 会生成 `data/pit.duckdb`（时点库）与 `artifacts/models/`（模型与逐日信号快照），API 首次请求更快，也支持 `--with-custom` 并入真实数据：

```powershell
.venv\Scripts\python.exe scripts\build_dataset.py
.venv\Scripts\python.exe scripts\build_dataset.py --with-custom   # 已放入 data/custom 时
```

该步骤耗时与机器相关（滚动快照训练，通常数分钟）。不做也不影响演示：数据层会自动回退到 `data/samples/`。

---

## 8. 接入真实数据 / 真实 LLM（后续）

- 真实数据：见 [真实数据接入指南](real-data.md)（`data/custom/` + `configs/data_mapping.yaml` + `data.dataset: custom`）。
- 真实 LLM：

  ```powershell
  $env:DEEPSEEK_API_KEY = "sk-..."     # 或写入 secrets/deepseek.key（已 gitignore）
  ```

  重启服务后 `/api/health` 的 `llm` 会显示真实模型；无 key 时自动 Mock，流程不变。

- 部署到服务器：见 [部署指南](deployment.md)。
- 跑实验：见 [实验指南](experiments.md)。

---

## 9. 接下来读什么

1. [README 架构概览](../../README.md#2-架构概览) —— 六层在做什么；
2. [架构设计 v1](../architecture/CBR-MAW_architecture_v1.md) —— 模块与实现映射；
3. [团队协作指南](team-collaboration.md) —— 准备改代码前先看写入范围与验证命令；
4. [故障排查](troubleshooting.md) —— 端口、bun、503、SSE 回退等常见问题。
