# 跨境金融市场压力高位状态：公开数据源实测与标签方案

> 项目：CBR-MAW 跨境金融风险多智能体协同预警系统（论文方向 2）
> 本文性质：数据可行性实测报告（本机 2026-10-18 实测）+ 标签方案设计建议
> 实测环境：Windows 11 / Python 3.12.14 / `.venv-probe`（akshare 1.19.1、yfinance 1.7.0、requests 2.34.2、pandas 3.0.6）
> 复现脚本：`scripts/probe_akshare.py`、`scripts/probe_akshare2.py`、`scripts/probe_yfinance.py`、`scripts/probe_network.py`、`scripts/probe_final.py`
> 原始日志：`docs/research/probe_akshare.log`、`probe_akshare2.log`、`probe_final.log`

---

## 0. 结论速览（先看这个）

**确定可用（本机实测跑通、无需 key、含历史）：**

| 数据域 | 首选源（实测可用） | 历史起点 | 关键接口 |
|---|---|---|---|
| A 股指数（沪深300） | akshare → 新浪源 | 2002-01-04 | `ak.stock_zh_index_daily("sh000300")` |
| 恒生指数 | akshare → 新浪源 | 2013-08-20 | `ak.stock_hk_index_daily_sina("HSI")` |
| 在岸人民币 | yfinance | 2014-01（10y+） | `yf.download("CNY=X")` |
| 离岸人民币 CNH | 东方财富 push2his | **2011-01-03** | `secid=133.USDCNH` 日 K 线 |
| 人民币中间价 | akshare（中国银行/外管局口径） | 1994 起（8066 行） | `ak.currency_boc_safe()` |
| 中/美国债收益率（2/5/10/30Y） | akshare | 2015-01-02 起 | `ak.bond_zh_us_rate(start_date="20150101")` |
| 国债/信用债收益率曲线 | akshare（中债） | 中债库，短区间可查 | `ak.bond_china_yield(...)` + 曲线名过滤 |
| 全球风险（VIX/MOVE/标普/美元指数/商品） | yfinance | 2014-01（10y+） | `^VIX`、`^MOVE`、`^GSPC`、`DX-Y.NYB`、`GC=F`、`CL=F`、`HG=F` |
| 南向资金（港股通） | akshare / 东财 | 2014-11-17 起，**至今连续** | `ak.stock_hsgt_hist_em("南向资金")` |
| 北向持股（个股级） | akshare | 2017-03-17 起 | `ak.stock_hsgt_individual_em("600519")` |
| 财经快讯/新闻 | akshare（东财/财联社） | 实时滚动（最新 200 条） | `ak.stock_info_global_em()`、`ak.stock_info_global_cls()` |
| 新闻联播文本（政策语料） | akshare | 按日期回溯 | `ak.news_cctv(date="20241018")` |
| 央行/外管局政策列表 | 官网静态 HTML | 列表页近 1-2 页 | pbc.gov.cn、safe.gov.cn 列表页 |
| 国务院政策文件库 | 政府网 JSON API | 全库 6222 条 | `sousuo.www.gov.cn/search-gov/data?...` |

**关键负面结论（必须写进论文的数据约束）：**
1. **北向资金"实时/每日净买额"自 2024-08-19 起停披露**：东财/akshare 历史序列 2024-08-16 为最后一个非空值（-67.75 亿元），之后全为空。不可 ffill、不可当作 0。替代：南向资金（连续可用）+ 北向个股持股加总（成本高）。**这是本项目最大的数据风险点。**
2. **FRED 直连不可用**：`fred.stlouisfed.org` 12s 读超时；`fredgraph.stlouisfed.org` SSL 错误；`api.stlouisfed.org` 可达但**需要 api_key**（HTTP 400）。无 key 时 VIXCLS/DGS10/BAMLH0A0HYM2 均取不到。替代：VIX→`^VIX`、DGS10→`^TNX` 或 `bond_zh_us_rate`；HY OAS 无直接替代（建议用 HYG/LQD 价格比率或中债信用利差近似，或注册免费 FRED key 后补）。
3. **Yahoo 无中国指数/CNH 历史**：`000300.SS`、`CNH=X` 无论 `range=1y/5y/max` 均只返回 1 根（2026-10-16）；`^VHSI` 404。中国指数走 akshare/新浪，CNH 走东财。
4. **akshare 的东财系接口在本机被断连**（`RemoteDisconnected`）：`index_zh_a_hist`、`stock_hk_index_daily_em`、`stock_zh_index_daily_em`、`forex_spot_em` 均失败（约 5-7s 超时断连），但**同样数据用原生 `requests` 直连东财 push2 完全正常**（见 §2.2）→ 结论：东财数据可用，但要绕开 akshare 的东财封装，或固定 UA/重试。
5. **GDELT 可达但强限速**：接口返回 429 "Please limit requests to one every 5 seconds"，需 ≥6-10s 间隔 + 重试。
6. 新闻/政策列表：**东方财富新闻列表 API 需 `req_trace` 参数**；**证监会列表页为 JS 动态渲染**（`common_list.js` 内部 JSON 接口为 `/searchList/{channelid}?...`，channelid 待定位）；**国务院"最新政策"列表页 JS 动态渲染**，但政策文件库 JSON API 可用。

---

## 1. 环境与复现

### 1.1 独立探测环境（已创建，未污染主环境）

```powershell
C:\Users\w5555\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe -m venv .venv-probe
.\.venv-probe\Scripts\python.exe -m pip install akshare yfinance requests pandas
```

实测：安装成功，`PIP_EXIT=0`；版本为 `akshare 1.19.1 / yfinance 1.7.0 / requests 2.34.2 / pandas 3.0.6`。
注意：**pandas 3.0.6 较新**，akshare 运行时出现大量 `Pandas4Warning: The default 'epoch' date format is deprecated`，功能不受影响；若要长期稳定，建议锁定 `pandas<3` 或 `akshare>=1.19`+`pandas==2.x` 组合后再验证。

### 1.2 实测方法

- 每个接口独立 try/except、记录耗时、shape、列名、前 2 行样例；失败记录异常类型与消息。
- 行情/收益率类额外核对"历史起点、最后一个有效日期、单位"。
- 政策/新闻类核对"列表页是否静态可解析、是否带日期"。
- 全部原始输出见 `docs/research/*.log`。

---

## 2. 实测明细（逐源记录）

### 2.1 akshare（1.19.1）

| 接口 | 实测 | 耗时 | 结果要点 |
|---|---|---|---|
| `stock_hsgt_fund_flow_summary_em()` | ✅ OK | 139ms | 4 行（沪股通/深股通/港股通沪/深），列：交易日、类型、板块、资金方向、交易状态、成交净买额、资金净流入、当日资金余额、上涨数、持平数、下跌数、相关指数、指数涨跌幅。**北向成交净买额=0.0（已停披露）**；南向港股通(沪) 成交净买额 -20.66 亿、资金净流入 420.0 亿（2026-10-16） |
| `stock_hsgt_hist_em(symbol="北向资金")` | ✅ OK | 1.2s | 2770 行 × 13 列，2014-11-17 → 2026-10-16；列：日期、当日成交净买额、买入成交额、卖出成交额、历史累计净买额、当日资金流入、当日余额、持股市值、领涨股…**当日成交净买额最后一个非空值 = 2024-08-16（-67.75 亿元），2024-08-19 起全 NaN** |
| `stock_hsgt_hist_em(symbol="南向资金")` | ✅ OK | 1.1s | 2732 行，2014-11-17 → 2026-10-16，**连续有值**（2026-10-16：-35.68 亿元，成交 309.17 亿） |
| `stock_hsgt_hold_stock_em(...)` | ❌ FAIL | 0.3-0.4s | `TypeError: 'NoneType' object is not subscriptable`（东财接口改版，2024-08 口径调整后该汇总接口失效） |
| `stock_hsgt_individual_em("600519")` | ✅ OK | 1.7s | 1683 行，2017-03-17 起；列：持股日期、当日收盘价、当日涨跌幅、持股数量、持股市值、持股数量占A股百分比、今日增持股数、今日增持资金、今日持股市值变化 → **北向持股可用个股级重建** |
| `index_zh_a_hist("000300",...)` | ❌ FAIL | 5.3s | `ConnectionError: RemoteDisconnected`（东财封装；原生 push2his 正常） |
| `stock_zh_index_daily_em("sh000300")` | ❌ FAIL | 0.2s | 同上 |
| `stock_zh_index_daily("sh000300")` | ✅ OK | 218ms | **6010 行，2002-01-04 起**；列 date/open/high/low/close/volume → 沪深300 首选历史源 |
| `stock_hk_index_daily_em("HSI")` | ❌ FAIL | 5.2s | RemoteDisconnected |
| `stock_hk_index_daily_sina("HSI")` | ✅ OK | 482ms | 3239 行，2013-08-20 起；列 date/open/high/low/close/volume/amount → 恒指历史源 |
| `bond_zh_us_rate(start_date="20150101")` | ✅ OK | 1.4s | **3142 行，2015-01-02 起**；列：日期、中国国债收益率2年/5年/10年/30年、10年-2年、美国国债收益率2年/5年/10年/30年、10年-2年、GDP → 中美国债收益率首选（10 年日频，含中美利差） |
| `bond_china_yield(start_date, end_date)` | ✅ OK（短区间） | 6.1s / 2 个月样本 | 2024-01-01→2024-07-01 共 372 行；列：曲线名称、日期、3月/6月/1年/3年/5年/7年/10年/30年；曲线名含 `中债国债收益率曲线`、`中债中短期票据收益率曲线(AAA)`、`中债商业银行普通债收益率曲线(AAA)` → **可算信用利差 = AAA 中票 5Y − 国债 5Y**。⚠️ 一次拉 2015-2026 返回 0 行 → 必须分段（按月/季）拉取 |
| `currency_boc_safe()` | ✅ OK | 3.8-4.6s | 8066 行，1994 起；列：日期、美元、欧元、日元…；**单位为"每 100 外币兑人民币"**（如 1994 美元=870.0 → 8.70），/100 后使用 |
| `fx_spot_quote()` | ⚠️ 半可用 | 212ms | 25 个货币对，但买/卖报价全为 null → 即期报价不可用 |
| `forex_hist_em(symbol="USDCNY")` | ❌ FAIL | 0ms | `KeyError: 'USDCNY'`（接口参数表无此 symbol） |
| `forex_spot_em()` | ❌ FAIL | 6.0s | RemoteDisconnected |
| `stock_info_global_em()` | ✅ OK | 0.2s | 200 行；列：标题、摘要、发布时间、链接；发布时间**秒级**（如 2026-10-18 15:11:27）→ 快讯首选 |
| `stock_info_global_cls()` | ✅ OK | 0.2s | 20 行；列：标题、内容、发布日期、发布时间（时:分:秒） |
| `news_cctv(date="20241018")` | ✅ OK | 3.6s | 14 行；列：date/title/content，按日回溯 → 政策语料长历史可用（注意逐日抓取成本） |
| `news_economic_baidu(date)` | ✅ OK | 0.4s | 68 行；列：日期、时间、地区、事件、公布、预期、前值、重要性 → 宏观日历 |

### 2.2 东方财富 push2 行情 API（原生 requests）

| 接口 | 实测 | 要点 |
|---|---|---|
| `push2.eastmoney.com/api/qt/stock/get?secid=1.000300` | ✅ 516ms | 返回 `{"f43":417061,"f57":"000300","f58":"沪深300","f60":416601,"f170":11}`；f43=最新价×100（4170.61），f60=昨收，f170=涨跌幅×100（0.11%）。无需 key |
| `push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.000300&klt=101&fqt=0` | ✅ 175ms | 日 K 线（14.6KB/500 日）；`fields2=f51..f58` 对应 日期,开,收,高,低,成交量,成交额,振幅；`dktotal=5289`（自 2005-04-08） |
| `push2.eastmoney.com/api/qt/kamt/get` | ✅ 129-256ms | 沪深港通资金：`hk2sh.dayNetAmtIn=0.0`（北向已停披露）、`sh2hk.dayNetAmtIn=4200000`（万元=420 亿，南向）、`status=3`（收盘）；日期 2026-10-16 |
| `push2his.../kline/get?secid=133.USDCNH` | ✅ 439ms | **4109 根日线，2011-01-03 → 2026-10-16**；名称"美元兑离岸人民币"（open,close,high,low 顺序）→ CNH 历史最佳来源（Yahoo 无历史） |
| `push2his.../kline/get?secid=133.HKDCNH` | ✅ | 430 根，2025-02-24 起（短历史） |
| `secid=133.USDCNY / 119.USDCNY / 100.CN10Y` 等 | ❌ rc=100 | 这些 secid 不存在，不要猜；USDCNY 走 yfinance/中行中间价，中债 10Y 走 akshare |
| `np-listapi.eastmoney.com/comm/web/getNewsByColumns` | ⚠️ 需参数 | 不带 `req_trace` 返回 `"Required String parameter 'req_trace' is not present"`；带上后未验证成功，新闻建议走 akshare 封装 |

### 2.3 yfinance（1.7.0，Yahoo chart API）

| 标的 | 实测（2014-01-01 起下载） | 历史 | 最后值（2026-10-16） |
|---|---|---|---|
| `^GSPC` 标普500 | ✅ 3217 行，6.8s（首调） | 2014-01-02 起 | 7659.44 |
| `^VIX` | ✅ 3219 行，0.7s | 2014-01-02 起 | 19.99 |
| `^HSI` 恒指 | ✅ 3148 行，0.7s | 2014-01-02 起 | 24186.83 |
| `^TNX` 美10Y | ✅ 3216 行，0.8s | 2014-01-02 起 | 5.098（**已是百分数**，与 `bond_zh_us_rate` 同日 5.09 交叉核对一致，勿再除 10） |
| `^MOVE` 美债波动率 | ✅ 3159 行，0.9s | 2014-01-02 起 | 101.10 |
| `CNY=X` 在岸人民币 | ✅ 3330 行，0.7s | 2014-01 起 | 6.6862 |
| `^VIX9D` / `^VIX3M` / `^SKEW` | ✅ | 短窗口图表 API 200 | 20.12 / 20.50 / 168.59 |
| `DX-Y.NYB` / `GC=F` / `CL=F` / `HG=F` / `^N225` | ✅ | chart API 200 | 101.84 / 4181.1 / 99.02 / 6.5735 / 65324.3 |
| `000300.SS` 沪深300 | ❌ 仅 1 行 | **Yahoo 已无历史**（range=1y/5y/max 都只有 2026-10-16） | 4170.61 |
| `CNH=X` | ❌ 仅 1 行 | **Yahoo 已无历史** | 6.6853 |
| `^VHSI` 恒指波指 | ❌ 404 | 已下架 | — |

结论：yfinance 可用于**美股/全球因子**；中国 A 股指数与 CNH 不要用 Yahoo。字段：下载默认含 Open/High/Low/Close/Adj Close/Volume；做点时特征建议 `auto_adjust=False` 用原始收盘价，指数无复权问题。

### 2.4 FRED（不可用，需 key）

| 方式 | 实测 |
|---|---|
| `https://fred.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS` | ❌ read timeout（requests 12s 超时、urllib 25s 超时），连续多次 |
| `https://fredgraph.stlouisfed.org/graph/fredgraph.csv?id=VIXCLS` | ❌ SSLError（1.2s） |
| `https://api.stlouisfed.org/fred/series/observations?...` | ⚠️ 可达 0.55s，但 HTTP 400：`Variable api_key is not set` |

结论：FRED 系列（VIXCLS、DGS10、BAMLH0A0HYM2、BAMLC0A0CM、DEXCHUS、T10Y2Y 等）**本机无 key 不可得**。替代方案：
- VIXCLS → yfinance `^VIX`（严格日频，够用）
- DGS10 → yfinance `^TNX` 或 `bond_zh_us_rate` 美国国债列
- BAMLH0A0HYM2（高收益 OAS）→ **无直接替代**：可用 `HYG`/`LQD` 价格比、或中债 AAA-国债利差（境内信用）、或注册免费 FRED key（`https://fredaccount.stlouisfed.org/apikeys`）后用 `api.stlouisfed.org`（本机可达）。
- 若坚持 FRED：建议申请 key + 走 `api.stlouisfed.org`（已证明网络可达），或找国内镜像（未验证）。

### 2.5 GDELT

- 接口：`https://api.gdeltproject.org/api/v2/doc/doc?query=...&mode=artlist&maxrecords=5&format=json&sort=datedesc`
- 实测：**可达**。首次（PowerShell/Invoke-WebRequest）返回 OK，12.8s，含 `articles[].url/title/seendate/language/sourcecountry`；随后连续 3 次 429：`"Please limit requests to one every 5 seconds"` → 需 ≥6-10s 间隔 + 指数退避。
- 时点：`seendate` 为 GDELT 抓取/索引时间（`20261018T064500Z`），与真实发布时间有滞后 → **近似**，只适合做事件/情绪辅助特征，不建议作为严格 point-in-time 主特征。

### 2.6 政策文本源（只测列表页，未深爬）

| 源 | 实测 | 可抓取性 |
|---|---|---|
| 中国人民银行 新闻发布（沟通交流） `pbc.gov.cn/goutongjiaoliu/113456/113469/index.html` | ✅ 200，~35-38KB | **静态 HTML**，16 条带标题+日期（如 2026-10-17），可靠；编码 UTF-8（requests 需 `r.content.decode("utf-8")`，否则乱码） |
| 中国人民银行 货币政策司（政策/公开市场） `pbc.gov.cn/zhengcehuobisi/125207/125227/125957/index.html` | ✅ 200，~110-118KB | **静态 HTML**，114 个带 title 链接、106 个日期 |
| 国家外汇管理局 新闻 `safe.gov.cn/safe/whxw/index.html` | ✅ 200，~20-23KB | **静态 HTML**，15 条带标题+日期（2026-10-15 等）；分页 `index_2.html` |
| 中国证监会 `csrc.gov.cn/csrc/c100028/common_list.shtml`（证监会要闻） | ⚠️ 200 但列表 JS 渲染（14KB 壳） | 栏目 JSON 接口在 `/csrc/xhtml/js/common_list.js` 中：`/searchList/{channelid}?_isAgg=true&_isJson=true&_pageSize=18&_template=index&page=N`，返回 `title/url/publishedTimeStr`；**channelid 需从栏目页定位（本次未拿到）** |
| 证监会 新闻发布 `csrc.gov.cn/csrc/xwfb/index.shtml` | ⚠️ 200，有文章链接（c106311/…content.shtml）但标题嵌套标签 | 需 HTML 解析；不如 JSON 接口稳 |
| 国务院"最新政策" `gov.cn/zhengce/zuixin/` | ⚠️ 200，列表 JS 动态渲染（`listArrP`） | 列表页不可直接抓；改走政策文件库 JSON（下） |
| **国务院政策文件库 JSON** `sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_gw&...` | ✅ 200，258ms | 返回 `searchVO.listVO[]`：`title / pubtimeStr / pubtime(epoch) / pcode(发文字号) / id`，可关键词+年份+文种（国发/国办发…）过滤；totalCount 示例 6222 → **国务院政策首选，日级发布日期严格可得** |
| 东方财富财经新闻 `finance.eastmoney.com` | ✅ 200 首页可抓；列表 API 需 `req_trace` | 建议用 akshare `stock_info_global_em`（已封装，200 条秒级时间戳） |
| 新浪财经 roll 新闻 `feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&...` | ✅ 200 JSON ~10KB | 含 `title/url/ctime`；**可用**（新浪主站 403，但 feed API 正常） |

政策文本时点评级：
- PBOC/SAFE 列表页：**近似**（只有发布日期，无时分）→ 特征中按"发布日期次日可用"处理（保守）。
- 国务院政策文件库：**近似（日级）**，pubtime 为发布日期。
- 新闻快讯（东财/财联社）：**严格时间戳（秒级）**。
- GDELT：**近似**（索引时间滞后）。
- 政策详情页正文：静态 HTML 可抓，但需控制频率（政府站 WAF）。

### 2.7 时点可得性评级汇总

> 密钥需求：除 FRED 外，**本节所有源（东财 push2/akshare/yfinance/新浪 feed/政策网站/GDELT）均无需 API key**；GDELT 只需限速。FRED 需免费 key。

| 源 | 评级 | 处理建议 |
|---|---|---|
| 东财 push2/ push2his 日线、K 线 | **严格时间戳**（按交易日） | 特征截止 t 日收盘 |
| akshare 行情/资金流/收益率/中间价（日期列） | **严格时间戳**（日度） | 同上 |
| yfinance 日线 | **严格时间戳**（日度，美东日期） | 美股因子在 t 日特征中用 t-1 收盘 |
| 东财/财联社快讯、新闻摘要 | **严格时间戳**（秒级） | 按时间戳切分 t 日 15:00 前后 |
| PBOC/SAFE 列表、政策文件库、新闻联播 | **近似**（发布日期/日级） | shift(1) 保守使用 |
| GDELT | **近似**（抓取时间滞后） | 仅辅助/事件发现 |
| 北向净买入 2024-08-19 后 | **不可得** | 缺失 + regime dummy 或换南向/持股 |
| FRED 系列（无 key） | **不可得** | 换 yfinance/akshare 或申请 key |
| Yahoo 中国指数/CNH | **不可得** | 换 akshare/东财 |
| 证监会列表（直接抓） | **不可得**（JS） | 走 searchList JSON（待 channelid） |
| 国务院最新政策列表（直接抓） | **不可得**（JS） | 走政策文件库 API |

---

## 3. 风险标签候选方案

> 目标：$y$ = 跨境金融市场压力**高位状态**（high-stress state），预测期限 h ∈ {5, 10, 20} 个交易日。
> 原则：标签可用未来信息构造（标签不是特征），但**所有特征/阈值/权重/标准化参数必须只用 t 及以前信息**。

### 3.1 候选 A（主方案）：中国金融压力指数代理 CFSI-CN（0–100 连续指数）

六维特征（每维 2–4 个指标，方向统一为"压力↑"）：

| 维度 | 指标（符号方向） | 数据源 | 频率 |
|---|---|---|---|
| 股票 | 沪深300 5d/20d 收益（负向）；20d 已实现波动（年化）；20d 下行半方差；20d 最大回撤 | `stock_zh_index_daily("sh000300")` | 日 |
| 债券 | 10Y 国债收益率 20d 变动(bp)（上行=压力）；10Y-2Y 期限利差（收窄/倒挂=压力）；**信用利差 = 中债 AAA 中票 5Y − 国债 5Y**（走阔=压力） | `bond_zh_us_rate` + `bond_china_yield` | 日 |
| 汇率 | USDCNH 20d 变动%（人民币贬值=压力）；20d 已实现波动；在岸-离岸价差（CNY=X vs 133.USDCNH，|价差| 大=压力）；人民币中间价偏离（中间价 vs 市场） | `133.USDCNH`（东财）+ `CNY=X`（yfinance）+ `currency_boc_safe` | 日 |
| 跨境资金 | 南向资金 20d 累计净买入/成交额占比（流出=压力）；北向：2014-11→2024-08-16 用 20d 累计净买入，之后用北向个股持股加总变化或 regime dummy | `stock_hsgt_hist_em` + `stock_hsgt_individual_em` | 日 |
| 全球风险 | ^VIX 水平与 5d 变动；^MOVE；^GSPC 20d 收益（负向）；美元指数 DX-Y.NYB 20d 变动；VIX9D/VIX3M 比值（倒挂=压力） | yfinance | 日 |
| 政策/文本 | 央行/外管局/国务院政策发布频率（7d 计数 z-score）；新闻关键词计数（贬值、资本流出、风险、救市、降准、降息、汇率…）7d z-score；GDELT tone（可选，近似） | 快讯接口 + 政策列表/政策文件库 + GDELT | 日 |

**合成步骤（严格无泄漏）：**
1. 每个指标先做 winsorize（1%/99%，训练期确定分位）；
2. 方向统一后，算**滚动 5 年（1250 交易日；不足时用扩展窗口 + min 252 日）经验分位** p∈[0,1]；
3. 两个版本：
   - **主：等权平均** `CFSI_t = 100 × mean_j p_{j,t}`（稳健，便于解释）；
   - 敏感性：PCA 第一主成分——**只用训练期（如 2015–2021）拟合载荷并冻结**，再应用到全样本（避免滚动 PCA 不稳定与 look-ahead）。
4. 输出：`CFSI-CN` 日频序列 + 各维度贡献（便于论文可解释性分析）。

### 3.2 候选 B：高位状态二分类标签（供 5/10/20 日预测）

以 CFSI-CN 为输入，定义两个版本：

- **B1 主标签（未来 h 日内是否进入高位）**：
  `y_{t,h} = 1[ max_{s=1..h} CFSI_{t+s} ≥ τ_high ]`，`τ_high` = **训练期（2015–2021）CFSI 的 90% 分位**（top10%）；稳健性用 85% 分位（top15%）。
- **B2 持续性标签（降噪）**：未来 h 日内有 **≥2 个交易日** CFSI ≥ τ_high，才记 1。

补充规则：
- 三分类（可选）：≥τ90 高压力 / τ75–τ90 中压力 / <τ75 低压力；
- 类别不平衡：h=20 时因窗口重叠正样本率可能 30%+，需报告实际正样本率，模型用 `class_weight`/阈值调参，不要只看 accuracy；
- 敏感性：用"滚动 5 年分位"替代固定阈值；阈值只在训练期确定并**冻结**，测试期不得重估（否则泄漏）。

### 3.3 候选 C：事件窗口标签（弱监督 / 外部验证，非主标签）

人工事件清单（示例，需按论文口径核定）：2015-06/08 股灾与 811 汇改、2016-01 熔断、2018 中美贸易摩擦、2020-01~03 疫情冲击、2022 美联储加息+地产压力、2023-08~10 汇率/外资流出、2024-01 小微盘流动性、2025 关税冲击（如适用）。事件前后 ±h 日窗口记正样本。

用途：
- 不直接作为训练标签（覆盖不全、主观），用于**验证 CFSI 阈值合理性**（事件窗口内 CFSI 是否显著更高）、做 few-shot/提示词评测集（多智能体系统演示）、以及预训练阶段弱监督。
- 可结合新闻关键词/GDELT 自动发现候选事件，再人工确认。

### 3.4 样本期建议

| 方案 | 区间 | 适用 | 说明 |
|---|---|---|---|
| **主样本（推荐）** | **2015-01-01 ~ 2025-12-31** | 训练 2015–2021 / 验证 2022–2023 / 测试 2024–2025 | 2015 汇改后市场结构更接近当前；但跨境维度 2014-11 才有北向、2024-08-19 有口径断点 |
| 稳健性 1 | 2017-01 ~ 2025-12 | 全维度齐备（个股北向持股 2017-03 起、CNH 2011 起、南向 2014 起） | 避开 2015–2016 极端期与数据起点问题 |
| 稳健性 2 | 2010-01 ~ 2025-12 | 长样本 | 中债/美股因子可回溯，但跨境资金维度 2014 前不可得，需降维（仅股/债/汇/全球） |

期限：h=5（周）、10（双周）、20（月），均按**交易日**计，不用自然日。标签与特征都按主交易日历对齐。

### 3.5 交易日历对齐与缺失处理（严格 point-in-time）

**主日历**：沪深300 交易日（`stock_zh_index_daily("sh000300")` 的日期序列）。

**对齐规则（决策时点 = t 日 A 股收盘后）：**
1. A 股/港股/CNH：用 t 日当日收盘（CNH 为 t 日 16:30 前最近价；东财日线按日期直接对齐）；
2. 美股/全球：用 **t-1 日收盘**（美股 t-1 收盘在中国 t 日开盘前已可得）；`merge_asof(direction="backward", allow_exact_matches=True)` 到主日历，**并保留原始日期列**用于审计；
3. 新闻/政策：t 日 15:00 前的新闻可用于 t 日特征；15:00 后的归入 t+1（严格版）；政策列表只有日期 → 全部 `shift(1)` 交易日（保守）；
4. 所有滚动窗口、分位、标准化、PCA 载荷、阈值只用 t 及以前数据。

**缺失处理：**
- 价格类（指数、汇率、VIX…）**不 ffill**，窗口内缺失则丢弃该窗口（或 NaN 交给 LightGBM）；
- 收益率/宏观类可 ffill ≤5 交易日，并加 `missing_flag`；
- **北向净买入 2024-08-19 后不做 ffill（会制造虚假 0）**：置缺失 + `north_regime` dummy（1=停披露期），或用南向/个股持股代理替代该维度；
- 新闻/事件计数缺失按 0 计并加 mask；
- 模型层面：树模型（LightGBM/XGBoost）原生支持 NaN；若用 PCA/回归需先填充（训练期均值）+ mask。

---

## 4. 数据获取脚本建议（伪代码级）

```
# scripts/build_dataset.py（建议实现，产出 data/raw/*.parquet + data/features/master.parquet）

CFG = {start:"2015-01-01", end:"2025-12-31", h:[5,10,20], cal:"sh000300"}

# 1) 主日历与 A 股
hs300  = ak.stock_zh_index_daily("sh000300")            # 2002+，date/open/high/low/close/volume
cal    = hs300["date"]                                   # 主交易日历

# 2) 港股 / 全球
hsi    = ak.stock_hk_index_daily_sina("HSI")             # 2013-08+
gspc   = yf.download("^GSPC", start=..., auto_adjust=False)["Close"]
vix    = yf.download("^VIX",  start=...)
move   = yf.download("^MOVE", start=...)
tnx    = yf.download("^TNX",  start=...)                 # 已是 %
dxy    = yf.download("DX-Y.NYB", start=...)
vix9d  = yf.download("^VIX9D", start=...); vix3m = yf.download("^VIX3M", start=...)

# 3) 汇率
cny    = yf.download("CNY=X", start=...)                 # 在岸
cnh    = eastmoney_kline(secid="133.USDCNH", beg=..., end=..., klt=101)  # 2011+
mid    = ak.currency_boc_safe()                          # 中间价，/100

# 4) 利率/信用
rates  = ak.bond_zh_us_rate(start_date="20150101")       # CN/US 2/5/10/30Y + 利差
# 信用利差：按月分段拉中债曲线，过滤曲线名后 pivot
for month in months(2015-01, 2025-12):
    df = ak.bond_china_yield(start_date=month_start, end_date=month_end)
    gov = df[df.曲线名称=="中债国债收益率曲线"]
    aaa = df[df.曲线名称=="中债中短期票据收益率曲线(AAA)"]
    credit_spread[month] = aaa["5年"] - gov["5年"]

# 5) 跨境资金
south    = ak.stock_hsgt_hist_em("南向资金")             # 2014-11+，连续
north    = ak.stock_hsgt_hist_em("北向资金")             # 北向净买额 2024-08-16 止
holding  = ak.stock_hsgt_individual_em(symbol)           # 个股持股（如需重建北向总量）

# 6) 文本
news_em  = ak.stock_info_global_em()                     # 秒级时间戳 200 条
news_cls = ak.stock_info_global_cls()
policy_gov = get("https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_gw&...")
pbc      = parse_static_list("http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html")
safe     = parse_static_list("https://www.safe.gov.cn/safe/whxw/index.html")

# 7) 特征/标签
feat = build_features(cal, ...)        # 方向统一 + 滚动分位（只用 t 以前）
cfsi = 100 * feat["pct"].mean(axis=1)  # 或训练期 PCA
y_h  = make_label(cfsi, tau=quantile(cfsi[:"2021-12-31"], 0.90), h=h)   # 未来 h 日 max ≥ τ
save_parquet("data/features/master.parquet", feat, cfsi, y_h)
```

**存储建议**：`data/raw/<source>/<table>.parquet` + `data/features/master.parquet`；每张表保留 `source_date`（原始日期）与 `trade_date`（主日历对齐日），便于审计与复现。

---

## 5. 已知坑（务必写进论文数据章节）

1. **北向资金口径断点（最大坑）**：2024-08-19 起北向实时/每日净买入停披露；东财序列 2024-08-16 之后为 NaN。禁止 ffill/置 0；需分段建模或换南向/持股代理。
2. **akshare 东财系接口在本机断连**（`RemoteDisconnected`），但原生 `requests` 直连 push2/push2his 正常 → 不要因 akshare 报错就判定东财不可用；行情类可自己写 requests 客户端（注意 UA、Referer、重试）。
3. **中债 `bond_china_yield` 长区间返回空**：一次拉 10 年 0 行；需按月/季分段（每次 6s 左右），且返回多条曲线（国债/中票 AAA/商业银行 AAA），必须按"曲线名称"过滤。
4. **FRED 直连超时 + 无 key**：VIX/DGS10 等改用 yfinance；HY OAS 无替代；如需 FRED 必须申请免费 key（api 域名本机可达）。
5. **Yahoo 中国指数/CNH 无历史**，`^VHSI` 404；别用 `000300.SS`/`CNH=X` 做回测。
6. **单位陷阱**：东财 push2 f43 为价格×100（指数）、f170 为涨跌%×100；`currency_boc_safe` 美元为"每 100 美元人民币"需 /100；`^TNX` 已是百分数（5.098=5.098%），不要再 /10；南向净买入单位亿元。
7. **时区/时序**：yfinance 日期为美东日期，美股 t 日收盘 ≈ 中国 t+1 日开盘前；严格用 t-1 对齐；CNH 24h 交易，需定收盘切点（建议北京时间 16:30）。
8. **交易日历不一致**：A 股/港股/美股节假日不同；用 `merge_asof` 取最近前一交易日，不要 `merge` 精确匹配；h 期限按主日历交易日计。
9. **复权/停牌**：本方案只用指数，无复权问题；若加 ETF/个股须前复权，停牌日 K 线缺失不可 ffill。
10. **修订**：行情/收益率无修订；宏观数据（GDP 等）有修订 → 避免使用，或用 ALFRED vintage；政策文本"发布日期"≠"可得日期"，保守 shift 1 日。
11. **反爬**：新浪主站 403（feed API 可用）；东财需正常 UA；政府网站有 WAF，列表页抓取加 1-2s 间隔、限页数；GDELT 429 需 ≥6s 间隔 + 退避。
12. **pandas 3.0.6 + akshare 1.19.1**：出现 `Pandas4Warning`（epoch JSON 格式），建议锁定版本组合后再大规模跑；`df.to_json` 的日期序列化需显式 `date_format="iso"`。
13. **证监会列表 JS / 国务院最新政策 JS**：直接抓列表页拿不到条目；证监会走 `/searchList/{channelid}` JSON（channelid 需从栏目页定位，本次未完成），国务院走政策文件库 API。

---

## 6. 最小可行原型数据栈（建议直接落地）

**MVP（一周内跑通）**：
- 沪深300（新浪，2002+）、恒指（新浪，2013+）
- CNY=X、133.USDCNH（东财，2011+）
- 中美国债收益率（`bond_zh_us_rate`，2015+）+ 中债信用利差（分段）
- VIX、MOVE、标普、美元指数（yfinance）
- 南向资金（akshare，2014-11+）
- 东财/财联社快讯 + 央行/外管局列表 + 国务院政策文件库（文本特征）
- 标签：CFSI-CN（等权分位复合）→ B1/B2 二分类，h=5/10/20

**待补/降级**：
- 北向维度：若必须保留，用 `stock_hsgt_individual_em` 对成分股加总重建（注意 2017-03 起、成本与覆盖率），否则 2024-08 后置缺失 + dummy；
- HY OAS：无 key 时用 HYG/LQD 价格比或境内信用利差替代；
- 证监会政策：定位 channelid 后接 `/searchList` JSON；否则用证监会发布/新华社转载。
