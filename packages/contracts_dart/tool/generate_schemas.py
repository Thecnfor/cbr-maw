#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 contracts/ 下的 JSON Schema 与样例。

用法（在仓库根执行）：
    python3 packages/contracts_dart/tool/generate_schemas.py

真源：本文件内的规格表（SPEC）；产出：
    contracts/tools/tools.json
    contracts/tools/<tool>.params.schema.json
    contracts/<domain>/<method>.{request,response}.schema.json
    contracts/examples/<method>/*.json

`contracts/` 下的 JSON 是跨语言契约的唯一真源；Dart 类型层由
`generate_types.py` 从这些 JSON 反向生成。

字段口径来源：
- 工具参数/默认值：docs/legacy-configs/tools.yaml + 旧版 cbr/tools/*.py 的 pydantic 模型
- allowed_roles：docs/legacy-configs/roles.yaml 的 tool_permissions
- 方法清单与信封：contracts/README.md §1/§2/§3
- 错误码：contracts/README.md §2
"""


# --------------------------------------------------------------------------- #
# 通用工具
# --------------------------------------------------------------------------- #
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def f(name, type, required=True, desc="", **kw):
    d = {"name": name, "type": type, "required": required, "desc": desc}
    d.update(kw)
    return d


# --------------------------------------------------------------------------- #
# 工具注册表（contracts/tools/tools.json）
# --------------------------------------------------------------------------- #
# allowed_roles 来自 docs/legacy-configs/roles.yaml 的 tool_permissions。
TOOL_DEFAULTS = {
    "risk_measure": {
        "lookback": 252,
        "annualization": 252,
        "confidence": 0.95,
        "horizon_days": 1,
        "values_are": "price",
        "min_observations": 20,
    },
    "systemic_risk": {
        "lookback": 252,
        "tail_q": 0.05,
        "dy_window": 120,
        "dy_lag": 1,
        "dy_horizon": 10,
        "values_are": "price",
    },
    "capital_flow": {
        "lookback": 60,
        "z_window": 60,
        "anomaly_z": 1.5,
        "top_n": 5,
        "flow_unit": "亿元",
    },
    "funding_cost": {
        "lookback": 252,
        "momentum_window": 20,
        "spread_unit": "bp",
        "cost_jump_bp": 50.0,
        "cost_medium_bp": 25.0,
        "refinancing_horizon_days": 90,
    },
    "scenario": {
        "lookback": 252,
        "us_equity_drop_pct": 10.0,
        "fx_depreciation_pct": 5.0,
        "spread_widening_bp": 100.0,
        "method": "both",
        "analog_k": 10,
        "spread_unit": "bp",
        "min_observations": 60,
        "values_are": "price",
    },
    "forecast": {
        "horizon": 5,
        "include_drivers": True,
    },
    "knowledge_search": {
        "top_k": 5,
    },
}

# 序列默认值：tools.yaml 的 series / dy_series，按旧版 cbr/tools/settings.py 的
# TOOL_SERIES_PARAMS 映射注入到对应参数名。
TOOL_SERIES_DEFAULTS = {
    "risk_measure": {"series_id": "market.cn_equity.csi300"},
    "systemic_risk": {
        "market_series_id": "market.cn_equity.csi300",
        "asset_series_id": "market.cn_bond.cgb_index",
        "series_ids": [
            "market.cn_equity.csi300",
            "market.global.sp500",
            "market.fx.usdcny",
            "market.global.vix",
        ],
    },
    "capital_flow": {
        "inflow_series_id": "crossborder.flows.northbound_net",
        "outflow_series_id": "crossborder.flows.southbound_net",
        "ah_premium_series_id": "crossborder.flows.ah_premium",
    },
    "funding_cost": {"spread_series_id": "rates.credit.aa_spread"},
    "scenario": {
        "target_series_id": "market.cn_equity.csi300",
        "us_equity_series_id": "market.global.sp500",
        "fx_series_id": "market.fx.usdcny",
        "spread_series_id": "rates.credit.aa_spread",
    },
    "forecast": {},
    "knowledge_search": {},
}

# allowed_roles：roles.yaml 中 tool_permissions 含该工具的角色。
TOOL_ALLOWED_ROLES = {
    "risk_measure": ["regulator", "investor", "financing"],
    "systemic_risk": ["regulator", "investor"],
    "capital_flow": ["regulator", "investor"],
    "funding_cost": ["financing"],
    "scenario": ["regulator", "investor", "financing"],
    "forecast": ["regulator", "investor", "financing"],
    "knowledge_search": ["regulator", "investor", "financing"],
}

TOOL_META = {
    "risk_measure": {
        "legacy_ref": "commorcial/src/cbr/tools/risk.py",
        "unit": "loss_ratio",
        "desc": "年化波动率、历史/参数 VaR 与 CVaR、最大回撤、压力分位（确定性纯计算）",
    },
    "systemic_risk": {
        "legacy_ref": "commorcial/src/cbr/tools/systemic.py",
        "unit": "ratio",
        "desc": "ΔCoVaR、MES、Diebold-Yilmaz 跨市场溢出指数（确定性纯计算）",
    },
    "capital_flow": {
        "legacy_ref": "commorcial/src/cbr/tools/capital.py",
        "unit": "z",
        "desc": "跨境资金异常净流入 z-score、同步撤离、集中度与 AH 溢价（确定性纯计算）",
    },
    "funding_cost": {
        "legacy_ref": "commorcial/src/cbr/tools/funding.py",
        "unit": "bp",
        "desc": "信用利差代理、融资成本变化（bp）、再融资窗口估计（确定性纯计算）",
    },
    "scenario": {
        "legacy_ref": "commorcial/src/cbr/tools/scenario.py",
        "unit": "ratio",
        "desc": "汇率/美股/利差冲击的线性与历史类比情景映射及压力传导（确定性纯计算）",
    },
    "forecast": {
        "legacy_ref": "commorcial/src/cbr/tools/forecast.py",
        "unit": "probability",
        "desc": "读取共享多模态风险信号（P1 产物，只读）并输出统一 Evidence",
    },
    "knowledge_search": {
        "legacy_ref": "commorcial/src/cbr/tools/kb_search.py",
        "unit": None,
        "desc": "时点过滤的知识库检索（政策/方法学/事件复盘），返回 chunk_id 可核验引文",
    },
}

# 工具参数（字段名/类型/约束/默认值取自旧版 pydantic 模型 + tools.yaml）
TOOL_PARAMS = {
    "risk_measure": [
        f("series_id", "str", False, "序列 ID；默认取 tools.yaml series.equity", default="market.cn_equity.csi300"),
        f("lookback", "int", False, "回看交易日数", minimum=30, maximum=2000, default=252),
        f("annualization", "int", False, "年化因子", minimum=1, maximum=366, default=252),
        f("confidence", "num", False, "置信水平", exclusive_minimum=0.5, exclusive_maximum=1.0, default=0.95),
        f("horizon_days", "int", False, "VaR/CVaR 持有期（日）", minimum=1, maximum=60, default=1),
        f("values_are", "enum:price,return", False, "输入序列是价格还是收益率", default="price"),
        f("min_observations", "int", False, "最少收益观测数", minimum=2, maximum=2000, default=20),
    ],
    "systemic_risk": [
        f("market_series_id", "str", False, "市场侧序列（资产端基准）", default="market.cn_equity.csi300"),
        f("asset_series_id", "str", False, "资产端序列（CoVaR 资产）", default="market.cn_bond.cgb_index"),
        f("series_ids", "arr[str]", False, "DY 溢出指数使用的跨市场序列集合", default=TOOL_SERIES_DEFAULTS["systemic_risk"]["series_ids"]),
        f("lookback", "int", False, "回看交易日数", minimum=60, maximum=2000, default=252),
        f("tail_q", "num", False, "尾部分位", exclusive_minimum=0.0, exclusive_maximum=0.5, default=0.05),
        f("dy_window", "int", False, "DY 溢出估计窗口", minimum=40, maximum=2000, default=120),
        f("dy_lag", "int", False, "DY 领先阶数", minimum=1, maximum=5, default=1),
        f("dy_horizon", "int", False, "DY 预测步长", minimum=1, maximum=50, default=10),
        f("values_are", "enum:price,return", False, "输入序列是价格还是收益率", default="price"),
    ],
    "capital_flow": [
        f("inflow_series_id", "str", False, "流入序列（北向净流入）", default="crossborder.flows.northbound_net"),
        f("outflow_series_id", "str", False, "流出序列（南向净流入；缺失时工具降级）", default="crossborder.flows.southbound_net"),
        f("ah_premium_series_id", "str", False, "AH 溢价序列", default="crossborder.flows.ah_premium"),
        f("lookback", "int", False, "回看交易日数", minimum=20, maximum=500, default=60),
        f("z_window", "int", False, "z-score 估计窗口", minimum=10, maximum=500, default=60),
        f("anomaly_z", "num", False, "异常阈值（z）", exclusive_minimum=0.0, default=1.5),
        f("top_n", "int", False, "集中度统计前 N 条", minimum=1, maximum=20, default=5),
        f("flow_unit", "str", False, "流量单位", default="亿元"),
    ],
    "funding_cost": [
        f("spread_series_id", "str", False, "信用利差序列", default="rates.credit.aa_spread"),
        f("lookback", "int", False, "回看交易日数", minimum=60, maximum=2000, default=252),
        f("momentum_window", "int", False, "利差动量窗口", minimum=1, maximum=120, default=20),
        f("spread_unit", "enum:pct,bp", False, "利差单位", default="bp"),
        f("cost_jump_bp", "num", False, "融资成本跳升阈值（bp）", exclusive_minimum=0.0, default=50.0),
        f("cost_medium_bp", "num", False, "融资成本中度抬升阈值（bp）", minimum=0.0, default=25.0),
        f("refinancing_horizon_days", "int", False, "再融资窗口（日）", minimum=1, maximum=365, default=90),
    ],
    "scenario": [
        f("target_series_id", "str", False, "情景目标序列", default="market.cn_equity.csi300"),
        f("us_equity_series_id", "str", False, "美股冲击序列", default="market.global.sp500"),
        f("fx_series_id", "str", False, "汇率冲击序列", default="market.fx.usdcny"),
        f("spread_series_id", "str", False, "利差冲击序列", default="rates.credit.aa_spread"),
        f("lookback", "int", False, "回看交易日数", minimum=60, maximum=2000, default=252),
        f("us_equity_drop_pct", "num", False, "美股下跌冲击（%）", minimum=0.0, maximum=100.0, default=10.0),
        f("fx_depreciation_pct", "num", False, "人民币贬值冲击（%）", minimum=0.0, maximum=100.0, default=5.0),
        f("spread_widening_bp", "num", False, "信用利差走阔冲击（bp）", minimum=0.0, maximum=1000.0, default=100.0),
        f("method", "enum:linear,historical,both", False, "情景方法", default="both"),
        f("analog_k", "int", False, "历史类比样本数", minimum=1, maximum=50, default=10),
        f("spread_unit", "enum:pct,bp", False, "利差单位", default="bp"),
        f("min_observations", "int", False, "最少观测数", minimum=20, maximum=2000, default=60),
        f("values_are", "enum:price,return", False, "输入序列是价格还是收益率", default="price"),
    ],
    "forecast": [
        f("horizon", "int", False, "预测步长（日）", minimum=1, maximum=250, default=5),
        f("include_drivers", "bool", False, "是否输出驱动因子分解", default=True),
    ],
    "knowledge_search": [
        f("query", "str", True, "检索式（1..500 字符）", min_length=1, max_length=500),
        f("top_k", "int", False, "返回条数", minimum=1, maximum=20, default=5),
        f("tags", "arr[str]", False, "标签过滤", default=None),
    ],
}

TOOL_ORDER = [
    "risk_measure",
    "systemic_risk",
    "capital_flow",
    "funding_cost",
    "scenario",
    "forecast",
    "knowledge_search",
]

# --------------------------------------------------------------------------- #
# 错误码（contracts/README.md §2）
# --------------------------------------------------------------------------- #
ERROR_CODES = [
    (-32700, "E_PARSE", "行不是合法 JSON", False),
    (-32600, "E_INVALID_REQUEST", "缺 method/id 等", False),
    (-32601, "E_METHOD_NOT_FOUND", "未知方法", False),
    (-32602, "E_INVALID_PARAMS", "参数不合法", False),
    (-32603, "E_INTERNAL", "内部异常（带 stack 摘要）", False),
    (-32001, "E_PLATFORM_UNSUPPORTED", "该平台不支持（如 Android 无 sidecar）", False),
    (-32002, "E_NOT_AUTHORIZED", "来源需授权/需登录", False),
    (-32003, "E_SOURCE_UNAVAILABLE", "不可达/反爬受限/已过期", True),
    (-32004, "E_DATA_MISSING", "必需数据缺失（缺失 ≠ 零值）", False),
    (-32005, "E_CONTRACT_MISMATCH", "契约或 schema 版本不匹配", False),
    (-32006, "E_RATE_LIMITED", "被限流", True),
    (-32007, "E_TIMEOUT", "超时", True),
    (-32008, "E_NOT_INITIALIZED", "未握手", False),
    (-32009, "E_PERMISSION_DENIED", "角色越权（工具未执行）", False),
]

# --------------------------------------------------------------------------- #
# 方法（contracts/README.md §3）
# --------------------------------------------------------------------------- #
# 每个方法：domain ∈ {core, collector, kernel}；params/result 为字段列表；
# defs 为该方法内共享的嵌套对象定义。

DB_VIEWS = [
    "market_daily",
    "macro_monthly",
    "pit_observations",
    "data_cards",
    "documents",
    "signals",
    "cfsi_history",
    "series_catalog",
    "ingest_batches",
    "audit_events",
]

METHODS = [
    # ---------------- 核心（collector 与 kernel 均实现） ---------------- #
    {
        "name": "initialize",
        "domain": "core",
        "params": [
            f("contract_version", "str", True, "契约版本（契约/VERSION）"),
            f("client_version", "str", True, "客户端版本"),
            f("workspace", "str", True, "工作区绝对路径"),
            f("data_home", "str", True, "可写根绝对路径"),
            f("resource_home", "str", True, "只读资源根绝对路径"),
            f("capabilities", "arr[str]", False, "客户端能力清单"),
        ],
        "result": [
            f("sidecar", "enum:collector,kernel", True, "sidecar 身份"),
            f("version", "str", True, "sidecar 版本"),
            f("contract_version", "str", True, "契约版本"),
            f("schema_version", "int", True, "schema 版本"),
            f("capabilities", "arr[str]", True, "sidecar 能力清单"),
        ],
        "defs": {},
    },
    {
        "name": "shutdown",
        "domain": "core",
        "params": [],
        "result": [f("stopped", "bool", True, "是否已进入退出流程")],
        "defs": {},
    },
    {
        "name": "ping",
        "domain": "core",
        "params": [],
        "result": [
            f("pong", "bool", True, "存活应答"),
            f("server_time", "str", False, "sidecar 当前时刻（ISO 8601）"),
        ],
        "defs": {},
    },
    # ---------------- 采集域（Go collector） ---------------- #
    {
        "name": "sources.list",
        "domain": "collector",
        "params": [
            f("include_disabled", "bool", False, "是否包含不可自动抓取的条目", default=False),
        ],
        "result": [f("sources", "arr[ref:SourceLedgerEntry]", True, "来源台账条目")],
        "defs": {
            "SourceLedgerEntry": [
                f("id", "str", True, "台账条目 ID（XL-xx / REG-xx）"),
                f("modality", "str", True, "模态（text/speech/image/video/numeric）"),
                f("subject", "str", True, "采集对象"),
                f("source_name", "str", True, "数据来源名称"),
                f("tier", "enum:t1Public,t2Credentialed,t3Terminal,t4NotAllowed", True, "可达性分档"),
                f("access_mode", "str", True, "访问方式"),
                f("authorization_status", "str", True, "授权状态"),
                f("endpoint_status", "enum:known,toVerify,notApplicable", True, "端点核实状态"),
                f("reachability", "str", True, "运行期可达性状态"),
                f("series_ids", "arr[str]", True, "关联规范序列 ID"),
                f("last_success_at", "str", False, "最后一次成功抓取时刻"),
                f("last_error", "str", False, "最近一次失败原因摘要"),
                f("notes", "str", False, "备注"),
            ]
        },
    },
    {
        "name": "sources.probe",
        "domain": "collector",
        "params": [
            f("source_id", "str", True, "台账条目 ID"),
            f("timeout_s", "int", False, "探测超时（秒）", minimum=1, maximum=300, default=20),
        ],
        "result": [
            f("source_id", "str", True, "台账条目 ID"),
            f(
                "state",
                "enum:reachable,need_auth,need_login,restricted,unreachable",
                True,
                "探测结论（五态）",
            ),
            f("detail", "ref:ProbeDetail", True, "探测明细"),
        ],
        "defs": {
            "ProbeDetail": [
                f("reason", "str", True, "中文短句说明"),
                f("checked_at", "str", True, "探测时刻"),
                f("http_status", "int", False, "HTTP 状态码（如适用）"),
                f("latency_ms", "int", False, "探测耗时（毫秒）"),
            ]
        },
    },
    {
        "name": "sources.health",
        "domain": "collector",
        "params": [],
        "result": [f("entries", "arr[ref:HealthEntry]", True, "各来源健康状态")],
        "defs": {
            "HealthEntry": [
                f("source_id", "str", True, "台账条目 ID"),
                f("last_success_at", "str", False, "最后一次成功抓取时刻"),
                f("stale", "bool", True, "是否已超过 staleThresholdDays"),
                f("coverage_start", "str", False, "覆盖区间起始日"),
                f("coverage_end", "str", False, "覆盖区间结束日"),
                f("failure_reason", "str", False, "失败原因（五态映射）"),
                f(
                    "state",
                    "enum:reachable,need_auth,need_login,restricted,unreachable",
                    True,
                    "可达性状态",
                ),
            ]
        },
    },
    {
        "name": "collect.run",
        "domain": "collector",
        "params": [
            f("source_id", "str", True, "台账条目 ID"),
            f("range", "ref:DateRange", False, "抓取区间"),
            f("dry_run", "bool", False, "只探测不落盘", default=False),
        ],
        "result": [
            f("job_id", "str", True, "抓取任务 ID"),
            f(
                "status",
                "enum:ok,partial,failed,skipped",
                True,
                "任务结论",
            ),
            f("written_files", "arr[str]", True, "落盘的规范化中间文件"),
            f("evidence", "arr[ref:CollectEvidence]", True, "来源证据"),
        ],
        "defs": {
            "DateRange": [
                f("start", "str", False, "起始日（YYYY-MM-DD）"),
                f("end", "str", False, "结束日（YYYY-MM-DD）"),
            ],
            "CollectEvidence": [
                f("evidence_id", "str", True, "证据 ID"),
                f("source_id", "str", True, "台账条目 ID"),
                f("series_id", "str", True, "关联序列 ID"),
                f("rows", "int", True, "观测条数"),
                f("release_time_rule", "str", True, "release_time 推导规则（可查）"),
                f("file", "str", False, "产出文件相对路径"),
            ],
        },
    },
    {
        "name": "inbox.ingest",
        "domain": "collector",
        "params": [
            f("path", "str", True, "投递文件绝对路径"),
            f("declared_source", "str", False, "用户声明的来源 ID"),
            f("as_of", "str", False, "时点（ISO 8601 或 YYYY-MM-DD）"),
        ],
        "result": [
            f("batch_id", "str", True, "清洗批次 ID"),
            f("accepted", "arr[ref:AcceptedFile]", True, "接受的文件"),
            f("rejected", "arr[ref:RejectedFile]", True, "拒绝的文件"),
        ],
        "defs": {
            "AcceptedFile": [
                f("file", "str", True, "文件名"),
                f("series_id", "str", True, "解析出的规范序列 ID"),
                f("rows", "int", True, "有效行数"),
                f("release_time_rule", "str", True, "release_time 推导规则"),
                f("evidence", "ref:InboxEvidence", False, "文件级证据"),
            ],
            "RejectedFile": [
                f("file", "str", True, "文件名"),
                f("reason", "str", True, "拒绝原因（中文短句）"),
                f("error_file", "str", False, "错误明细文件路径"),
            ],
            "InboxEvidence": [
                f("evidence_id", "str", True, "证据 ID"),
                f("source_id", "str", True, "来源 ID（未知时为 null）"),
                f("declared_source", "str", False, "用户声明的来源 ID"),
                f("rows", "int", True, "有效行数"),
                f("dropped_rows", "int", True, "剔除的脏行数"),
                f("hash", "str", True, "内容哈希（64 位小写 hex）"),
            ],
        },
    },
    {
        "name": "events.poll",
        "domain": "collector",
        "params": [f("job_id", "str", False, "只看某个任务的事件")],
        "result": [f("events", "arr[ref:CollectEvent]", True, "抓取事件流")],
        "defs": {
            "CollectEvent": [
                f("ts", "str", True, "事件时刻（ISO 8601）"),
                f("type", "str", True, "事件类型（started/progress/succeeded/failed）"),
                f("job_id", "str", True, "任务 ID"),
                f("payload", "map[str,any]", False, "事件负载"),
            ]
        },
    },
    # ---------------- 内核域（Rust kernel） ---------------- #
    {
        "name": "db.query",
        "domain": "kernel",
        "params": [
            f("view", "enum:" + ",".join(DB_VIEWS), True, "具名视图（不接受任意 SQL）"),
            f("filters", "map[str,any]", False, "参数化过滤条件"),
            f("as_of", "str", True, "时点（由 kernel 强制注入过滤）"),
            f("limit", "int", False, "返回行上限", minimum=1, maximum=100000, default=1000),
        ],
        "result": [
            f("columns", "arr[str]", True, "列名"),
            f("rows", "arr[arr[any]]", True, "行数据"),
            f("as_of", "str", True, "实际生效的时点"),
            f("truncated", "bool", True, "是否因 limit 截断"),
        ],
        "defs": {},
    },
    {
        "name": "db.write",
        "domain": "kernel",
        "params": [
            f("table", "str", True, "目标表（受白名单约束）"),
            f("rows", "arr[obj]", True, "待写入行"),
            f("idempotency_key", "str", True, "幂等键（重放同键不重复写）"),
        ],
        "result": [
            f("written", "int", True, "实际写入行数"),
            f("idempotency_key", "str", True, "回显的幂等键"),
        ],
        "defs": {},
    },
    {
        "name": "pit.ingest",
        "domain": "kernel",
        "params": [
            f("source", "str", True, "中间文件来源描述"),
            f("path", "str", True, "中间文件绝对路径"),
            f("declared", "obj", False, "声明的时点与映射信息"),
            f("idempotency_key", "str", True, "幂等键"),
        ],
        "result": [
            f("series", "arr[ref:PitSeries]", True, "写入的序列"),
            f("derived_recomputed", "arr[str]", True, "重算的派生序列 ID"),
            f("coverage_gate", "ref:CoverageGate", True, "覆盖率守门结论"),
        ],
        "defs": {
            "PitSeries": [
                f("series_id", "str", True, "规范序列 ID"),
                f("rows", "int", True, "写入行数"),
                f("release_time_rule", "str", True, "release_time 推导规则"),
                f("coverage", "ref:Coverage", True, "覆盖区间"),
            ],
            "Coverage": [
                f("start", "str", True, "起始日"),
                f("end", "str", True, "结束日"),
            ],
            "CoverageGate": [
                f("passed", "bool", True, "是否通过守门"),
                f("baseline", "num", True, "基线覆盖率"),
                f("current", "num", True, "本次覆盖率"),
            ],
        },
    },
    {
        "name": "kb.index",
        "domain": "kernel",
        "params": [
            f("corpus_dir", "str", True, "语料目录绝对路径"),
            f("force", "bool", False, "强制重建索引", default=False),
        ],
        "result": [
            f("documents", "int", True, "文档数"),
            f("chunks", "int", True, "分块数"),
            f("index_version", "str", True, "索引版本（如 kb-bm25-v1）"),
        ],
        "defs": {},
    },
    {
        "name": "kb.search",
        "domain": "kernel",
        "params": [
            f("query", "str", True, "检索式（1..500 字符）", min_length=1, max_length=500),
            f("top_k", "int", False, "返回条数", minimum=1, maximum=50, default=5),
            f("filters", "map[str,any]", False, "过滤条件（来源/时间等）"),
        ],
        "result": [f("hits", "arr[ref:KbHit]", True, "检索命中")],
        "defs": {
            "KbHit": [
                f("chunk_id", "str", True, "分块 ID"),
                f("score", "num", True, "打分"),
                f("text", "str", True, "分块原文"),
                f("document_id", "str", True, "文档 ID"),
                f("locator", "str", True, "文档内定位"),
                f("published_at", "str", False, "文档发布时间"),
                f("source_id", "str", False, "来源 ID"),
            ]
        },
    },
    {
        "name": "workspace.info",
        "domain": "kernel",
        "params": [],
        "result": [
            f("path", "str", True, "工作区路径"),
            f("size_bytes", "int", True, "占用字节数"),
            f("schema_version", "int", True, "schema 版本"),
            f("series_count", "int", True, "序列数"),
            f("obs_count", "int", True, "观测总数"),
            f("last_ingest_at", "str", False, "最近一次入库时刻"),
        ],
        "defs": {},
    },
    {
        "name": "workspace.migrate",
        "domain": "kernel",
        "params": [f("target_version", "int", True, "目标 schema 版本", minimum=1)],
        "result": [
            f("from", "int", True, "迁移前版本"),
            f("to", "int", True, "迁移后版本"),
        ],
        "defs": {},
    },
    {
        "name": "features.build",
        "domain": "kernel",
        "params": [
            f("series_ids", "arr[str]", True, "参与计算的序列 ID"),
            f("as_of", "str", True, "时点"),
        ],
        "result": [
            f("built", "int", True, "生成的特征数"),
            f("feature_ids", "arr[str]", True, "特征 ID"),
        ],
        "defs": {},
    },
    {
        "name": "signal.compute",
        "domain": "kernel",
        "params": [f("as_of", "str", True, "时点")],
        "result": [
            f("signal_id", "str", True, "信号 ID"),
            f("value", "num", True, "压力概率"),
            f("dims", "map[str,any]", True, "各维度贡献"),
            f("missing_dims", "arr[str]", True, "缺席维度（不参与计算，禁止填充）"),
            f("limitations", "arr[str]", True, "局限性说明"),
        ],
        "defs": {},
    },
    {
        "name": "cfsi.compute",
        "domain": "kernel",
        "params": [f("as_of", "str", True, "时点")],
        "result": [
            f("cfsi", "num", True, "CFSI 数值"),
            f("level", "enum:low,medium,high,critical", True, "压力等级"),
            f("tau", "num", True, "阈值 τ"),
            f("dims", "map[str,any]", True, "六维明细（缺席维度不出现）"),
            f("missing_dims", "arr[str]", True, "缺席维度"),
            f("limitations", "arr[str]", True, "局限性说明"),
            f("provenance", "map[str,any]", True, "来源与版本溯源"),
        ],
        "defs": {},
    },
    {
        "name": "tools.invoke",
        "domain": "kernel",
        "params": [
            f("tool", "enum:" + ",".join(TOOL_ORDER), True, "工具名（须在 tools.json 注册表内）"),
            f("params", "obj", True, "工具参数（按 `tools/<tool>.params.schema.json`）"),
            f("idempotency_key", "str", True, "幂等键"),
        ],
        "result": [f("evidence", "ref:ToolEvidence", True, "工具产出的证据")],
        "defs": {
            "ToolEvidence": [
                f("evidence_id", "str", True, "证据 ID"),
                f("tool", "str", True, "工具名"),
                f("version", "str", True, "工具版本"),
                f("inputs_hash", "str", True, "入参哈希（64 位小写 hex）"),
                f("hash", "str", True, "证据载荷哈希（64 位小写 hex）"),
                f("value", "num", False, "主数值"),
                f("unit", "str", False, "单位"),
                f("as_of", "str", True, "时点"),
                f("params", "obj", True, "规范化后的入参"),
            ]
        },
    },
    {
        "name": "kernel.hash",
        "domain": "kernel",
        "params": [
            f("payload", "obj", True, "待哈希载荷"),
            f("kind", "enum:inputs_hash,evidence_id,evidence_hash", True, "哈希种类"),
        ],
        "result": [f("hash", "str", True, "哈希结果")],
        "defs": {},
    },
]

# --------------------------------------------------------------------------- #
# 样例（contracts/examples/<method>/*.json）—— 全部为 SYNTHETIC 契约夹具
# --------------------------------------------------------------------------- #
EXAMPLES = {
    "initialize": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "initialize",
            "params": {
                "contract_version": "1.0.0",
                "client_version": "0.1.0",
                "workspace": "/tmp/cbr-workspace",
                "data_home": "/tmp/cbr-workspace/data-home",
                "resource_home": "/opt/cbr/resource-home",
                "capabilities": ["sources.list", "collect.run"],
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "1",
            "result": {
                "sidecar": "kernel",
                "version": "0.1.0",
                "contract_version": "1.0.0",
                "schema_version": 3,
                "capabilities": ["db.query", "tools.invoke"],
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "1",
            "error": {
                "code": -32005,
                "message": "契约版本不匹配",
                "data": {
                    "kind": "E_CONTRACT_MISMATCH",
                    "retryable": False,
                    "detail": {
                        "reason": "客户端契约版本 0.9.0 与 sidecar 1.0.0 不匹配",
                        "expected": "1.0.0",
                        "actual": "0.9.0",
                    },
                },
            },
        },
    },
    "shutdown": {
        "ok": {"jsonrpc": "2.0", "id": "9", "method": "shutdown", "params": {}},
        "ok_result": {"jsonrpc": "2.0", "id": "9", "result": {"stopped": True}},
        "error": {
            "jsonrpc": "2.0",
            "id": "9",
            "error": {
                "code": -32603,
                "message": "退出流程异常",
                "data": {
                    "kind": "E_INTERNAL",
                    "retryable": False,
                    "detail": {"reason": "关闭工作区句柄失败", "stack": "RuntimeError: close failed"},
                },
            },
        },
    },
    "ping": {
        "ok": {"jsonrpc": "2.0", "id": "10", "method": "ping", "params": {}},
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "10",
            "result": {"pong": True, "server_time": "2026-11-25T09:00:00+08:00"},
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "10",
            "error": {
                "code": -32008,
                "message": "未握手",
                "data": {
                    "kind": "E_NOT_INITIALIZED",
                    "retryable": False,
                    "detail": {"reason": "收到业务方法前必须先完成 initialize 握手"},
                },
            },
        },
    },
    "sources.list": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "20",
            "method": "sources.list",
            "params": {"include_disabled": False},
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "20",
            "result": {
                "sources": [
                    {
                        "id": "REG-01",
                        "modality": "numeric",
                        "subject": "沪深300指数",
                        "source_name": "交易所公开行情",
                        "tier": "t1Public",
                        "access_mode": "publicHttp",
                        "authorization_status": "notRequired",
                        "endpoint_status": "known",
                        "reachability": "reachable",
                        "series_ids": ["market.cn_equity.csi300"],
                        "last_success_at": "2026-11-24T18:05:00+08:00",
                        "last_error": None,
                        "notes": None,
                    }
                ]
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "20",
            "error": {
                "code": -32001,
                "message": "平台不支持本地计算",
                "data": {
                    "kind": "E_PLATFORM_UNSUPPORTED",
                    "retryable": False,
                    "detail": {"reason": "当前平台不提供 collector sidecar", "platform": "android"},
                },
            },
        },
    },
    "sources.probe": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "21",
            "method": "sources.probe",
            "params": {"source_id": "REG-01", "timeout_s": 20},
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "21",
            "result": {
                "source_id": "REG-01",
                "state": "need_login",
                "detail": {
                    "reason": "端点返回 302 跳转登录页，需人工登录后重试",
                    "checked_at": "2026-11-25T09:01:00+08:00",
                    "http_status": 302,
                    "latency_ms": 412,
                },
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "21",
            "error": {
                "code": -32602,
                "message": "参数不合法",
                "data": {
                    "kind": "E_INVALID_PARAMS",
                    "retryable": False,
                    "detail": {"reason": "timeout_s 必须在 1..300 之间", "field": "timeout_s"},
                },
            },
        },
    },
    "sources.health": {
        "ok": {"jsonrpc": "2.0", "id": "22", "method": "sources.health", "params": {}},
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "22",
            "result": {
                "entries": [
                    {
                        "source_id": "REG-01",
                        "last_success_at": "2026-11-24T18:05:00+08:00",
                        "stale": False,
                        "coverage_start": "2026-11-01",
                        "coverage_end": "2026-11-24",
                        "failure_reason": None,
                        "state": "reachable",
                    }
                ]
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "22",
            "error": {
                "code": -32003,
                "message": "来源不可达",
                "data": {
                    "kind": "E_SOURCE_UNAVAILABLE",
                    "retryable": True,
                    "detail": {
                        "reason": "连续 3 次探测超时，判定为不可达",
                        "source_id": "REG-07",
                        "retry_after_seconds": 300,
                    },
                },
            },
        },
    },
    "collect.run": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "23",
            "method": "collect.run",
            "params": {
                "source_id": "REG-01",
                "range": {"start": "2026-11-01", "end": "2026-11-24"},
                "dry_run": False,
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "23",
            "result": {
                "job_id": "job_20261125_0001",
                "status": "ok",
                "written_files": ["intermediate/market.cn_equity.csi300.csv"],
                "evidence": [
                    {
                        "evidence_id": "ev_collect_REG-01_20261125_0001",
                        "source_id": "REG-01",
                        "series_id": "market.cn_equity.csi300",
                        "rows": 18,
                        "release_time_rule": "obs_date 18:00 +08:00",
                        "file": "intermediate/market.cn_equity.csi300.csv",
                    }
                ],
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "23",
            "error": {
                "code": -32002,
                "message": "来源需授权",
                "data": {
                    "kind": "E_NOT_AUTHORIZED",
                    "retryable": False,
                    "detail": {
                        "reason": "该来源为 T2 终端来源，需用户先在设置页配置凭证",
                        "source_id": "REG-09",
                    },
                },
            },
        },
    },
    "inbox.ingest": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "24",
            "method": "inbox.ingest",
            "params": {
                "path": "/tmp/cbr-workspace/data-home/inbox/user_batch_20261125.csv",
                "declared_source": "REG-01",
                "as_of": "2026-11-25T09:00:00+08:00",
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "24",
            "result": {
                "batch_id": "batch_20261125_0001",
                "accepted": [
                    {
                        "file": "user_batch_20261125.csv",
                        "series_id": "market.cn_equity.csi300",
                        "rows": 20,
                        "release_time_rule": "obs_date 18:00 +08:00",
                        "evidence": {
                            "evidence_id": "ev_inbox_batch_20261125_0001",
                            "source_id": "REG-01",
                            "declared_source": "REG-01",
                            "rows": 20,
                            "dropped_rows": 2,
                            "hash": "0000000000000000000000000000000000000000000000000000000000000000",
                        },
                    }
                ],
                "rejected": [
                    {"file": "broken_batch.csv", "reason": "表头无法识别为任何规范序列", "error_file": None}
                ],
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "24",
            "error": {
                "code": -32004,
                "message": "必需数据缺失",
                "data": {
                    "kind": "E_DATA_MISSING",
                    "retryable": False,
                    "detail": {"reason": "文件不存在：/tmp/cbr-workspace/data-home/inbox/missing.csv"},
                },
            },
        },
    },
    "events.poll": {
        "ok": {"jsonrpc": "2.0", "id": "25", "method": "events.poll", "params": {"job_id": "job_20261125_0001"}},
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "25",
            "result": {
                "events": [
                    {
                        "ts": "2026-11-25T09:02:00+08:00",
                        "type": "progress",
                        "job_id": "job_20261125_0001",
                        "payload": {"written": 12, "total": 18},
                    }
                ]
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "25",
            "error": {
                "code": -32007,
                "message": "超时",
                "data": {
                    "kind": "E_TIMEOUT",
                    "retryable": True,
                    "detail": {"reason": "等待事件超过 timeout_ms", "timeout_ms": 30000},
                },
            },
        },
    },
    "db.query": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "30",
            "method": "db.query",
            "params": {
                "view": "market_daily",
                "filters": {
                    "series_id": "market.cn_equity.csi300",
                    "start": "2026-01-01",
                    "end": "2026-06-30",
                },
                "as_of": "2026-06-30T18:00:00+08:00",
                "limit": 1000,
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "30",
            "result": {
                "columns": ["obs_date", "value"],
                "rows": [["2026-06-29", 4012.34], ["2026-06-30", 4025.11]],
                "as_of": "2026-06-30T18:00:00+08:00",
                "truncated": False,
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "30",
            "error": {
                "code": -32602,
                "message": "参数不合法",
                "data": {
                    "kind": "E_INVALID_PARAMS",
                    "retryable": False,
                    "detail": {"reason": "view 不在白名单内", "field": "view", "allowed": DB_VIEWS},
                },
            },
        },
    },
    "db.write": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "31",
            "method": "db.write",
            "params": {
                "table": "pit_observations",
                "rows": [
                    {
                        "series_id": "market.cn_equity.csi300",
                        "obs_date": "2026-11-24",
                        "value": 4025.11,
                        "release_time": "2026-11-24T18:00:00+08:00",
                    }
                ],
                "idempotency_key": "idem_20261125_0001",
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "31",
            "result": {"written": 1, "idempotency_key": "idem_20261125_0001"},
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "31",
            "error": {
                "code": -32009,
                "message": "角色越权",
                "data": {
                    "kind": "E_PERMISSION_DENIED",
                    "retryable": False,
                    "detail": {"reason": "当前角色无权直接写本地库", "role": "investor"},
                },
            },
        },
    },
    "pit.ingest": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "32",
            "method": "pit.ingest",
            "params": {
                "source": "intermediate-file",
                "path": "/tmp/cbr-workspace/data-home/intermediate/market.cn_equity.csi300.csv",
                "declared": {"release_lag_days": 0, "publish_hour": 18, "tz_offset": "+08:00"},
                "idempotency_key": "idem_pit_20261125_0001",
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "32",
            "result": {
                "series": [
                    {
                        "series_id": "market.cn_equity.csi300",
                        "rows": 18,
                        "release_time_rule": "obs_date 18:00 +08:00",
                        "coverage": {"start": "2026-11-01", "end": "2026-11-24"},
                    }
                ],
                "derived_recomputed": [],
                "coverage_gate": {"passed": True, "baseline": 0.82, "current": 0.86},
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "32",
            "error": {
                "code": -32004,
                "message": "必需数据缺失",
                "data": {
                    "kind": "E_DATA_MISSING",
                    "retryable": False,
                    "detail": {"reason": "中间文件缺少 release_time 推导所需列", "file": "market.cn_equity.csi300.csv"},
                },
            },
        },
    },
    "kb.index": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "33",
            "method": "kb.index",
            "params": {"corpus_dir": "/opt/cbr/resource-home/data/knowledge/corpus", "force": False},
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "33",
            "result": {"documents": 128, "chunks": 940, "index_version": "kb-bm25-v1"},
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "33",
            "error": {
                "code": -32003,
                "message": "语料不可达",
                "data": {
                    "kind": "E_SOURCE_UNAVAILABLE",
                    "retryable": True,
                    "detail": {"reason": "语料目录不存在或不可读", "path": "/opt/cbr/resource-home/data/knowledge/corpus"},
                },
            },
        },
    },
    "kb.search": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "34",
            "method": "kb.search",
            "params": {"query": "跨境资金异常流动的监管口径", "top_k": 5, "filters": {}},
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "34",
            "result": {
                "hits": [
                    {
                        "chunk_id": "doc_0042#007",
                        "score": 8.42,
                        "text": "跨境资金异常流动的监测口径以净额 z-score 与同步撤离为主……",
                        "document_id": "doc_0042",
                        "locator": "第 3 页 第 2 段",
                        "published_at": "2024-05-11",
                        "source_id": "REG-01",
                    }
                ]
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "34",
            "error": {
                "code": -32004,
                "message": "知识库索引缺失",
                "data": {
                    "kind": "E_DATA_MISSING",
                    "retryable": False,
                    "detail": {"reason": "索引尚未构建，请先调用 kb.index", "index_version": "kb-bm25-v1"},
                },
            },
        },
    },
    "workspace.info": {
        "ok": {"jsonrpc": "2.0", "id": "35", "method": "workspace.info", "params": {}},
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "35",
            "result": {
                "path": "/tmp/cbr-workspace",
                "size_bytes": 10485760,
                "schema_version": 3,
                "series_count": 27,
                "obs_count": 128450,
                "last_ingest_at": "2026-11-25T09:02:00+08:00",
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "35",
            "error": {
                "code": -32008,
                "message": "未握手",
                "data": {
                    "kind": "E_NOT_INITIALIZED",
                    "retryable": False,
                    "detail": {"reason": "workspace.info 需在 initialize 之后调用"},
                },
            },
        },
    },
    "workspace.migrate": {
        "ok": {"jsonrpc": "2.0", "id": "36", "method": "workspace.migrate", "params": {"target_version": 3}},
        "ok_result": {"jsonrpc": "2.0", "id": "36", "result": {"from": 2, "to": 3}},
        "error": {
            "jsonrpc": "2.0",
            "id": "36",
            "error": {
                "code": -32005,
                "message": "schema 版本不匹配",
                "data": {
                    "kind": "E_CONTRACT_MISMATCH",
                    "retryable": False,
                    "detail": {"reason": "目标版本 9 不存在", "target_version": 9, "available": [1, 2, 3]},
                },
            },
        },
    },
    "features.build": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "37",
            "method": "features.build",
            "params": {
                "series_ids": ["market.cn_equity.csi300", "market.fx.usdcny"],
                "as_of": "2026-11-25T09:00:00+08:00",
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "37",
            "result": {"built": 12, "feature_ids": ["feat_csi300_ret_5", "feat_usdcny_ret_5"]},
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "37",
            "error": {
                "code": -32004,
                "message": "必需数据缺失",
                "data": {
                    "kind": "E_DATA_MISSING",
                    "retryable": False,
                    "detail": {"reason": "序列 market.fx.usdcny 在该时点无观测", "series_id": "market.fx.usdcny"},
                },
            },
        },
    },
    "signal.compute": {
        "ok": {"jsonrpc": "2.0", "id": "38", "method": "signal.compute", "params": {"as_of": "2026-11-25T09:00:00+08:00"}},
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "38",
            "result": {
                "signal_id": "sig_20261125",
                "value": 0.42,
                "dims": {"equity": 0.31, "fx": 0.18},
                "missing_dims": ["credit"],
                "limitations": ["信用维度数据不可得（需商业授权），未参与计算"],
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "38",
            "error": {
                "code": -32004,
                "message": "信号所需观测不足",
                "data": {
                    "kind": "E_DATA_MISSING",
                    "retryable": False,
                    "detail": {"reason": "as_of 之前可用观测不足模型热身期要求", "as_of": "2026-11-25"},
                },
            },
        },
    },
    "cfsi.compute": {
        "ok": {"jsonrpc": "2.0", "id": "39", "method": "cfsi.compute", "params": {"as_of": "2026-11-25T09:00:00+08:00"}},
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "39",
            "result": {
                "cfsi": 1.24,
                "level": "medium",
                "tau": 1.5,
                "dims": {
                    "equity": {"value": 0.35, "weight": 0.2},
                    "fx": {"value": 0.21, "weight": 0.15},
                },
                "missing_dims": ["credit", "crossborder", "global"],
                "limitations": ["信用/跨境资金/全球维度数据不可得，未参与计算，结论口径待六维齐备后复核"],
                "provenance": {"label_version": "stress_pca_q90", "index_version": "cfsi-v1"},
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "39",
            "error": {
                "code": -32004,
                "message": "CFSI 全部维度缺失",
                "data": {
                    "kind": "E_DATA_MISSING",
                    "retryable": False,
                    "detail": {"reason": "六个维度在 as_of 均无可用观测，无法计算（缺失不得用 0 填充）"},
                },
            },
        },
    },
    "tools.invoke": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "40",
            "method": "tools.invoke",
            "params": {
                "tool": "risk_measure",
                "params": {"series_id": "market.cn_equity.csi300", "lookback": 252},
                "idempotency_key": "idem_tool_20261125_0001",
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "40",
            "result": {
                "evidence": {
                    "evidence_id": "ev_0123456789abcdef",
                    "tool": "risk_measure",
                    "version": "1.0.0",
                    "inputs_hash": "0000000000000000000000000000000000000000000000000000000000000000",
                    "hash": "1111111111111111111111111111111111111111111111111111111111111111",
                    "value": 0.0231,
                    "unit": "loss_ratio",
                    "as_of": "2026-11-25",
                    "params": {"lookback": 252, "series_id": "market.cn_equity.csi300"},
                }
            },
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "40",
            "error": {
                "code": -32009,
                "message": "角色越权",
                "data": {
                    "kind": "E_PERMISSION_DENIED",
                    "retryable": False,
                    "detail": {
                        "reason": "角色 financing 无 risk_measure 调用权限（roles.yaml）",
                        "role": "financing",
                        "tool": "risk_measure",
                    },
                },
            },
        },
    },
    "kernel.hash": {
        "ok": {
            "jsonrpc": "2.0",
            "id": "41",
            "method": "kernel.hash",
            "params": {
                "payload": {"tool": "risk_measure", "version": "1.0.0", "as_of": "2026-11-25", "params": {"lookback": 252}},
                "kind": "inputs_hash",
            },
        },
        "ok_result": {
            "jsonrpc": "2.0",
            "id": "41",
            "result": {"hash": "0000000000000000000000000000000000000000000000000000000000000000"},
        },
        "error": {
            "jsonrpc": "2.0",
            "id": "41",
            "error": {
                "code": -32602,
                "message": "参数不合法",
                "data": {
                    "kind": "E_INVALID_PARAMS",
                    "retryable": False,
                    "detail": {"reason": "kind 必须是 inputs_hash / evidence_id / evidence_hash", "field": "kind"},
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# 生成逻辑
# ---------------------------------------------------------------------------


import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CONTRACTS = os.path.join(ROOT, "contracts")


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")


def type_schema(spec):
    """把紧凑类型串翻译为 JSON Schema 片段。"""
    if spec.startswith("enum:"):
        return {"type": "string", "enum": spec[5:].split(",")}
    if spec.startswith("ref:"):
        return {"$ref": "#/$defs/" + spec[4:]}
    if spec.startswith("arr["):
        return {"type": "array", "items": type_schema(spec[4:-1])}
    if spec == "str":
        return {"type": "string"}
    if spec == "int":
        return {"type": "integer"}
    if spec == "num":
        return {"type": "number"}
    if spec == "bool":
        return {"type": "boolean"}
    if spec == "obj":
        return {"type": "object"}
    if spec == "map[str,any]":
        return {"type": "object", "additionalProperties": True}
    if spec == "arr[arr[any]]":
        return {"type": "array", "items": {"type": "array", "items": {}}}
    if spec == "any":
        return {}
    raise ValueError("未知类型：" + spec)


def field_schema(field):
    node = type_schema(field["type"])
    if not field["required"]:
        # 可选字段允许 null（缺席与显式 null 同义）。
        if "type" in node and isinstance(node["type"], str):
            node["type"] = [node["type"], "null"]
            if "enum" in node:
                node["enum"] = [*node["enum"], None]
        elif "$ref" in node:
            node = {"oneOf": [node, {"type": "null"}]}
    for key, jkey in (
        ("minimum", "minimum"),
        ("maximum", "maximum"),
        ("exclusive_minimum", "exclusiveMinimum"),
        ("exclusive_maximum", "exclusiveMaximum"),
        ("min_length", "minLength"),
        ("max_length", "maxLength"),
    ):
        if key in field:
            node[jkey] = field[key]
    if "default" in field:
        node["default"] = field["default"]
    node["description"] = field["desc"]
    return node


def object_schema(fields, defs=None, extra=True):
    props = {f["name"]: field_schema(f) for f in fields}
    required = [f["name"] for f in fields if f["required"]]
    node = {"type": "object", "properties": props}
    if required:
        node["required"] = required
    node["additionalProperties"] = extra
    if defs:
        node["$defs"] = {
            name: object_schema(items) for name, items in defs.items()
        }
    return node


# --------------------------------------------------------------------------- #
# 1. 工具注册表
# --------------------------------------------------------------------------- #
def build_tools_json():
    entries = []
    for name in TOOL_ORDER:
        meta = TOOL_META[name]
        unit = meta["unit"]
        returns = {
            "value": "number" if unit is not None else None,
            "unit": "string" if unit is not None else None,
            "as_of": "datetime",
        }
        entries.append(
            {
                "tool": name,
                "version": TOOL_DEFAULTS and "1.0.0",
                "risk_level": "L0",
                "allowed_roles": TOOL_ALLOWED_ROLES[name],
                "params_schema_ref": f"contracts/tools/{name}.params.schema.json",
                "returns": returns,
                "deterministic": True,
                "legacy_ref": meta["legacy_ref"],
                "description": meta["desc"],
                "default_params": {
                    **TOOL_DEFAULTS[name],
                    **TOOL_SERIES_DEFAULTS[name],
                },
            }
        )
    return {
        "registry_version": "tools-v1",
        "default_deny": True,
        "contract_version": "1.0.0",
        "tools": entries,
    }


def build_tool_params_schema(name):
    fields = []
    for f in TOOL_PARAMS[name]:
        f = dict(f)
        if not f["required"] and f["name"] in TOOL_SERIES_DEFAULTS[name]:
            f["default"] = TOOL_SERIES_DEFAULTS[name][f["name"]]
        elif not f["required"] and "default" not in f:
            pass
        fields.append(f)
    node = object_schema(fields)
    node = {
        "$schema": SCHEMA_DIALECT,
        "$id": f"contracts/tools/{name}.params.schema.json",
        "title": f"{name} 工具入参",
        "description": (
            "工具入参 schema。默认值与 docs/legacy-configs/tools.yaml 一致；"
            "旧版实现见 " + TOOL_META[name]["legacy_ref"] + "。"
            "additionalProperties=false 对齐旧版 pydantic extra='forbid'。"
        ),
        **node,
    }
    return node


# --------------------------------------------------------------------------- #
# 2. 方法 request / response schema
# --------------------------------------------------------------------------- #
ENVELOPE_PROPS = {
    "jsonrpc": {"const": "2.0"},
    "id": {"type": "string", "minLength": 1},
}


def error_schema_node():
    return {
        "type": "object",
        "required": ["code", "message", "data"],
        "additionalProperties": False,
        "properties": {
            "code": {"type": "integer"},
            "message": {"type": "string"},
            "data": {
                "type": "object",
                "required": ["kind", "retryable", "detail"],
                "additionalProperties": False,
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [k for _, k, _, _ in ERROR_CODES],
                    },
                    "retryable": {"type": "boolean"},
                    "detail": {
                        "type": "object",
                        "required": ["reason"],
                        "properties": {
                            "reason": {"type": "string", "minLength": 1},
                            "source_id": {"type": "string"},
                            "retry_after_seconds": {"type": "integer"},
                            "retryable": {"type": "boolean"},
                            "field": {"type": "string"},
                            "stack": {"type": "string"},
                        },
                        "additionalProperties": True,
                    },
                },
            },
        },
    }


def build_request_schema(method, dom):
    params = object_schema(method["params"], extra=False)
    node = {
        "$schema": SCHEMA_DIALECT,
        "$id": f"contracts/{dom}/{method['name']}.request.schema.json",
        "title": f"{method['name']} 请求信封",
        "description": (
            f"JSON-RPC 2.0 请求信封；method 固定为 {method['name']}。"
            "副作用等级与工具权限由 contracts/tools/tools.json 与 roles 矩阵决定。"
        ),
        "type": "object",
        "required": ["jsonrpc", "id", "method", "params"],
        "additionalProperties": False,
        "properties": {
            "jsonrpc": ENVELOPE_PROPS["jsonrpc"],
            "id": ENVELOPE_PROPS["id"],
            "method": {"const": method["name"]},
            "params": params,
        },
    }
    if method["defs"]:
        node["$defs"] = {name: object_schema(items) for name, items in method["defs"].items()}
    return node


def build_response_schema(method, dom):
    result = object_schema(method["result"])
    ok = {
        "type": "object",
        "required": ["jsonrpc", "id", "result"],
        "additionalProperties": False,
        "properties": {
            "jsonrpc": ENVELOPE_PROPS["jsonrpc"],
            "id": ENVELOPE_PROPS["id"],
            "result": result,
        },
    }
    err = {
        "type": "object",
        "required": ["jsonrpc", "id", "error"],
        "additionalProperties": False,
        "properties": {
            "jsonrpc": ENVELOPE_PROPS["jsonrpc"],
            "id": ENVELOPE_PROPS["id"],
            "error": error_schema_node(),
        },
    }
    node = {
        "$schema": SCHEMA_DIALECT,
        "$id": f"contracts/{dom}/{method['name']}.response.schema.json",
        "title": f"{method['name']} 响应信封",
        "description": (
            f"{method['name']} 的成功或失败响应。失败时 error.data.kind 取 "
            "contracts/README.md §2 错误码表；detail.reason 必填（中文短句）。"
        ),
        "oneOf": [ok, err],
    }
    if method["defs"]:
        node["$defs"] = {name: object_schema(items) for name, items in method["defs"].items()}
    return node


# --------------------------------------------------------------------------- #
# 3. 样例
# --------------------------------------------------------------------------- #
def write_examples():
    for method in METHODS:
        name = method["name"]
        samples = EXAMPLES[name]
        base = os.path.join(CONTRACTS, "examples", name)
        write_json(os.path.join(base, "01-request-ok.json"), samples["ok"])
        write_json(os.path.join(base, "02-response-ok.json"), samples["ok_result"])
        write_json(os.path.join(base, "03-error.json"), samples["error"])


def domain_dirs(method):
    """核心生命周期方法归属「两者」：在 collector/ 与 kernel/ 各放一份（内容一致）。"""
    if method["domain"] == "core":
        return ["collector", "kernel"]
    return [method["domain"]]


def main():
    write_json(os.path.join(CONTRACTS, "tools", "tools.json"), build_tools_json())
    for name in TOOL_ORDER:
        write_json(
            os.path.join(CONTRACTS, "tools", f"{name}.params.schema.json"),
            build_tool_params_schema(name),
        )
    for method in METHODS:
        for dom in domain_dirs(method):
            write_json(
                os.path.join(
                    CONTRACTS, dom, f"{method['name']}.request.schema.json"
                ),
                build_request_schema(method, dom),
            )
            write_json(
                os.path.join(
                    CONTRACTS, dom, f"{method['name']}.response.schema.json"
                ),
                build_response_schema(method, dom),
            )
    write_examples()
    print("methods:", len(METHODS))
    print("db views:", len(DB_VIEWS))
    print("tools:", len(TOOL_ORDER))


if __name__ == "__main__":
    main()
