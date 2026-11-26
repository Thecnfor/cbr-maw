package inbox

// 真实样本回归测试：直接吃旧项目重建出来的真实 CSV，不造假数据。
// 数据不存在时跳过（data/custom 不入库）。

import (
	"archive/zip"
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// realCustomDir 是真实样本目录；可由 CBR_REAL_CUSTOM_DIR 覆盖。
func realCustomDir(t *testing.T) string {
	t.Helper()
	dir := os.Getenv("CBR_REAL_CUSTOM_DIR")
	if dir == "" {
		dir = "/mnt/shared/recently/commorcial/data/custom"
	}
	if _, err := os.Stat(filepath.Join(dir, "daily_series.csv")); err != nil {
		t.Skip("真实样本不存在，跳过（设 CBR_REAL_CUSTOM_DIR 指定目录）")
	}
	return dir
}

func newRealOpts(t *testing.T) Options {
	t.Helper()
	dir := t.TempDir()
	return Options{
		IntermediateDir: filepath.Join(dir, "intermediate"),
		RejectedDir:     filepath.Join(dir, "rejected"),
		Now:             time.Date(2026, 11, 27, 9, 0, 0, 0, time.FixedZone("+08:00", 8*3600)),
	}
}

// TestRealDailySeries 22 条真实序列全部 accepted、行数逐列对得上、
// release_time 沿用文件列而不是推导。
func TestRealDailySeries(t *testing.T) {
	custom := realCustomDir(t)
	opts := newRealOpts(t)
	result, err := Ingest(filepath.Join(custom, "daily_series.csv"), opts)
	if err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	if len(result.Rejected) != 0 {
		t.Fatalf("不应有拒绝: %+v", result.Rejected)
	}
	if len(result.Accepted) != 22 {
		t.Fatalf("accepted = %d, want 22", len(result.Accepted))
	}
	// 真实有效行数（非空单元格），不是文件行数。
	want := map[string]int{
		"crossborder.flows.ah_premium":         2886,
		"crossborder.flows.northbound_net":     2342,
		"crossborder.flows.southbound_net":     2615,
		"crossborder.holdings.northbound_hold": 2342,
		"crossborder.holdings.southbound_hold": 2615,
		"market.cn_bond.cgb_10y":               2877,
		"market.cn_bond.cgb_2y":                2877,
		"market.cn_bond.cgb_index":             2877,
		"market.cn_bond.repo_7d":               2615,
		"market.cn_bond.term_spread":           2877,
		"market.cn_equity.csi300":              2871,
		"market.cn_equity.csi500":              2871,
		"market.cn_equity.turnover":            2615,
		"market.fx.cnh_cny_gap":                2615,
		"market.fx.usdcnh":                     2615,
		"market.fx.usdcny":                     2615,
		"market.global.cn_us_spread":           2861,
		"market.global.dxy":                    2615,
		"market.global.sp500":                  2885,
		"market.global.us10y":                  2883,
		"market.global.vix":                    2892,
		"rates.credit.aa_spread":               2615,
	}
	got := map[string]int{}
	for _, a := range result.Accepted {
		got[a.SeriesID] = a.Rows
	}
	for sid, n := range want {
		if got[sid] != n {
			t.Errorf("%s rows = %d, want %d", sid, got[sid], n)
		}
	}

	// release_time 沿用文件列：境内 18:00、海外也按文件写的 18:00，而不是推导成次日 09:00。
	vix := readNDJSON(t, filepath.Join(opts.IntermediateDir, "market.global.vix.ndjson"))
	if rt := vix[0]["release_time"].(string); rt != "2015-01-05T18:00:00+08:00" {
		t.Fatalf("vix release_time = %s，文件列未被沿用", rt)
	}
	if vix[0]["obs_date"].(string) != "2015-01-05" {
		t.Fatalf("vix obs_date = %v", vix[0]["obs_date"])
	}
}

// TestRealNorthboundTailNotFilled 北向 2024-08-16 之后没有观测，不得被补 0 或补值。
func TestRealNorthboundTailNotFilled(t *testing.T) {
	custom := realCustomDir(t)
	opts := newRealOpts(t)
	if _, err := Ingest(filepath.Join(custom, "daily_series.csv"), opts); err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	records := readNDJSON(t, filepath.Join(opts.IntermediateDir, "crossborder.flows.northbound_net.ndjson"))
	if len(records) != 2342 {
		t.Fatalf("rows = %d, want 2342", len(records))
	}
	last := records[len(records)-1]
	if last["obs_date"].(string) != "2024-08-16" {
		t.Fatalf("最后一行 = %s, want 2024-08-16", last["obs_date"])
	}
	for _, rec := range records {
		if rec["obs_date"].(string) > "2024-08-16" {
			t.Fatalf("出现停更后的伪造行: %v", rec)
		}
		if v, _ := rec["value"].(float64); v == 0 && rec["obs_date"].(string) > "2024-08-16" {
			t.Fatalf("停更后出现 0 填充: %v", rec)
		}
	}
}

// TestRealMonthlySeries 月频 5 条序列全部识别，缺失行不补 0。
func TestRealMonthlySeries(t *testing.T) {
	custom := realCustomDir(t)
	opts := newRealOpts(t)
	result, err := Ingest(filepath.Join(custom, "monthly_series.csv"), opts)
	if err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	want := map[string]int{
		"macro.cpi.yoy":              56,
		"macro.fx_reserves":          129,
		"macro.lpr.1y":               19,
		"macro.pmi.manufacturing":    128,
		"macro.social_financing.yoy": 105,
	}
	if len(result.Accepted) != len(want) {
		t.Fatalf("accepted = %d, want %d", len(result.Accepted), len(want))
	}
	for _, a := range result.Accepted {
		if want[a.SeriesID] != a.Rows {
			t.Errorf("%s rows = %d, want %d", a.SeriesID, a.Rows, want[a.SeriesID])
		}
	}
}

// TestRealPolicyNewsCorpus 9798 篇真实文本被识别为语料形态。
func TestRealPolicyNewsCorpus(t *testing.T) {
	custom := realCustomDir(t)
	opts := newRealOpts(t)
	result, err := Ingest(filepath.Join(custom, "policy_news.csv"), opts)
	if err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	if len(result.Accepted) != 1 {
		t.Fatalf("accepted = %d, want 1", len(result.Accepted))
	}
	acc := result.Accepted[0]
	if !strings.HasPrefix(acc.SeriesID, "documents.") {
		t.Fatalf("语料未被识别: %s", acc.SeriesID)
	}
	if acc.Rows != 9798 {
		t.Fatalf("rows = %d, want 9798", acc.Rows)
	}
	docs := readNDJSON(t, filepath.Join(opts.IntermediateDir, strings.TrimPrefix(acc.SeriesID, "documents.")+".documents.ndjson"))
	if len(docs) != 9798 {
		t.Fatalf("NDJSON docs = %d", len(docs))
	}
	first := docs[0]
	if first["publish_time"].(string) != "2017-01-10T00:00:00+08:00" {
		t.Fatalf("publish_time = %v，应沿用文件列并标 +08:00", first["publish_time"])
	}
	if first["doc_id"].(string) == "" || first["hash"].(string) == "" {
		t.Fatalf("doc_id/hash 缺失: %v", first)
	}
}

// TestRealZipRecursive 把真实 daily/monthly 两个 CSV 打成 zip，验证递归展开。
func TestRealZipRecursive(t *testing.T) {
	custom := realCustomDir(t)
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, name := range []string{"daily_series.csv", "monthly_series.csv"} {
		data, err := os.ReadFile(filepath.Join(custom, name))
		if err != nil {
			t.Fatal(err)
		}
		w, err := zw.Create("真实数据/" + name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := w.Write(data); err != nil {
			t.Fatal(err)
		}
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "real.zip")
	if err := os.WriteFile(path, buf.Bytes(), 0o644); err != nil {
		t.Fatal(err)
	}
	opts := newRealOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	if len(result.Rejected) != 0 {
		t.Fatalf("不应有拒绝: %+v", result.Rejected)
	}
	if len(result.Accepted) != 27 {
		t.Fatalf("accepted = %d, want 27（22 日频 + 5 月频）", len(result.Accepted))
	}
}
