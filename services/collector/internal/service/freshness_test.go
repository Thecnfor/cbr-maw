package service

import (
	"os"
	"path/filepath"
	"testing"
	"time"

	"cbr-maw/services/collector/internal/inbox"
)

// TestTradingDaysSince 工作日近似：不扣节假日。
func TestTradingDaysSince(t *testing.T) {
	from := time.Date(2024, 8, 16, 0, 0, 0, 0, time.UTC) // 周五
	cases := map[string]int{
		"2024-08-16": 0,
		"2024-08-17": 0, // 周六
		"2024-08-19": 1, // 周一
		"2024-08-23": 5,
	}
	for day, want := range cases {
		to, _ := time.Parse("2006-01-02", day)
		if got := tradingDaysSince(from, to); got != want {
			t.Errorf("%s: got %d, want %d", day, got, want)
		}
	}
}

// TestClassifyFreshness 三档边界：≤30 fresh、31..60 stale、>60 dead。
func TestClassifyFreshness(t *testing.T) {
	now := time.Date(2026, 11, 27, 0, 0, 0, 0, time.UTC)
	cases := map[string]string{
		"2026-10-27": freshnessFresh, // 2026-10-28 起算 ~22 个工作日
		"2025-09-30": freshnessDead,  // 远超过 60
		"2024-08-16": freshnessDead,
	}
	for day, want := range cases {
		latest, _ := time.Parse("2006-01-02", day)
		if got := classifyFreshness(&latest, now); got != want {
			t.Errorf("%s: got %s, want %s", day, got, want)
		}
	}
	if got := classifyFreshness(nil, now); got != freshnessUnknown {
		t.Errorf("nil: got %s, want unknown", got)
	}
}

// TestWorstFreshness 多依赖取最差：unknown > dead > stale > fresh。
func TestWorstFreshness(t *testing.T) {
	chain := []string{freshnessFresh, freshnessStale, freshnessDead, freshnessUnknown}
	for i := 0; i < len(chain); i++ {
		for j := 0; j < len(chain); j++ {
			want := chain[i]
			if j > i {
				want = chain[j]
			}
			if got := worstFreshness(chain[i], chain[j]); got != want {
				t.Errorf("worst(%s,%s) = %s, want %s", chain[i], chain[j], got, want)
			}
		}
	}
}

func realDailySeriesPath(t *testing.T) string {
	t.Helper()
	custom := os.Getenv("CBR_REAL_CUSTOM_DIR")
	if custom == "" {
		custom = "/mnt/shared/recently/commorcial/data/custom"
	}
	path := filepath.Join(custom, "daily_series.csv")
	if _, err := os.Stat(path); err != nil {
		t.Skip("真实样本不存在，跳过（设 CBR_REAL_CUSTOM_DIR 指定目录）")
	}
	return path
}

// TestFreshnessAgainstRealPanel 用真实 daily_series 建 panel，
// 断言 docs/23 §5 锁定的最新可用日期与 docs/18 §7.3 的 NaN 率口径。
func TestFreshnessAgainstRealPanel(t *testing.T) {
	path := realDailySeriesPath(t)
	dir := t.TempDir()
	opts := inbox.Options{
		IntermediateDir: filepath.Join(dir, "intermediate"),
		RejectedDir:     filepath.Join(dir, "rejected"),
		Now:             time.Date(2026, 11, 27, 9, 0, 0, 0, time.FixedZone("+08:00", 8*3600)),
	}
	if _, err := inbox.Ingest(path, opts); err != nil {
		t.Fatal(err)
	}
	p := scanPanel(filepath.Join(dir, "intermediate"))
	if len(p.series) != 22 {
		t.Fatalf("panel series = %d, want 22", len(p.series))
	}
	now := time.Date(2026, 11, 27, 0, 0, 0, 0, time.UTC)

	cases := []struct {
		sid       string
		latest    string
		nanRate   float64
		freshness string
	}{
		{"crossborder.flows.northbound_net", "2024-08-16", 0.1930, freshnessDead},
		{"crossborder.flows.southbound_net", "2025-09-30", 0.0989, freshnessDead},
		{"rates.credit.aa_spread", "2025-09-30", 0.0989, freshnessDead},
		{"market.cn_bond.repo_7d", "2025-09-30", 0.0989, freshnessDead},
		{"market.fx.usdcny", "2025-09-30", 0.0989, freshnessDead},
		{"market.global.vix", "2026-10-27", 0.0034, freshnessFresh},
		{"market.global.sp500", "2026-10-27", 0.0059, freshnessFresh},
		{"market.cn_equity.csi300", "2026-10-28", 0.0107, freshnessFresh},
	}
	for _, c := range cases {
		ps := p.series[c.sid]
		if ps == nil {
			t.Errorf("%s 不在 panel 内", c.sid)
			continue
		}
		if ps.last != c.latest {
			t.Errorf("%s latest = %s, want %s", c.sid, ps.last, c.latest)
		}
		rate := p.nanRate(c.sid)
		if rate == nil || !almostEqual(*rate, c.nanRate, 1e-4) {
			t.Errorf("%s nan_rate = %v, want %.4f", c.sid, rate, c.nanRate)
		}
		latest, _ := time.Parse("2006-01-02", ps.last)
		if got := classifyFreshness(&latest, now); got != c.freshness {
			t.Errorf("%s freshness = %s, want %s", c.sid, got, c.freshness)
		}
	}
}

func almostEqual(a, b, tol float64) bool {
	d := a - b
	if d < 0 {
		d = -d
	}
	return d <= tol
}

// TestSourcesHealthFreshnessEndToEnd 走真实 JSON-RPC handler：
// 真实 daily_series 落 intermediate → sources.health 报出每源依赖序列的新鲜度。
func TestSourcesHealthFreshnessEndToEnd(t *testing.T) {
	path := realDailySeriesPath(t)
	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{
		{"id": "northbound", "kind": "http_json", "enabled": true,
			"series": []string{"crossborder.flows.northbound_net"}, "params": map[string]any{"url": "http://x"}},
		{"id": "vix_src", "kind": "http_csv", "enabled": true,
			"series": []string{"market.global.vix"}, "params": map[string]any{"url": "http://x"}},
	})
	h.init()
	opts := inbox.Options{
		IntermediateDir: filepath.Join(h.dataDir, "data-home", "intermediate"),
		Now:             time.Date(2026, 11, 27, 9, 0, 0, 0, time.FixedZone("+08:00", 8*3600)),
	}
	if _, err := inbox.Ingest(path, opts); err != nil {
		t.Fatal(err)
	}
	res, rpcErr := h.call("sources.health", map[string]any{})
	if rpcErr != nil {
		t.Fatalf("%+v", rpcErr)
	}
	byID := map[string]map[string]any{}
	for _, raw := range res.(map[string]any)["entries"].([]any) {
		e := raw.(map[string]any)
		byID[e["source_id"].(string)] = e
	}

	nb := byID["northbound"]
	if nb["freshness"] != freshnessDead {
		t.Errorf("northbound freshness = %v, want dead", nb["freshness"])
	}
	deps := nb["dependencies"].([]any)
	if len(deps) != 1 {
		t.Fatalf("northbound dependencies = %d", len(deps))
	}
	dep := deps[0].(map[string]any)
	if dep["latest_available"] != "2024-08-16" {
		t.Errorf("northbound latest = %v", dep["latest_available"])
	}
	if !almostEqual(dep["nan_rate"].(float64), 0.1930, 1e-4) {
		t.Errorf("northbound nan_rate = %v", dep["nan_rate"])
	}

	vix := byID["vix_src"]
	if vix["freshness"] != freshnessFresh {
		t.Errorf("vix freshness = %v, want fresh", vix["freshness"])
	}
}
