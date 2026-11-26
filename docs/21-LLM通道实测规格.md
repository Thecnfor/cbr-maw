# 21 · LLM 通道实测规格（2026-11-25）

> 目的：把两个模型端点的**真实可用性与请求/响应形状**固化下来，避免实现阶段靠猜。
> 全部结论来自对真实端点的实际调用（状态码与响应体原文）。

## 1. DeepSeek（生成侧）—— **当前密钥失效**

| 项 | 实测结果 |
|---|---|
| 端点 | `https://api.deepseek.com`（`.env` 的 `DEEPSEEK_BASE_URL`） |
| 调用 | `POST {base}/chat/completions`，头 `Authorization: Bearer {DEEPSEEK_API_KEY}`、`Content-Type: application/json` |
| 请求 | `{"model":"deepseek-chat","messages":[{"role":"user","content":"..."}],"max_tokens":16,"temperature":0}` |
| **现状** | **HTTP 401** `{"error":{"message":"Authentication Fails, Your api key: ****1852 is invalid","code":"invalid_request_error"}}` |
| 结论 | **密钥已失效**（`.env` 与 `secrets/deepseek.key` 是同一把）。生成侧（角色分析文本、结论撰写、情绪打分）**无法真跑**，直到换有效密钥 |

实现要求（不因密钥失效而降低）：
- 生成侧不可用时**必须显式失败并引导到设置页**，禁止用规则模板或词典分冒充模型结论（零 Mock 严格模式）。
- 密钥校验按旧版口径（`commorcial/src/cbr/llm/connect.py`）：`GET {base}/user/balance` 确认账号、`POST {base}/chat/completions`（max_tokens=1）确认模型可用；官方域名（`api.deepseek.com`）的异常响应**不得**当成功。

## 2. JEV / TypeSafe System One（裁判侧）—— **实测可用**

| 项 | 实测结果 |
|---|---|
| 端点 | `https://api.typesafe.ai`（`.env` 的 `JEV_BASE_URL`） |
| 调用 | `POST {base}/v1/systemone`（**不是** `/v1/chat/completions`，那个路径 404） |
| 认证 | `Authorization: Bearer {TYPESAFE_API_KEY}`（实测通过） |
| 请求体 | `{"model":"jev-1.14.0","state":"<状态摘要>", "questions":{"<id>":{...}}}` |
| 响应 | `{"model":"...","answers":{"<id>":{...}},"usage":{"input_tokens":N,"output_tokens":M}}` |

### 2.1 三种问题类型（全部实测 200）

| type | criteria | 响应字段 | 实测示例 |
|---|---|---|---|
| `choice` | **必填**，`dict[str,str]`（选项→说明） | `choice`、`confidence`、`probabilities{选项:概率}` | `{"type":"choice","choice":"高风险","confidence":0.68,"probabilities":{"高风险":0.84,"低风险":0.16}}` |
| `score` | **必填**，`list[str]`（图例） | `score`、`confidence`、`legend{序号:标签}`、`probabilities{序号:概率}` | `{"type":"score","score":1.76,"confidence":0.62,"legend":{"0":"低","1":"中","2":"高"},"probabilities":{"0":0.01,"1":0.23,"2":0.76}}` |
| `noul` | 可省略 | `noul`（标量） | `{"type":"noul","noul":0.66}` |

### 2.2 错误形态（用于错误文案）

| 状态码 | 响应 | 含义 |
|---|---|---|
| 400 | `{"detail":{"error_type":"api_usage_error","message":"Invalid request."}}` | 请求体结构不合法（类型名错等） |
| 422 | `{"detail":[{"loc":["body","questions","q1","choice","criteria"],"msg":"Input should be a valid dictionary"}]}` | **字段形状错**（criteria 类型/缺失）——可据此生成可执行的中文错误文案 |
| 401 | —— | 密钥无效 |

### 2.3 定位（与设计一致）

JEV 是**裁判**，不是生成者：只做 choice / score / noul 三类结构化判断。角色分析文本、结论撰写、情绪打分属生成侧，需 DeepSeek。**这正好符合零 Mock 严格模式**：裁判可用时用裁判，生成侧不可用时显式失败——不拿裁判冒充生成。

## 3. `.env` 的 CRLF 陷阱（已实测踩中）

`.env` 为 **CRLF 行尾**。在 Unix 下 `source .env` 会把 `\r` 带进变量值，导致 URL 变成 `https://api.deepseek.com\r` → curl 报 `URL malformatted`（exit 3），看起来像"网络不通"。

**实现要求**：密钥/配置加载器必须对每个值做 `trim()`（去 `\r\n` 与空白），并对解析后的 base_url 做合法性校验；错误文案要能区分"URL 格式非法"与"网络不可达"。

## 4. 代理

本机出网需走 `http://127.0.0.1:7897`（`HTTPS_PROXY`/`HTTP_PROXY`/`ALL_PROXY=socks5://127.0.0.1:7897`）。

**实测修正（2026-11-27）**：Dart `Dio` **会**读 `HTTPS_PROXY` 等环境变量——带代理环境变量跑
`flutter test test/jev_judge_live_test.dart` 时，JEV 真实返回
`choice=高风险 confidence=1.0 probabilities={高风险:1.0, 低风险:0.0}`，链路打通。

但这不能作为发布依赖：普通用户从桌面图标启动时环境里没有这些变量。**因此仍须**：
- `configs/app.json` 提供 `network.proxy`（scheme/host/port），三语言统一读取；
- 无配置时直连；
- 错误文案要区分"代理不可达"与"密钥无效"（两者都表现为连接失败/401）。
