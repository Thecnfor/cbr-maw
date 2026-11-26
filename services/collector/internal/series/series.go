// Package series 承载规范序列目录（口径真源）与「列名 → 序列 ID」映射规则。
//
// 目录字段与旧版 commorcial/src/cbr/data/catalog.py 的 SERIES_SPECS 逐条对齐：
// 序列 ID、单位、频率、发布时滞（release_lag_days）是 PIT 推导的输入，不可随意改。
package series

import "strings"

// Spec 是单条规范序列的口径元数据。
type Spec struct {
	ID             string
	Name           string
	Unit           string
	Frequency      string
	ReleaseLagDays int
	Derived        bool
}

// DailySeriesIDs 全部日频序列（有序）。
var DailySeriesIDs = []string{
	"market.cn_equity.csi300",
	"market.cn_equity.csi500",
	"market.cn_equity.turnover",
	"market.cn_bond.cgb_2y",
	"market.cn_bond.cgb_10y",
	"market.cn_bond.repo_7d",
	"market.cn_bond.term_spread",
	"market.cn_bond.cgb_index",
	"rates.credit.aa_spread",
	"market.fx.usdcny",
	"market.fx.usdcnh",
	"market.fx.cnh_cny_gap",
	"market.global.dxy",
	"market.global.vix",
	"market.global.sp500",
	"market.global.us10y",
	"market.global.cn_us_spread",
	"crossborder.flows.northbound_net",
	"crossborder.flows.southbound_net",
	"crossborder.holdings.northbound_hold",
	"crossborder.holdings.southbound_hold",
	"crossborder.flows.ah_premium",
}

// MonthlySeriesIDs 全部月频序列（有序）。
var MonthlySeriesIDs = []string{
	"macro.pmi.manufacturing",
	"macro.cpi.yoy",
	"macro.social_financing.yoy",
	"macro.fx_reserves",
	"macro.lpr.1y",
}

// Specs 是规范序列目录（27 条）。
var Specs = map[string]Spec{
	"market.cn_equity.csi300":              {ID: "market.cn_equity.csi300", Name: "沪深300指数", Unit: "点", Frequency: "daily"},
	"market.cn_equity.csi500":              {ID: "market.cn_equity.csi500", Name: "中证500指数", Unit: "点", Frequency: "daily"},
	"market.cn_equity.turnover":            {ID: "market.cn_equity.turnover", Name: "沪深两市成交额", Unit: "亿元", Frequency: "daily"},
	"market.cn_bond.cgb_2y":                {ID: "market.cn_bond.cgb_2y", Name: "2年期国债到期收益率", Unit: "%", Frequency: "daily"},
	"market.cn_bond.cgb_10y":               {ID: "market.cn_bond.cgb_10y", Name: "10年期国债到期收益率", Unit: "%", Frequency: "daily"},
	"market.cn_bond.repo_7d":               {ID: "market.cn_bond.repo_7d", Name: "银行间7天质押式回购利率", Unit: "%", Frequency: "daily"},
	"market.cn_bond.term_spread":           {ID: "market.cn_bond.term_spread", Name: "10Y-2Y国债期限利差", Unit: "bp", Frequency: "daily", Derived: true},
	"market.cn_bond.cgb_index":             {ID: "market.cn_bond.cgb_index", Name: "中债国债全价指数", Unit: "点", Frequency: "daily", Derived: true},
	"rates.credit.aa_spread":               {ID: "rates.credit.aa_spread", Name: "AA级中票信用利差", Unit: "bp", Frequency: "daily"},
	"market.fx.usdcny":                     {ID: "market.fx.usdcny", Name: "美元兑人民币在岸即期汇率", Unit: "CNY/USD", Frequency: "daily"},
	"market.fx.usdcnh":                     {ID: "market.fx.usdcnh", Name: "美元兑离岸人民币即期汇率", Unit: "CNH/USD", Frequency: "daily"},
	"market.fx.cnh_cny_gap":                {ID: "market.fx.cnh_cny_gap", Name: "离岸-在岸人民币汇差", Unit: "pips", Frequency: "daily", Derived: true},
	"market.global.dxy":                    {ID: "market.global.dxy", Name: "美元指数", Unit: "点", Frequency: "daily"},
	"market.global.vix":                    {ID: "market.global.vix", Name: "VIX恐慌指数", Unit: "点", Frequency: "daily"},
	"market.global.sp500":                  {ID: "market.global.sp500", Name: "标普500指数", Unit: "点", Frequency: "daily"},
	"market.global.us10y":                  {ID: "market.global.us10y", Name: "美国10年期国债收益率", Unit: "%", Frequency: "daily"},
	"market.global.cn_us_spread":           {ID: "market.global.cn_us_spread", Name: "中美10年期国债利差", Unit: "bp", Frequency: "daily", Derived: true},
	"crossborder.flows.northbound_net":     {ID: "crossborder.flows.northbound_net", Name: "北向资金净流入", Unit: "亿元", Frequency: "daily"},
	"crossborder.flows.southbound_net":     {ID: "crossborder.flows.southbound_net", Name: "南向资金净流入", Unit: "亿元", Frequency: "daily"},
	"crossborder.holdings.northbound_hold": {ID: "crossborder.holdings.northbound_hold", Name: "北向持股总市值", Unit: "亿元", Frequency: "daily"},
	"crossborder.holdings.southbound_hold": {ID: "crossborder.holdings.southbound_hold", Name: "南向持股总市值", Unit: "亿元", Frequency: "daily"},
	"crossborder.flows.ah_premium":         {ID: "crossborder.flows.ah_premium", Name: "AH股溢价指数", Unit: "点", Frequency: "daily"},
	"macro.pmi.manufacturing":              {ID: "macro.pmi.manufacturing", Name: "制造业PMI", Unit: "点", Frequency: "monthly", ReleaseLagDays: 1},
	"macro.cpi.yoy":                        {ID: "macro.cpi.yoy", Name: "CPI同比", Unit: "%", Frequency: "monthly", ReleaseLagDays: 10},
	"macro.social_financing.yoy":           {ID: "macro.social_financing.yoy", Name: "社融存量同比", Unit: "%", Frequency: "monthly", ReleaseLagDays: 12},
	"macro.fx_reserves":                    {ID: "macro.fx_reserves", Name: "外汇储备", Unit: "亿美元", Frequency: "monthly", ReleaseLagDays: 7},
	"macro.lpr.1y":                         {ID: "macro.lpr.1y", Name: "1年期贷款市场报价利率(LPR)", Unit: "%", Frequency: "monthly"},
}

// overseasSeries 是「隔夜海外因子」集合：观测日次日 09:00 (+08:00) 才可得。
var overseasSeries = map[string]bool{
	"market.global.vix":   true,
	"market.global.sp500": true,
	"market.global.us10y": true,
	"market.global.dxy":   true,
}

// aliases 是旧名 → 规范 ID 的兼容表（对齐旧版 SERIES_ALIASES）。
var aliases = map[string]string{
	"market.global.us_equity":         "market.global.sp500",
	"market.global.equity":            "market.global.sp500",
	"market.cn_equity":                "market.cn_equity.csi300",
	"market.cn_bond":                  "market.cn_bond.cgb_index",
	"crossborder.northbound_net":      "crossborder.flows.northbound_net",
	"crossborder.southbound_net":      "crossborder.flows.southbound_net",
	"crossborder.ah_premium":          "crossborder.flows.ah_premium",
	"crossborder.holdings.northbound": "crossborder.holdings.northbound_hold",
	"crossborder.holdings.southbound": "crossborder.holdings.southbound_hold",
	"market.fx.cny":                   "market.fx.usdcny",
	"market.fx.cnh":                   "market.fx.usdcnh",
	"market.global.vix_level":         "market.global.vix",
	"market.global.dollar_index":      "market.global.dxy",
	"market.global.cn10y":             "market.cn_bond.cgb_10y",
	"market.global.us10y_yield":       "market.global.us10y",
	"rates.credit.credit_spread":      "rates.credit.aa_spread",
	"macro.pmi":                       "macro.pmi.manufacturing",
	"macro.cpi":                       "macro.cpi.yoy",
	"macro.fx_reserve":                "macro.fx_reserves",
}

// Canonical 把别名归一化为规范序列 ID；未知 ID 原样返回。
func Canonical(id string) string {
	if canon, ok := aliases[id]; ok {
		return canon
	}
	return id
}

// Exists 判断序列 ID 是否在目录内。
func Exists(id string) bool {
	_, ok := Specs[Canonical(id)]
	return ok
}

// Unit 返回序列单位；未知序列返回空串。
func Unit(id string) string {
	if spec, ok := Specs[Canonical(id)]; ok {
		return spec.Unit
	}
	return ""
}

// IsMonthly 判断序列是否月频。
func IsMonthly(id string) bool {
	spec, ok := Specs[Canonical(id)]
	return ok && spec.Frequency == "monthly"
}

// IsOverseas 判断序列是否隔夜海外因子（release_lag_days=1，次日 09:00 可得）。
func IsOverseas(id string) bool {
	return overseasSeries[Canonical(id)]
}

// ReleaseLagDays 返回目录声明的发布时滞天数；未知序列返回 0。
func ReleaseLagDays(id string) int {
	if spec, ok := Specs[Canonical(id)]; ok {
		return spec.ReleaseLagDays
	}
	return 0
}

// hint 是一条列名映射规则：命中任一关键词即指向该序列。
type hint struct {
	Keywords []string
	SeriesID string
}

// columnHints 是「列名/文件名 → 规范序列 ID」的映射规则表。
//
// 排序规则（与旧版 commorcial/src/cbr/ingest/inbox.py 的 _ORDERED_SERIES_HINTS 对齐）：
//  1. 海外因子优先——us10y 必须先于 cgb_10y 命中，否则「美国国债10年」会被
//     境内「国债10年」关键词抢走；
//  2. 同一序列内按关键词长度从长到短匹配，长关键词优先防误命中
//     （如「中国国债收益率10年」优先于「国债10年」）；
//  3. 未命中落 custom.*。
var columnHints = []hint{
	{[]string{"us10y", "us_10y", "美国国债10年", "美国10年", "美国国债收益率10年", "美债10年", "美债收益率10年", "tnx"}, "market.global.us10y"},
	{[]string{"usdcnh", "cnh", "离岸人民币"}, "market.fx.usdcnh"},
	{[]string{"usdcny", "cny", "在岸人民币", "美元兑人民币"}, "market.fx.usdcny"},
	{[]string{"cn_us_spread", "中美利差"}, "market.global.cn_us_spread"},
	{[]string{"cnh_cny_gap", "汇差", "离岸在岸差"}, "market.fx.cnh_cny_gap"},
	{[]string{"term_spread", "期限利差"}, "market.cn_bond.term_spread"},
	{[]string{"cgb_index", "国债指数", "中债指数"}, "market.cn_bond.cgb_index"},
	{[]string{"cgb_2y", "cgb2", "国债2年", "中国国债收益率2年", "中债2年"}, "market.cn_bond.cgb_2y"},
	{[]string{"cgb_10y", "cgb10", "国债10年", "中国国债收益率10年", "中债10年"}, "market.cn_bond.cgb_10y"},
	{[]string{"csi300", "hs300", "沪深300", "000300"}, "market.cn_equity.csi300"},
	{[]string{"csi500", "中证500", "000905"}, "market.cn_equity.csi500"},
	{[]string{"turnover", "成交额", "成交金额", "amount"}, "market.cn_equity.turnover"},
	{[]string{"repo_7d", "repo", "回购", "dr007", "r007", "资金利率"}, "market.cn_bond.repo_7d"},
	{[]string{"aa_spread", "credit_spread", "信用利差", "信用"}, "rates.credit.aa_spread"},
	{[]string{"dxy", "美元指数", "dollar"}, "market.global.dxy"},
	{[]string{"vix", "恐慌指数", "波动率指数"}, "market.global.vix"},
	{[]string{"sp500", "标普500", "标普", "spx", "gspc", "us.inx"}, "market.global.sp500"},
	{[]string{"northbound_hold", "北向持股", "北向持仓"}, "crossborder.holdings.northbound_hold"},
	{[]string{"southbound_hold", "南向持股", "南向持仓"}, "crossborder.holdings.southbound_hold"},
	{[]string{"northbound", "北向资金", "北向净", "北向"}, "crossborder.flows.northbound_net"},
	{[]string{"southbound", "南向资金", "南向净", "南向"}, "crossborder.flows.southbound_net"},
	{[]string{"ah_premium", "ah溢价", "ah股溢价"}, "crossborder.flows.ah_premium"},
	{[]string{"pmi", "制造业pmi"}, "macro.pmi.manufacturing"},
	{[]string{"cpi", "居民消费价格", "通胀"}, "macro.cpi.yoy"},
	{[]string{"social_financing", "社融"}, "macro.social_financing.yoy"},
	{[]string{"fx_reserves", "外汇储备", "外储"}, "macro.fx_reserves"},
	{[]string{"lpr", "贷款市场报价利率"}, "macro.lpr.1y"},
}

// MappingRule 是一条可查的映射规则说明（对外输出，便于审计与覆盖）。
type MappingRule struct {
	SeriesID string   `json:"series_id"`
	Keywords []string `json:"keywords"`
	Note     string   `json:"note"`
}

// MappingRules 返回全部映射规则（供设置页展示 / 覆盖）。
func MappingRules() []MappingRule {
	out := make([]MappingRule, 0, len(columnHints))
	for _, h := range columnHints {
		out = append(out, MappingRule{SeriesID: h.SeriesID, Keywords: h.Keywords})
	}
	return out
}

// SafeToken 把任意字符串规整为可用于序列 ID 的片段（小写 + 下划线）。
func SafeToken(text string) string {
	var b strings.Builder
	for _, r := range strings.ToLower(strings.TrimSpace(text)) {
		switch {
		case r >= 'a' && r <= 'z', r >= '0' && r <= '9', r == '_':
			b.WriteRune(r)
		case r >= '一' && r <= '鿿':
			b.WriteRune(r)
		default:
			b.WriteByte('_')
		}
	}
	out := strings.Trim(b.String(), "_")
	if out == "" {
		return "col"
	}
	return out
}

// ResolveColumn 把列名/文件名映射为规范序列 ID。
//
// 规则：
//   - 列名精确等于规范 ID 或其别名 → 直接采用；
//   - 列名按 columnHints 顺序匹配（海外因子优先、组内长关键词优先）；
//   - 列名未命中时退回文件名再匹配一次；
//   - 仍未命中 → custom.<file>.<col>。
//
// overrides 允许外部（设置页 / 配置文件）覆盖映射结果。
func ResolveColumn(raw, fileHint string, overrides map[string]string) (string, string) {
	raw = strings.TrimSpace(raw)
	if raw != "" {
		if canon := Canonical(raw); Exists(canon) {
			return canon, "exact"
		}
	}
	if overrides != nil {
		key := strings.ToLower(raw)
		if sid, ok := overrides[key]; ok && sid != "" {
			return sid, "override"
		}
	}
	if sid := matchColumn(raw); sid != "" {
		return sid, "column"
	}
	if sid := matchColumn(fileHint); sid != "" {
		return sid, "file"
	}
	return "custom." + SafeToken(fileHint) + "." + SafeToken(raw), "custom"
}

// matchColumn 在规则表内匹配一个名称，返回命中的序列 ID。
//
// 匹配采用「子串包含」语义（与旧版一致），但**全局取最长命中关键词**，
// 同长时才按规则表顺序（海外因子在前）决胜。这样：
//   - 「美国国债收益率10年」→ us10y（11 字），不会被「国债10年」抢走；
//   - 「cnh_cny_gap」→ cnh_cny_gap（11 字），不会被短词「cnh」误判为 usdcnh。
func matchColumn(name string) string {
	if name == "" {
		return ""
	}
	lowered := strings.ToLower(name)
	bestLen, bestSID := 0, ""
	for _, h := range columnHints {
		for _, kw := range h.Keywords {
			n := len([]rune(kw))
			if n > bestLen && strings.Contains(lowered, strings.ToLower(kw)) {
				bestLen, bestSID = n, h.SeriesID
			}
		}
	}
	return bestSID
}
