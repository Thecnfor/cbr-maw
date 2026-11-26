# services/collector · CBR-MAW Go 采集 sidecar

负责契约里归属 Go 的全部方法：`sources.list` / `sources.probe` / `sources.health` /
`collect.run` / `inbox.ingest` / `events.poll`，以及 `initialize` / `shutdown` / `ping`。
另提供 `--selfupdate` 子命令（复用同一可执行体，不新增第 4 个 exe）。

- 传输：**stdin/stdout NDJSON，一行一个 JSON-RPC 2.0 消息**；stdout 只出协议消息。
- 日志：**stderr JSONL**（`{"ts","level","sidecar":"collector","msg",...}`）。
- **不写 DuckDB**：只产出规范化 NDJSON 中间文件 + 证据，落库交给 kernel 的 `pit.ingest`。
- 真源：`contracts/README.md`、`contracts/collector/*.schema.json`。

## 运行

```bash
cd services/collector
go build -o bin/collector ./cmd/collector
./bin/collector --workspace /path/to/ws --data-home /path/to/data --resource-home /path/to/res
```

未给 `--repo-root` 时会从可执行文件位置向上找含 `contracts/VERSION` 的目录。

## 配置：`configs/sources.json`

读取顺序（先命中先用）：

1. `<data_home>/configs/sources.json`（用户覆盖）
2. `<resource_home>/configs/sources.json`（安装包只读）
3. `<repo>/configs/sources.json`
4. `<repo>/services/collector/configs/sources.json`（本服务自带的迁移产物）
5. `<repo>/docs/legacy-configs/sources.yaml`（旧 YAML 兼容回退，会写一条 warning）

条目格式：

```jsonc
{
  "version": 1,
  "user_agent": "cbr-maw-collector/0.1.0 (+https://github.com/Thecnfor/cbr-maw)",
  "defaults": {
    "timeout_seconds": 20,
    "retries": 2,
    "stale_threshold_days": 3,
    "monthly_stale_threshold_days": 40,
    "min_interval_seconds": 2          // 串行低频：两次请求的最小间隔
  },
  "sources": [
    {
      "id": "em_csi300",
      "kind": "http_json",              // http_json | http_csv | rss
      "enabled": true,
      "series": ["market.cn_equity.csi300"],
      "interval_seconds": 1800,
      "release_lag_days": 0,            // PIT 四要素
      "publish_hour": 18,
      "publish_minute": 0,
      "tz_offset": "+08:00",
      "backup_for": null,               // 非空表示它是该主源的备源
      "tier": "t1Public",               // t1Public | t2Credentialed | t3Terminal | t4NotAllowed
      "params": {
        "url": "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        "query": { "secid": "1.000300", "klt": "101" },
        "headers": { "Referer": "https://quote.eastmoney.com/" },
        "rows_path": "data.klines",     // 字符串点路径，或 ["data","us.INX","day"] 键序列
        "row_split": ",",               // 行是分隔字符串时使用
        "date_field": 0,                // 数字索引或字段名
        "value_field": 2,
        "unit": "点",
        "source": "eastmoney"
      }
    }
  ]
}
```

`http_csv` 用 `date_column` / `value_column` / `date_format`（`%m/%d/%Y` 与 Go 布局都接受）；
`rss` 产出文档行，可选 `limit`、`encoding`。

**akshare 类来源**：`kind: "akshare"` 会在加载时被改写为等价的公开 HTTP 端点
（`bond_zh_us_yield_em` → 东财 `RPTA_WEB_TREASURYYIELD`），不引入 Python。
无适配器的函数会置 `enabled=false` 并标 `endpoint_status=notApplicable`。

## 如何新增一个来源 kind

1. 在 `internal/sources/sources.go` 的 `validate()` 里放行新的 `kind` 字符串。
2. 在 `internal/parse/` 增加解析函数，把响应转成 `[]parse.RawRow`（数值）或 `[]parse.Document`（文本）。
3. 在 `internal/service/service.go` 的 `collectOne` 里加一个 `case`：
   ```go
   case "http_xml":
       rows, err = parse.ParseXMLRows(resp.Body, cfg)
   ```
   `parse.Config` 已从 `params` 自动填充；PIT、证据、区间过滤、写 NDJSON 都是公共路径，不需要重写。
4. 在 `internal/parse/parse_test.go` 加一个解析用例（用真实响应的**脱敏**片段，或 `httptest` 桩）。
5. 若探测语义不同（例如需要 POST），改 `internal/fetch.Client`，不要在 service 里另起 HTTP 逻辑。

## `inbox.ingest` 支持范围

- 文件：`.csv` / `.tsv` / `.txt` / `.json` / `.jsonl` / `.ndjson` / `.xlsx`（多工作表）/ `.zip`（递归识别）。
- 清洗：编码探测（UTF-8/BOM/GB18030/GBK/Latin-1）、表头提升、脏行剔除、千分位与货币符、
  占位符（`-`、`N/A`、`null`、`无` …）→ **缺失**，绝不补 0、紧凑日期 `YYYYMMDD`、Excel 序列号、
  长表/宽表/语料三形态识别。
- 列名映射：海外因子优先（`美国国债收益率10年` → `market.global.us10y`），
  全局取最长命中关键词；未命中落 `custom.<file>.<col>`。
- 逐文件结论：`accepted`（`series_id` / `rows` / `release_time_rule` / `evidence`）与
  `rejected`（`reason` + `rejected/<file>.error.txt`）。**脏文件不阻断其它文件**。
- 产出：`<data_home>/intermediate/<series_id>.ndjson`（UTF-8）+ 文件级证据（sha256 / rows / dropped_rows）。

## PIT 推导

| 场景 | 规则 |
|---|---|
| 境内日频（A 股 / 中债 / 港股） | `obs_date` 当日 **18:00 (+08:00)** |
| 隔夜海外（VIX / SP500 / US10Y / DXY） | `obs_date` 次日 **09:00 (+08:00)**（`release_lag_days=1`） |
| 月频 | 按目录 `release_lag_days`（≥1），10:00 (+08:00) |
| 文件含发布列 | 优先用发布列 |

无发布列时使用上表的保守规则，并把依据写进 `release_time_rule`（可查）。

## 数据新鲜度（`sources.health`）

`docs/23 §4.5` 强制要求。新鲜度按**依赖序列最新可用观测日**判定，不是抓取时刻：

| `freshness` | 判定（工作日近似交易日） |
|---|---|
| `fresh` | 最新可用日期距今 ≤ 30 个交易日（ADR-009 G2：可进实时叙事） |
| `stale` | 31..60 个交易日（只能进历史回测/情景分析） |
| `dead` | > 60 个交易日（docs/23 强制条款） |
| `unknown` | 没有任何观测数据 |

- 数据来源：`<data_home>/intermediate/*.ndjson` 的 `obs_date`（不是 health 文件里的 `last_success_at`）。
- `dependencies[]` 给出每个依赖序列的 `latest_available` / `observations` / `nan_rate` / `freshness`。
- `nan_rate` = 缺失日期 ÷ **同频 panel 交易日总数**（全 panel 口径）。北向 2342/2902 → 19.3%，
  vix 2892/2902 → 0.34%，与 `docs/18 §7.3` 一致。
- 来源整体 `freshness` 取全部依赖序列中最差的一档；文本来源（RSS/语料）无数值依赖时为 `unknown`。

真实数据已锁定断言（`internal/service/freshness_test.go`）：northbound 最新 2024-08-16、
southbound/credit/repo/usdcny 最新 2025-09-30、vix/sp500 最新 2026-10-27。

## 错误码
严格按 `contracts/README.md §2`：`E_INVALID_PARAMS`(-32602)、`E_NOT_INITIALIZED`(-32008)、
`E_CONTRACT_MISMATCH`(-32005)、`E_NOT_AUTHORIZED`(-32002)、`E_SOURCE_UNAVAILABLE`(-32003)、
`E_DATA_MISSING`(-32004)、`E_RATE_LIMITED`(-32006)。所有错误 `data.detail.reason` 必填。

## 自更新

```bash
collector --selfupdate <installer> --expected-sha256 <hash> \
          [--wait-pid <pid>] [--restart <exe>] [--wait-timeout 60s]
```

顺序：校验 sha256（不匹配即中止，不执行任何东西）→ 等主进程退出 → 静默运行安装器
（Windows `/VERYSILENT /NORESTART /SUPPRESSMSGBOXES`）→ 重启应用。
**未提供 `--expected-sha256` 时拒绝执行。**

## 验证

```bash
cd services/collector
go vet ./... && go test ./...
```

测试覆盖：脏 CSV 清洗、zip 展开、xlsx 多表、编码探测、列名映射优先级（us10y vs cgb_10y）、
缺失值不等于 0、release_time 推导、五态探测、备源切换、区间过滤、dry_run、错误码形状、
台账回退 YAML、数据新鲜度分档与 NaN 率。

**真实样本回归**（`internal/inbox/real_data_test.go`、`internal/service/freshness_test.go`）：
直接吃 `/mnt/shared/recently/commorcial/data/custom/` 下的真实 CSV（22 日频 + 5 月频 + 9798 篇语料），
断言逐列行数、release_time 沿用文件列、北向 2024-08-16 停更后无 0 填充、ZIP 递归展开、新鲜度口径。
样本不存在时跳过；可用 `CBR_REAL_CUSTOM_DIR` 指定目录。
