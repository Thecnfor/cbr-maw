# SSE 流式接口实现备注（后端）

> 契约：[ai-native-interaction-spec.md](./ai-native-interaction-spec.md) §1；实现：[src/cbr/api/streaming.py](../../src/cbr/api/streaming.py)；测试：[tests/test_streaming.py](../../tests/test_streaming.py)。
> 同步端点 `/api/decision`、`/api/chat` 行为完全不变。

## 1. 端点与事件

| 端点 | 事件 | 最终业务事件 |
|---|---|---|
| `GET /api/decision/stream?as_of=&scenario=&mode=&refresh=` | `run` / `stage` / `trace` / `decision` / `error` + `: ping` | `decision` |
| `POST /api/chat/stream`（body `ChatRequest`） | `run` / `stage` / `trace` / `chat` / `error` + `: ping` | `chat` |

- `Content-Type: text/event-stream; charset=utf-8`，`Cache-Control: no-cache`，`X-Accel-Buffering: no`；
- `run`：发现本次 trace 文件后立即发送 `{"run_id": ...}`（文件名即 run_id）；
- `stage`：由 trace 事件按 spec §1.3 映射（`map_trace_to_stage`），字段 `stage/label/role/status/action/ts`；
- `trace`：完整 `TraceEvent`（等同 `/api/trace/{run_id}` 单条）；
- `error`：`{"status": 503|504, "message": 中文}`；SSE 内错误时 **HTTP 状态仍为 200**；
- 决策命中 30 分钟缓存（`refresh=false`）：只发一条 `decision`，不构建编排器；
- 心跳 `: ping` 每 10s；总超时默认 300s（`CBR_STREAM_TIMEOUT` 可覆盖），轮询间隔 `CBR_STREAM_POLL_INTERVAL`（默认 0.1s）。

## 2. 实现结构

1. `new_stream_trace_dir(service)` → `artifacts/traces/stream-<uuid12>/`（每次真实请求独立目录）；
2. `build_stream_orchestrator(service, trace_dir)` → `build_orchestrator(..., trace_dir=...)` 构建**独立编排器**
   （避免并发请求共享 `_last_board` / HITL 等可变状态；测试通过 monkeypatch 该函数注入 Fake）；
3. 后台 daemon 线程执行 `run` / `chat`；生成器以 0.1s 轮询 tail 该目录最新 `*.jsonl`，
   只解析**完整行**（半行/坏行跳过）；
4. 线程结束（`done` Event）后终态排空一次再发最终事件，避免最后一行竞态丢失；
5. 成功时与同步端点一致：`state.remember_decision` + 决策缓存写入（chat 不写决策缓存）。

`trace → stage` 的一致性保护：智能体内部 trace 也会复用 `finalize`（`step=R0:regulator`），
若按 action 直接映射会让进度条提前跳到 R5；因此当 `step` 带阶段根且与映射阶段不一致时不发
`stage`（只发 `trace`）。

## 3. 已知限制 / 风险

- **线程模型**：每个流式请求一个 daemon 线程 + 独立编排器。客户端断开后生成器停止 tail
  （pull 驱动），后台线程允许自然结束；进程退出时 daemon 线程被直接终止，未完成的 LLM
  调用可能被丢弃（不写半条 JSONL，坏行由 tail 容忍）。
- **独立编排器**：流式 run 使用新编排器，因此共享 `service.orchestrator` 的内存黑板
  （`_last_board`）与 HITL 队列不会包含这次运行；但决策卡 / 证据快照 / 轨迹已通过
  `state.remember_decision` 与 `DecisionCard.trace_ref` 兜底，`/api/evidence/{id}`、
  `/api/trace/{run_id}` 仍可查询（本条为实测路径）。
- **超时**：300s 只保护 SSE 连接；超时后后台线程仍可能继续跑完整次 `run`（仍会产生 artifacts）。
- **缓存**：仅进程内、仅 `decision/stream` 写入；多 worker（uvicorn `--workers>1`）下各进程
  缓存不共享，命中率下降但不影响正确性；`refresh=true` 跳过读取但仍会写入新结果。
- **trace 目录**：`artifacts/traces/stream-*` 不自动清理（保留完整审计），长期运行需外部
  定期归档/删除；每个真实请求一个目录。
- **降级**：服务未就绪 / 编排异常均以 SSE `error` 事件返回 200（前端按 `error` 展示中文
  说明）；参数校验失败仍是 HTTP 422。
- **并发真实 LLM**：多个流式请求会并发调用 LLM；演示时避免并发触发真实请求（成本/限流）。

## 4. 自测方式

```powershell
# 单元 + 端点（FakeService，无外部依赖）
$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m pytest tests/test_streaming.py -q

# 手动 HTTP 验收（示例：把 mock 服务跑在 8010，避免占用/干扰 8000）
$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe scripts\verify_stream.py --base http://127.0.0.1:8010 --refresh --limit 15
$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe scripts\verify_stream.py --base http://127.0.0.1:8010 --chat "当前跨境资金流出压力如何？"
```

本次验证结果（真实 `build_service()` 装配 + MockLLM，避免真实计费）：decision 流 1 个 `run`、
91 个 `trace`、35 个 `stage`、1 个 `decision`；chat 流 1 个 `run`、91 个 `trace`、35 个 `stage`、
1 个 `chat`；缓存命中仅 1 个 `decision`（约 0.01s）。
