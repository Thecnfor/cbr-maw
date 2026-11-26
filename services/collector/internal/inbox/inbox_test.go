package inbox

import (
	"archive/zip"
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/xuri/excelize/v2"
)

func newOpts(t *testing.T) Options {
	t.Helper()
	dir := t.TempDir()
	return Options{
		IntermediateDir: filepath.Join(dir, "intermediate"),
		RejectedDir:     filepath.Join(dir, "rejected"),
		Now:             time.Date(2026, 11, 25, 9, 0, 0, 0, time.FixedZone("+08:00", 8*3600)),
	}
}

func writeFile(t *testing.T, dir, name string, data []byte) string {
	t.Helper()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// TestDirtyCSVCleaning 覆盖千分位、货币符号、占位符、尾部说明行、重复行。
func TestDirtyCSVCleaning(t *testing.T) {
	csvData := "日期,沪深300,备注\n" +
		"2026-11-01,\"4,000.50\",x\n" +
		"2026-11-02,\"¥4,010\",y\n" +
		"2026-11-03,-,z\n" + // 缺失值：必须被丢弃而不是补 0
		"2026-11-04,N/A,z\n" +
		"2026-11-01,\"4,000.50\",dup\n" + // 重复观测日，保留最后
		"单位：点,,\n" +
		"数据来源：交易所,,\n"
	path := writeFile(t, t.TempDir(), "dirty.csv", []byte(csvData))
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	if len(result.Rejected) != 0 {
		t.Fatalf("不应拒绝: %+v", result.Rejected)
	}
	if len(result.Accepted) != 1 {
		t.Fatalf("应有 1 个序列，实际 %d", len(result.Accepted))
	}
	acc := result.Accepted[0]
	if acc.SeriesID != "market.cn_equity.csi300" {
		t.Fatalf("series_id = %s", acc.SeriesID)
	}
	if acc.Rows != 2 {
		t.Fatalf("有效行数 = %d, want 2（两个缺失行被丢弃）", acc.Rows)
	}
	// 校验 NDJSON 内容与数值。
	records := readNDJSON(t, filepath.Join(opts.IntermediateDir, "market.cn_equity.csi300.ndjson"))
	if len(records) != 2 {
		t.Fatalf("NDJSON 行数 = %d", len(records))
	}
	if v := records[0]["value"].(float64); v != 4000.5 {
		t.Fatalf("首行值 = %v", v)
	}
	if v := records[1]["value"].(float64); v != 4010 {
		t.Fatalf("次行值 = %v", v)
	}
}

// TestMissingIsNotZeroInInbox 缺失值不得写 0 行。
func TestMissingIsNotZeroInInbox(t *testing.T) {
	csvData := "date,vix\n2026-11-01,15.2\n2026-11-02,-\n2026-11-03,null\n2026-11-04,\n"
	path := writeFile(t, t.TempDir(), "vix.csv", []byte(csvData))
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Accepted) != 1 || result.Accepted[0].Rows != 1 {
		t.Fatalf("应只有 1 条有效观测，实际 %+v", result.Accepted)
	}
	if result.Accepted[0].Evidence.DroppedRows != 3 {
		t.Fatalf("dropped_rows = %d, want 3", result.Accepted[0].Evidence.DroppedRows)
	}
}

// TestZIPExpansion zip 内递归识别多个文件，且坏文件不阻断好文件。
func TestZIPExpansion(t *testing.T) {
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	add := func(name, content string) {
		w, err := zw.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = w.Write([]byte(content))
	}
	add("batch/csi300.csv", "日期,沪深300\n2026-11-01,4000\n2026-11-02,4010\n")
	add("batch/vix.csv", "date,vix\n2026-11-01,15.2\n")
	add("batch/readme.txt", "")
	add("__MACOSX/._junk", "x")
	// 一个无法识别的文件：应被拒绝但不阻断。
	add("batch/broken.csv", "foo,bar\n1,2\n")
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	path := writeFile(t, t.TempDir(), "batch.zip", buf.Bytes())
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	if len(result.Accepted) != 2 {
		t.Fatalf("应接受 2 个序列，实际 %d: %+v", len(result.Accepted), result.Accepted)
	}
	if len(result.Rejected) != 1 {
		t.Fatalf("应拒绝 1 个文件，实际 %+v", result.Rejected)
	}
	if result.Rejected[0].ErrorFile == nil {
		t.Fatal("拒绝文件应写 error_file")
	}
	if _, err := os.Stat(*result.Rejected[0].ErrorFile); err != nil {
		t.Fatalf("error.txt 未写入: %v", err)
	}
}

// TestXLSXIngest Excel 多工作表各成一表。
func TestXLSXIngest(t *testing.T) {
	f := excelize.NewFile()
	defer f.Close()
	sheet1 := f.GetSheetName(0)
	_ = f.SetSheetRow(sheet1, "A1", &[]any{"日期", "美国国债收益率10年"})
	_ = f.SetSheetRow(sheet1, "A2", &[]any{"2026-11-01", 4.25})
	_ = f.SetSheetRow(sheet1, "A3", &[]any{"2026-11-02", 4.30})
	if _, err := f.NewSheet("Sheet2"); err != nil {
		t.Fatal(err)
	}
	_ = f.SetSheetRow("Sheet2", "A1", &[]any{"日期", "中国国债收益率10年"})
	_ = f.SetSheetRow("Sheet2", "A2", &[]any{"2026-11-01", 1.85})
	buf, err := f.WriteToBuffer()
	if err != nil {
		t.Fatal(err)
	}
	path := writeFile(t, t.TempDir(), "rates.xlsx", buf.Bytes())
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	if len(result.Accepted) != 2 {
		t.Fatalf("应有 2 个序列（两个工作表），实际 %d: %+v", len(result.Accepted), result.Accepted)
	}
	got := map[string]bool{}
	for _, a := range result.Accepted {
		got[a.SeriesID] = true
	}
	if !got["market.global.us10y"] {
		t.Fatal("海外 10Y 未识别（映射优先级失败）")
	}
	if !got["market.cn_bond.cgb_10y"] {
		t.Fatal("中国 10Y 未识别")
	}
}

// TestGBKEncodedCSV 编码探测。
func TestGBKEncodedCSV(t *testing.T) {
	// "日期,沪深300\n2026-11-01,4000\n" 的 GBK 编码。
	gbk := []byte{
		0xC8, 0xD5, 0xC6, 0xDA, ',', 0xBB, 0xA6, 0xC9, 0xEE, 0x33, 0x30, 0x30, '\n',
		'2', '0', '2', '6', '-', '1', '1', '-', '0', '1', ',', '4', '0', '0', '0', '\n',
	}
	path := writeFile(t, t.TempDir(), "gbk.csv", gbk)
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatalf("Ingest: %v", err)
	}
	if len(result.Accepted) != 1 || result.Accepted[0].SeriesID != "market.cn_equity.csi300" {
		t.Fatalf("GBK 文件未正确识别: %+v", result.Accepted)
	}
}

// TestHeaderPromotion 标题横幅 + 第 2 行表头。
func TestHeaderPromotion(t *testing.T) {
	csvData := "CBR-MAW 示例导出,,\n日期,VIX,\n2026-11-01,15.2\n2026-11-02,16.1\n"
	path := writeFile(t, t.TempDir(), "banner.csv", []byte(csvData))
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Accepted) != 1 || result.Accepted[0].SeriesID != "market.global.vix" {
		t.Fatalf("表头提升失败: %+v", result.Accepted)
	}
	if result.Accepted[0].Rows != 2 {
		t.Fatalf("rows = %d", result.Accepted[0].Rows)
	}
}

// TestLongTableForm 长表：series_id + date + value。
func TestLongTableForm(t *testing.T) {
	csvData := "date,series_id,value\n2026-11-01,VIX,15.2\n2026-11-01,SP500,5200\n2026-11-02,VIX,16.0\n"
	path := writeFile(t, t.TempDir(), "long.csv", []byte(csvData))
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Accepted) != 2 {
		t.Fatalf("长表应展开为 2 个序列，实际 %+v", result.Accepted)
	}
}

// TestReleaseTimeInInbox 海外 10Y 的 release_time 必须是次日 09:00。
func TestReleaseTimeInInbox(t *testing.T) {
	csvData := "日期,美国国债收益率10年\n2026-11-02,4.25\n"
	path := writeFile(t, t.TempDir(), "us10y.csv", []byte(csvData))
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Accepted) != 1 {
		t.Fatalf("accepted = %+v", result.Accepted)
	}
	acc := result.Accepted[0]
	if acc.SeriesID != "market.global.us10y" {
		t.Fatalf("series = %s", acc.SeriesID)
	}
	if !strings.Contains(acc.ReleaseTimeRule, "09:00") {
		t.Fatalf("release_time_rule 未写明海外规则: %s", acc.ReleaseTimeRule)
	}
	records := readNDJSON(t, filepath.Join(opts.IntermediateDir, "market.global.us10y.ndjson"))
	if len(records) != 1 {
		t.Fatalf("rows = %d", len(records))
	}
	if rt := records[0]["release_time"].(string); rt != "2026-11-03T09:00:00+08:00" {
		t.Fatalf("release_time = %s, want 2026-11-03T09:00:00+08:00", rt)
	}
}

// TestDomesticReleaseTimeInInbox 境内当日 18:00。
func TestDomesticReleaseTimeInInbox(t *testing.T) {
	csvData := "日期,沪深300\n2026-11-02,4000\n"
	path := writeFile(t, t.TempDir(), "csi.csv", []byte(csvData))
	opts := newOpts(t)
	if _, err := Ingest(path, opts); err != nil {
		t.Fatal(err)
	}
	records := readNDJSON(t, filepath.Join(opts.IntermediateDir, "market.cn_equity.csi300.ndjson"))
	if rt := records[0]["release_time"].(string); rt != "2026-11-02T18:00:00+08:00" {
		t.Fatalf("release_time = %s", rt)
	}
}

// TestEvidenceAttached 每个数值必须带 evidence。
func TestEvidenceAttached(t *testing.T) {
	csvData := "日期,VIX\n2026-11-01,15.2\n"
	path := writeFile(t, t.TempDir(), "ev.csv", []byte(csvData))
	opts := newOpts(t)
	opts.DeclaredSource = "REG-01"
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatal(err)
	}
	ev := result.Accepted[0].Evidence
	if ev == nil || len(ev.Hash) != 64 || ev.EvidenceID == "" {
		t.Fatalf("证据不完整: %+v", ev)
	}
	records := readNDJSON(t, filepath.Join(opts.IntermediateDir, "market.global.vix.ndjson"))
	if records[0]["evidence_id"].(string) != ev.EvidenceID {
		t.Fatal("数值行未绑定文件证据 ID")
	}
}

// TestMissingFile 不存在 → MissingError（映射 E_DATA_MISSING）。
func TestMissingFile(t *testing.T) {
	opts := newOpts(t)
	_, err := Ingest(filepath.Join(t.TempDir(), "nope.csv"), opts)
	if err == nil {
		t.Fatal("应返回错误")
	}
	if _, ok := err.(*MissingError); !ok {
		t.Fatalf("错误类型 = %T, want *MissingError", err)
	}
}

// TestDocumentCorpus 语料形态（标题+正文）。
func TestDocumentCorpus(t *testing.T) {
	csvData := "title,body,publish_time,source,url\n" +
		"央行降准,央行宣布下调存款准备金率0.5个百分点,2026-11-20T10:00:00+08:00,央行,https://example.com/a\n"
	path := writeFile(t, t.TempDir(), "news.csv", []byte(csvData))
	opts := newOpts(t)
	result, err := Ingest(path, opts)
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Accepted) != 1 || !strings.HasPrefix(result.Accepted[0].SeriesID, "documents.") {
		t.Fatalf("语料未识别: %+v", result.Accepted)
	}
}

func readNDJSON(t *testing.T, path string) []map[string]any {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("读取 %s: %v", path, err)
	}
	var out []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(string(raw)), "\n") {
		if line == "" {
			continue
		}
		var rec map[string]any
		if err := json.Unmarshal([]byte(line), &rec); err != nil {
			t.Fatalf("解析 NDJSON: %v", err)
		}
		out = append(out, rec)
	}
	return out
}
