# 部署指南（本地 / 服务器）

> 目标：把 CBR-MAW 以「FastAPI + React `/ui/`（可选）+ Streamlit 回退」的方式稳定跑起来。
> 当前仓库未提供 Dockerfile / systemd unit；本文给出可直接执行的命令与反向代理配置参考（标注为参考示例，未在 CI 中验证）。
> 端口、环境变量与进程关系以 [`configs/app.yaml`](../../configs/app.yaml)、[`src/cbr/api/main.py`](../../src/cbr/api/main.py) 为准。

---

## 1. 进程与端口

| 进程 | 默认地址 | 用途 | 启动前提 |
|---|---|---|---|
| FastAPI（uvicorn） | `127.0.0.1:8000` | `/api/*`、`/docs`；有 `web/dist` 时托管 `/ui/` | Python 环境 + 依赖 |
| Vite dev（可选） | `127.0.0.1:5173` | 前端开发热更新，`/api` 代理到 8000 | `bun install` |
| Vite preview（可选） | `127.0.0.1:4173` | 构建产物预览（路径 `/ui/`） | `bun run build` |
| Streamlit（可选回退） | `127.0.0.1:8501` | Streamlit 驾驶台/对话 | Python 环境 |

关系：React 前端是纯静态产物，由 FastAPI 静态挂载；**不存在独立前端服务进程**（生产部署只需 uvicorn）。

---

## 2. 本地开发

```powershell
# 终端 A：后端（改代码自动重载；生产不要加 --reload）
.venv\Scripts\python.exe -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000 --reload

# 终端 B：前端热更新
cd web
bun run dev        # http://127.0.0.1:5173，/api 代理到 8000
```

如需让局域网访问，把 `--host` 改为 `0.0.0.0`（注意：默认无鉴权，仅限可信网络；见 §7）。

---

## 3. 单机部署（推荐路径）

```powershell
# 1) 安装与数据（同 quickstart）
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -e . --no-deps
.venv\Scripts\python.exe scripts\build_sample_data.py
.venv\Scripts\python.exe scripts\build_knowledge.py

# 2) 构建前端（产出 web/dist）
cd web
bun install
bun run build
cd ..

# 3) 启动（生产模式，无 --reload）
.venv\Scripts\python.exe -m uvicorn cbr.api.main:app --host 0.0.0.0 --port 8000
```

Linux：

```bash
source .venv/bin/activate
python -m uvicorn cbr.api.main:app --host 0.0.0.0 --port 8000
```

验证：`GET /api/health` 返回 200 且核心模块就绪；`GET /ui/` 返回 `index.html`；`GET /` 307 跳转 `/ui/`。

---

## 4. 配置与环境变量

优先级：进程环境变量 > `.env`（`python-dotenv` 加载，不覆盖已有变量）> `secrets/deepseek.key` > `configs/app.yaml` 默认值。

| 变量 | 默认 | 作用 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | DeepSeek 密钥；空则 Mock LLM（全流程离线可跑） |
| `CBR_CONFIG` | `configs/app.yaml` | 指定应用配置（如指向真实数据配置） |
| `CBR_WEB_DIST` | `web/dist` | React 构建产物目录 |
| `CBR_DECISION_CACHE_TTL` | `1800` 秒 | 决策缓存 TTL（缓存键 `(as_of, mode, scenario)`） |
| `CBR_STREAM_TIMEOUT` | `300` 秒 | SSE 连接超时 |
| `CBR_STREAM_POLL_INTERVAL` | `0.1` 秒 | 流式 tail 轮询间隔 |
| `CBR_STREAM_TRACE_RETENTION` | `50` | `artifacts/traces/stream-*` 保留数量 |
| `CBR_TOOLS_CONFIG` | `configs/tools.yaml` | 工具/知识库配置路径 |

`.env` 示例（复制 [`.env.example`](../../.env.example)）：

```ini
DEEPSEEK_API_KEY=sk-...
# CBR_CONFIG=configs/app.yaml
```

> 前端**不保存任何 key**；密钥只在后端进程内使用。不要把 `.env`、`secrets/` 提交入库。

---

## 5. 反向代理（Nginx 参考示例，未在 CI 验证）

SSE 需要关闭代理缓冲，否则前端会看到「一次性返回」而不是真实流式（前端仍会自动回退同步端点，功能不坏但体验降级）：

```nginx
location / {
    proxy_pass         http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header   Host $host;
    proxy_set_header   X-Real-IP $remote_addr;
    proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;

    # SSE：关闭缓冲、放宽读超时、禁用 gzip
    proxy_buffering    off;
    proxy_cache        off;
    proxy_read_timeout 360s;
    gzip               off;
}

location /api/decision/stream { proxy_pass http://127.0.0.1:8000; proxy_buffering off; proxy_read_timeout 360s; }
location /api/chat/stream     { proxy_pass http://127.0.0.1:8000; proxy_buffering off; proxy_read_timeout 360s; }
```

若代理无法放行 SSE：前端会在运行面板标注「同步回退」并调用 `/api/decision`、`/api/chat`，功能不受影响。

---

## 6. Linux systemd 参考单元

```ini
# /etc/systemd/system/cbr-maw.service（参考示例，按实际路径/用户修改）
[Unit]
Description=CBR-MAW API
After=network.target

[Service]
Type=simple
User=cbr
WorkingDirectory=/opt/cbr-maw
Environment="CBR_CONFIG=configs/app.yaml"
EnvironmentFile=-/opt/cbr-maw/.env
ExecStart=/opt/cbr-maw/.venv/bin/python -m uvicorn cbr.api.main:app --host 127.0.0.1 --port 8000
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now cbr-maw
sudo journalctl -u cbr-maw -f
```

Streamlit 回退 UI 如需常驻，单独起一个 service（`... -m streamlit run app/dashboard.py --server.port 8501 --server.address 127.0.0.1`）。

---

## 7. 安全与资源注意

- **默认无鉴权**：`uvicorn` 本身不提供用户认证。对外暴露前应放在带认证的反向代理 / 内网之后，或仅绑定 `127.0.0.1`。
- **密钥**：只从环境变量或 `secrets/deepseek.key` 读取；确认 `.gitignore` 生效（`.env`、`secrets/`）。
- **流式并发**：目前每个 SSE 请求独立创建编排器 + daemon 线程，**无并发上限**（已知限制 LIM-11）；高并发场景应加队列/限流或关闭流式改用同步端点。
- **磁盘**：`artifacts/traces/`、`artifacts/runs/` 会持续增长；按需清理并调整 `CBR_STREAM_TRACE_RETENTION`。这些目录不入库。
- **缓存**：决策缓存 30 分钟；演示时想强制重算用 `?refresh=true`。
- **健康检查**：`GET /api/health` 永远 200；核心模块未就绪时业务端点返回 503 + 中文说明，适合作为探针（看响应体字段而非仅状态码）。

---

## 8. 部署检查清单

- [ ] `python -m pytest -q` 通过（基线 249 项，2026-10-18 记录）
- [ ] `web/dist` 存在（否则 `/ui/` 404，API/Streamlit 仍可用）
- [ ] `/api/health` 中核心模块就绪、LLM 模式符合预期（mock/真实）
- [ ] 数据源符合预期：`data/samples`（SYNTHETIC）或 `data/custom`（真实，且 `synthetic_fallback: false`）
- [ ] 反向代理关闭 SSE 缓冲 / 超时 ≥ 300s（如使用流式）
- [ ] 密钥未入库、日志未打印密钥
- [ ] 对外暴露前已加认证或限制来源
