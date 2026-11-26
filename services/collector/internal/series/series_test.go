package series

import "testing"

// TestMappingPriorityUS10YOverCGB10Y 是本模块最关键的回归：
// 「美国国债收益率10年」必须映射到 us10y，而不是被「国债10年」抢走。
func TestMappingPriorityUS10YOverCGB10Y(t *testing.T) {
	cases := []struct {
		raw  string
		want string
	}{
		{"美国国债收益率10年", "market.global.us10y"},
		// 目录无 us2y 序列：不猜测，落 custom.*（宁可显式未知，也不张冠李戴）
		{"美国国债收益率2年", "custom.col.美国国债收益率2年"},
		{"US10Y", "market.global.us10y"},
		{"美债10年", "market.global.us10y"},
		{"中国国债收益率10年", "market.cn_bond.cgb_10y"},
		{"国债10年", "market.cn_bond.cgb_10y"},
		{"cgb_10y", "market.cn_bond.cgb_10y"},
		{"中国国债收益率2年", "market.cn_bond.cgb_2y"},
		{"cnh_cny_gap", "market.fx.cnh_cny_gap"},
		{"usdcnh", "market.fx.usdcnh"},
		{"usdcny", "market.fx.usdcny"},
		{"沪深300", "market.cn_equity.csi300"},
		{"VIX", "market.global.vix"},
		{"标普500", "market.global.sp500"},
	}
	for _, c := range cases {
		got, _ := ResolveColumn(c.raw, "", nil)
		if got != c.want {
			t.Fatalf("ResolveColumn(%q) = %q, want %q", c.raw, got, c.want)
		}
	}
}

func TestResolveColumnFallsBackToCustom(t *testing.T) {
	got, basis := ResolveColumn("my_private_metric", "mystery_file", nil)
	if got != "custom.mystery_file.my_private_metric" {
		t.Fatalf("got %q, want custom.*", got)
	}
	if basis != "custom" {
		t.Fatalf("basis = %q, want custom", basis)
	}
}

func TestResolveColumnOverride(t *testing.T) {
	overrides := map[string]string{"my_col": "market.global.vix"}
	got, basis := ResolveColumn("my_col", "", overrides)
	if got != "market.global.vix" || basis != "override" {
		t.Fatalf("got %q/%q, want override", got, basis)
	}
}

func TestCanonicalAliases(t *testing.T) {
	if Canonical("market.fx.cnh") != "market.fx.usdcnh" {
		t.Fatal("别名未归一化")
	}
	if !Exists("market.global.us10y") {
		t.Fatal("us10y 应存在")
	}
	if Unit("market.cn_bond.cgb_10y") != "%" {
		t.Fatal("单位口径错误")
	}
}

// TestMappingRuleTableIsStable 保证规则表可查且顺序稳定（海外因子在前）。
func TestMappingRuleTableIsStable(t *testing.T) {
	rules := MappingRules()
	if len(rules) == 0 {
		t.Fatal("规则表为空")
	}
	if rules[0].SeriesID != "market.global.us10y" {
		t.Fatalf("首条规则应为 us10y，实际 %s", rules[0].SeriesID)
	}
}
