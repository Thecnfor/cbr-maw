# 长时测试（soak）：实时抓取稳定性与资源趋势

> 目标：验证「实时智能抓取」能长时间稳定运行——反复抓取下**成功率不下降、耗时可控、
> 内存不无界增长、陈旧序列不失控**。配套脚本 [scripts/soak_test.py](../../scripts/soak_test.py)，
> 结果落盘到 `artifacts/soak/`。
>
> 前置知识见 [实时智能抓取指南](realtime-ingestion.md)；数据口径见
> [data/real_data_integration.md](../data/real_data_integration.md)。

---

## 1. 一句话说明

soak 测试把实时抓取当作长跑组件：以**可配置的总时长 + 运行间隔**反复触发
`IngestAgent.run`（或后台调度器 `IngestScheduler.run_once` 路径），逐次采集：

- 单次**耗时长**（`wall_ms`）与各来源耗时（`latency_ms`）；
- **成功率**（`ok` / `n_errors`）与异常文本；
- **写入量**：观测数 `n_observations`、文档数 `n_documents`、写入序列数；
- **来源状态分布**：`ok` / `empty` / `error` / `skipped`；
- **陈旧序列数**（`stale_series`）与可抓取序列数（`fetchable_series`）；
- **进程 RSS**（运行前后），观察内存是否随时间漂移。

每次运行实时追加到 JSONL（防中断丢数据），结束时另写一份 `*.summary.json` 汇总。

---

## 2. 快速使用

```bash
# 真实来源：直连，先清代理（代理会劫持/拦截公开行情站点）
env -u http_proxy -u https_proxy -u all_proxy \
  .venv/bin/python scripts/soak_test.py --duration 1800 --interval 60

# 短冒烟（3 次、固定序列、强制刷新、不写库）
env -u http_proxy -u https_proxy -u all_proxy \
  .venv/bin/python scripts/soak_test.py --duration 300 --interval 30 \
    --series market.cn_equity.csi300 --mode forced --no-write --max-runs 3

# 走后台调度器路径（覆盖 IngestScheduler.run_once 与写前/写后钩子）
env -u http_proxy -u https_proxy -u all_proxy \
  .venv/bin/python scripts/soak_test.py --duration 600 --interval 120 --via-scheduler
```

> Windows PowerShell 清代理：`$env:http_proxy=$null; $env:https_proxy=$null; $env:all_proxy=$null`

### 2.1 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `--duration` | `1800` | 总时长（秒）；到点后不再发起新运行 |
| `--interval` | `300` | 两次抓取之间的间隔（秒） |
| `--max-runs` | `0` | 最多运行次数（`0` 表示不限制，仅按 `--duration`） |
| `--mode` | `gap` | `gap`（按缺口）/ `full`（全部来源）/ `forced`（忽略陈旧阈值） |
| `--as-of` | 今天 | 基准日 `YYYY-MM-DD` |
| `--series` | 全部 | 仅抓取这些序列（逗号分隔），如 `market.cn_equity.csi300` |
| `--no-write` | 关 | 只抓取不写回 PIT（干跑） |
| `--via-scheduler` | 关 | 走 `IngestScheduler.run_once` 路径 |
| `--output-dir` | `artifacts/soak` | 结果目录 |
| `--label` | 时间戳 | 本次运行标签（决定输出文件名） |
| `--min-success-rate` | `0.0` | 低于该成功率以非零码退出（`0` 表示不设门禁） |

---

## 3. 结果怎么看

运行结束后打印汇总；同时落盘：

```text
artifacts/soak/soak-<label>.jsonl          # 每次运行一行（实时追加）
artifacts/soak/soak-<label>.summary.json   # 汇总（成功/耗时分布/RSS/按来源聚合）
```

汇总关键字段：

- `success_rate`：`n_ok / n_runs`，其中**一次运行成功 = 完整跑完并产出报告（未抛异常）**。
  个别来源被限流/不可达（`error`/`empty`）由多源回退兜底，**不**判定整次运行失败——请结合
  `sources` 聚合与 `total_errors` 单独观察单源健康度。
- `latency_ms`：`min/mean/p50/p95/max`。重点看**趋势**——若 p95 随运行次数持续抬升，
  说明存在累积开销（连接/句柄/缓存）。
- `rss_mb.start/end/peak/delta`：`delta` 显著为正且持续增长 = 内存泄漏信号；
  稳态下应小幅波动。
- `stale_series_start/end`：陈旧序列数应随抓取推进**不上升**（有备源覆盖的会下降）。
- `sources`：按来源聚合 `ok/empty/error/skipped` 与平均耗时，用于定位单源退化。

推荐时长：**冒烟** 5–10 分钟；**回归** ≥ 30 分钟（默认）；**稳定性观察** ≥ 2 小时
（配合 `--interval 300` 或更长，贴近生产抓取节奏）。

---

## 4. 启用后台定时抓取（生产路径）

soak 默认用即时 `run()` 循环，便于可控压测；生产形态是**后台调度器**：

1. `configs/app.yaml` 中 `ingest.enabled: true`（并按需 `run_on_start: true`、`interval_seconds`）；
2. 启动 API 即随 lifespan 启停：`python -m uvicorn cbr.api.main:app --port 8000`；
3. 状态与手动触发：`GET /api/ingest/status`、`POST /api/ingest/refresh`。
4. 决策即时消费实时数据：将 `data.dataset` 设为 `pit`（写回后 `provider.reload()` 热刷新）。

长时观察建议同时采集 API 侧：`/api/ingest/status` 的 `stale_series`、`last_report`，
与 `artifacts/ingest/latest.json` 对照。

---

## 5. 边界与已知限制

- **代理**：真实公开来源需直连；环境里若设了 `http(s)_proxy`/`all_proxy` 请清除后再跑。
- 部分公开来源可能被限流/不可达（如本环境 `push2his.eastmoney.com`），依赖多源回退；
  无备源的序列会保持陈旧（见 `/api/ingest/status`），属**预期**而非脚本故障。
- `akshare`、向量库/基础设施驱动为**可选依赖**，未安装时相关来源记为 `skipped`。
- soak 只做**观测与统计**，不自动判定「通过/失败」；阈值门禁请用 `--min-success-rate`
  或另建 CI 判据。

---

## 6. 相关

- 抓取机制与来源配置：[realtime-ingestion.md](realtime-ingestion.md)
- 可选基础设施（redis/mongo/pgvector/qdrant）：[docker-compose.yml](../../docker-compose.yml) · [ADR](../architecture/adr-2026-10-27-infra-and-rag.md)
- 发布验证清单：[releases/v2.0.0.md](../releases/v2.0.0.md)
