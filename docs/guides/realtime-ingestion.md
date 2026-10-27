# 实时智能抓取（L1.5 数据接入层）

> 目标：把「每次手动找数据、跑批脚本」升级为「系统自己发现缺口、自动实时抓取、写回时点库、
> 热刷新决策链路」。本文说明**怎么用、怎么加源、怎么验、边界在哪**。
>
> 面向人的协作规则见 [team-collaboration.md](team-collaboration.md)；数据口径见
> [data/real_data_integration.md](../data/real_data_integration.md)。

---

## 1. 一句话架构

```
configs/sources.yaml ──► cbr.ingest（来源规格 + 抓取器）
                              │
        缺口/陈旧度分析(确定性) │  cbr.ingest.gaps
                              ▼
                    IngestAgent.plan()  →  IngestAgent.run()
                              │
        抓取(多来源回退) ──────┤─► PitStore.upsert_observations / upsert_documents（增量）
                              │            └─► 派生序列实时重算（cbr.ingest.derive）
                              ▼
                    provider.reload()（热刷新，决策立即用新数据）
```

- **计划器是确定性的**（基于覆盖期 + 陈旧阈值），可复现、可审计；不依赖 LLM。
- **抓取器按 `kind` 选择**：`http_csv` / `http_json` / `akshare` / `rss`。
- **同一序列可声明多个来源**（主源失败自动切备源，如东财限流时切腾讯）。
- **只增量写库**（`(series_id, obs_date)` 幂等覆盖），不重建 4 万行历史。
- 未配置来源的序列（如北向资金）在状态里标注 `fetchable=false`，不假装能抓。

---

## 2. 快速使用

### 2.1 命令行（脚本/CI）

```python
from cbr.ingest import build_ingest_agent

agent = build_ingest_agent()          # 读 configs/sources.yaml + settings.data.pit_db
plan = agent.plan()                   # 该抓什么（确定性）
report = agent.run(mode="gap")        # 抓 → 增量写库 → 重算派生 → 落盘 report
print(report.run_id, report.n_observations, report.written_series)
```

### 2.2 API

```bash
# 状态：调度器 / 来源健康 / 陈旧序列 / 最近报告
curl -s http://127.0.0.1:8000/api/ingest/status | jq
curl -s http://127.0.0.1:8000/api/ingest/freshness | jq '.[0:5]'
curl -s http://127.0.0.1:8000/api/ingest/plan | jq 'length'

# 按需抓取（可指定序列/模式；写回 PIT 并热刷新 provider）
curl -s -X POST http://127.0.0.1:8000/api/ingest/refresh \
  -H 'content-type: application/json' \
  -d '{"mode":"gap","series_ids":["market.global.vix"]}' | jq '.n_observations'
```

### 2.3 后台定时抓取

`configs/app.yaml`：

```yaml
ingest:
  enabled: true          # true 时随 API 启动后台调度线程
  run_on_start: false
  interval_seconds: 3600
```

---

## 3. 加一个新来源（3 步）

1. 在 `configs/sources.yaml` 追加一条（只需描述「从哪抓、怎么解析、时点假设」）：

   ```yaml
   - id: cboe_vix
     kind: http_csv
     series: [market.global.vix]
     params:
       url: "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
       date_column: DATE
       value_column: CLOSE
       date_format: "%m/%d/%Y"
       unit: "点"
       source: cboe
       release_lag_days: 1     # 美股收盘 → 北京次日可得
       publish_hour: 9
       tz_offset: "+08:00"
   ```

2. 若序列在此之前没有任何来源，`/api/ingest/plan` 会自动把它标为 `missing` 并纳入计划。

3. 跑一次 `agent.run(mode="forced")` 或 `POST /api/ingest/refresh` 验证落库。

**时点（PIT）约定**：`release_time = obs_date + release_lag_days` 的 `publish_hour:publish_minute`
（`tz_offset` 时区）。这是保证「不偷看未来」的关键，务必按真实发布时点设置（见
[data/real_data_integration.md §3](../data/real_data_integration.md)）。

**多来源回退**：为同一 `series` 再声明一条来源即可（声明顺序即优先级）。

---

## 4. 边界与注意事项

- **DuckDB 连接**：同一进程不能同时持有同一文件的读写连接与只读连接。`POST /api/ingest/refresh`
  会先让 provider `detach()`（释放只读连接），写完后 `reload()`；因此**不要**在外部长时间持有
  该 PIT 文件的写连接。
- **provider 模式**：实时数据要影响决策，provider 必须是 **PIT 支撑**的
  （`data.dataset: pit`，或 `auto/public` 且在 `data/custom` 为空时走 PIT）。`custom` 模式读取的是
  `data/custom/*.csv`，实时写回 PIT 不会进入该 provider；如需真实数据 + 实时，推荐
  `data.dataset: pit` + `data.pit_db: data/pit_real.duckdb`。
- **akshare 可选**：未安装时对应来源状态为 `skipped`，不影响其它来源。
- **公开接口不稳定**：已内置重试与多来源回退；单来源失败不会中断整轮抓取，会记入 `report.results`。
- **派生序列**：`term_spread` / `cgb_index` / `cnh_cny_gap` / `cn_us_spread` 由基础序列实时重算，
  不直接抓取，也不能在 `sources.yaml` 里声明为可抓取（加载时会报错）。

---

## 5. 验证与测试

```bash
# 单元/集成（离线，注入假抓取器，不访问网络）
.venv-linux/bin/python -m pytest tests/test_ingest.py -q

# 全量
.venv-linux/bin/python -m pytest -q
```

真实抓取冒烟（需联网）：

```bash
.venv-linux/bin/python - <<'PY'
from cbr.ingest import build_ingest_agent
agent = build_ingest_agent()
rep = agent.run(series_ids=("market.global.vix", "market.cn_equity.csi300"), mode="gap")
print(rep.n_observations, [r.source_id for r in rep.results if r.status in ("ok", "empty")])
PY
```

---

## 6. 相关文件

| 路径 | 作用 |
|---|---|
| `src/cbr/ingest/` | 抓取层（contracts / sources / gaps / derive / agent / scheduler / runtime） |
| `configs/sources.yaml` | 来源声明（改行为优先改这里） |
| `src/cbr/data/pit_store.py` | 增量写入 `upsert_observations` / `upsert_documents` / `touch_coverage` |
| `src/cbr/api/ingest.py` | `/api/ingest/*` 端点 |
| `src/cbr/infra/` | 可选基础设施（PG/Redis/Mongo/向量库）探测与降级 |
| `src/cbr/knowledge/vector.py` | RAG 向量检索（混合检索，默认离线可用） |
| `src/cbr/harness/` | 执行 harness（进程内 / 远程外部执行器） |
