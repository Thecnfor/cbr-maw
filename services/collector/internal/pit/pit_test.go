package pit

import (
	"testing"
	"time"
)

func mustDate(t *testing.T, s string) time.Time {
	t.Helper()
	d, err := time.Parse("2006-01-02", s)
	if err != nil {
		t.Fatalf("bad date %s: %v", s, err)
	}
	return d
}

// TestDomesticReleaseTime 境内日频：观测日当日 18:00 (+08:00)。
func TestDomesticReleaseTime(t *testing.T) {
	rule := DefaultRule("market.cn_equity.csi300")
	got, err := rule.ReleaseTime(mustDate(t, "2026-11-02"))
	if err != nil {
		t.Fatal(err)
	}
	want := "2026-11-02T18:00:00+08:00"
	if s := got.Format(time.RFC3339); s != want {
		t.Fatalf("got %s, want %s", s, want)
	}
	if rule.LagDays != 0 || rule.Hour != 18 {
		t.Fatalf("境内规则错误: %+v", rule)
	}
}

// TestOverseasReleaseTime 隔夜海外：观测日次日 09:00 (+08:00)。
func TestOverseasReleaseTime(t *testing.T) {
	for _, sid := range []string{"market.global.vix", "market.global.sp500", "market.global.us10y"} {
		rule := DefaultRule(sid)
		if rule.LagDays != 1 || rule.Hour != 9 {
			t.Fatalf("%s 海外规则错误: %+v", sid, rule)
		}
		got, err := rule.ReleaseTime(mustDate(t, "2026-11-02"))
		if err != nil {
			t.Fatal(err)
		}
		want := "2026-11-03T09:00:00+08:00"
		if s := got.Format(time.RFC3339); s != want {
			t.Fatalf("%s got %s, want %s", sid, s, want)
		}
	}
}

// TestMonthlyReleaseTime 月频：按发布日（至少 lag 天）+ 10:00。
func TestMonthlyReleaseTime(t *testing.T) {
	rule := DefaultRule("macro.cpi.yoy")
	if rule.LagDays != 10 || rule.Hour != 10 {
		t.Fatalf("月频规则错误: %+v", rule)
	}
	got, err := rule.ReleaseTime(mustDate(t, "2026-10-01"))
	if err != nil {
		t.Fatal(err)
	}
	if s := got.Format(time.RFC3339); s != "2026-10-11T10:00:00+08:00" {
		t.Fatalf("got %s", s)
	}
}

func TestRuleFromParamsOverride(t *testing.T) {
	lag, hour, minute := 2, 7, 30
	rule := RuleFromParams("market.global.vix", &lag, &hour, &minute, "+08:00")
	got, err := rule.ReleaseTime(mustDate(t, "2026-11-02"))
	if err != nil {
		t.Fatal(err)
	}
	if s := got.Format(time.RFC3339); s != "2026-11-04T07:30:00+08:00" {
		t.Fatalf("got %s", s)
	}
}

// TestReleaseRuleIsTraceable release_time_rule 必须写明依据（可查）。
func TestReleaseRuleIsTraceable(t *testing.T) {
	rule := DefaultRule("market.global.sp500")
	desc := rule.Describe()
	if desc == "" {
		t.Fatal("release_time_rule 为空")
	}
	for _, want := range []string{"obs_date", "09:00", "+08:00"} {
		if !contains(desc, want) {
			t.Fatalf("rule 描述缺少 %q: %s", want, desc)
		}
	}
}

func contains(s, sub string) bool {
	return len(s) >= len(sub) && (s == sub || indexOf(s, sub) >= 0)
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
