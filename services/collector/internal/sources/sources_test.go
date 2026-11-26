package sources

import (
	"os"
	"path/filepath"
	"testing"
)

const minimalJSON = `{
  "version": 1,
  "user_agent": "cbr-test/1.0",
  "defaults": {"timeout_seconds": 5, "retries": 1, "min_interval_seconds": 0},
  "sources": [
    {"id":"em_csi300","kind":"http_json","enabled":true,"series":["market.cn_equity.csi300"],
     "release_lag_days":0,"publish_hour":18,"publish_minute":0,"tz_offset":"+08:00",
     "params":{"url":"https://example.com/a"}},
    {"id":"tencent_csi300","kind":"http_json","enabled":true,"backup_for":"em_csi300",
     "series":["market.cn_equity.csi300"],"params":{"url":"https://example.com/b"}},
    {"id":"disabled","kind":"http_csv","enabled":false,"series":["market.global.vix"],
     "params":{"url":"https://example.com/c"}}
  ]
}`

func writeJSON(t *testing.T, dir, body string) string {
	t.Helper()
	cfg := filepath.Join(dir, "configs")
	if err := os.MkdirAll(cfg, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(cfg, "sources.json")
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestLoadJSONAndDefaults(t *testing.T) {
	dir := t.TempDir()
	writeJSON(t, dir, minimalJSON)
	ledger, err := Load(dir, "", "")
	if err != nil {
		t.Fatal(err)
	}
	if len(ledger.Sources) != 3 {
		t.Fatalf("sources = %d", len(ledger.Sources))
	}
	src, ok := ledger.Get("em_csi300")
	if !ok || src.TZOffset != "+08:00" || src.PublishHour == nil || *src.PublishHour != 18 {
		t.Fatalf("PIT 字段缺失: %+v", src)
	}
	// 缺省字段补全。
	if src.Tier != "t1Public" || src.AuthStatus != "notRequired" {
		t.Fatalf("默认台账字段未补齐: %+v", src)
	}
}

func TestListIncludeDisabled(t *testing.T) {
	dir := t.TempDir()
	writeJSON(t, dir, minimalJSON)
	ledger, err := Load(dir, "", "")
	if err != nil {
		t.Fatal(err)
	}
	if got := len(ledger.List(false)); got != 2 {
		t.Fatalf("默认应排除停用源，实际 %d", got)
	}
	if got := len(ledger.List(true)); got != 3 {
		t.Fatalf("include_disabled 应为 3，实际 %d", got)
	}
}

func TestBackups(t *testing.T) {
	dir := t.TempDir()
	writeJSON(t, dir, minimalJSON)
	ledger, _ := Load(dir, "", "")
	backups := ledger.Backups("em_csi300")
	if len(backups) != 1 || backups[0].ID != "tencent_csi300" {
		t.Fatalf("备源解析错误: %+v", backups)
	}
	if len(ledger.SeriesSources("market.cn_equity.csi300")) != 2 {
		t.Fatal("序列来源应含主源+备源")
	}
}

func TestAkshareAdapter(t *testing.T) {
	body := `{"sources":[{"id":"akshare_cgb_10y","kind":"akshare","enabled":true,
	  "series":["market.cn_bond.cgb_10y"],
	  "params":{"func":"bond_zh_us_yield_em","value_column":"中国国债收益率10年"}}]}`
	dir := t.TempDir()
	writeJSON(t, dir, body)
	ledger, err := Load(dir, "", "")
	if err != nil {
		t.Fatal(err)
	}
	src, _ := ledger.Get("akshare_cgb_10y")
	if src.Kind != "http_json" {
		t.Fatalf("akshare 应被适配为 http_json，实际 %s", src.Kind)
	}
	if src.Params["value_field"] != "EMM00166466" {
		t.Fatalf("列映射错误: %v", src.Params["value_field"])
	}
}

func TestUnknownKindRejected(t *testing.T) {
	body := `{"sources":[{"id":"x","kind":"magic","enabled":true,"params":{"url":"http://x"}}]}`
	dir := t.TempDir()
	writeJSON(t, dir, body)
	if _, err := Load(dir, "", ""); err == nil {
		t.Fatal("未知 kind 应加载失败")
	}
}

func TestDataHomeOverridesResourceHome(t *testing.T) {
	dataHome := t.TempDir()
	resourceHome := t.TempDir()
	writeJSON(t, resourceHome, `{"sources":[{"id":"r","kind":"http_json","enabled":true,"params":{"url":"http://r"}}]}`)
	writeJSON(t, dataHome, `{"sources":[{"id":"d","kind":"http_json","enabled":true,"params":{"url":"http://d"}}]}`)
	ledger, err := Load(dataHome, resourceHome, "")
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := ledger.Get("d"); !ok {
		t.Fatal("data_home 应覆盖 resource_home")
	}
}

func TestMissingLedger(t *testing.T) {
	if _, err := Load(t.TempDir(), "", ""); err == nil {
		t.Fatal("台账缺失应报错")
	}
}
