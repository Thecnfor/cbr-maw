package parse

import (
	"strings"
	"testing"
	"time"
)

// TestParseJSONKlineRows 东财 kline 形态：data.klines 是分隔字符串行。
func TestParseJSONKlineRows(t *testing.T) {
	body := []byte(`{"data":{"klines":["2026-11-01,1,4000.1,4010","2026-11-02,1,4010.2,4020"]}}`)
	cfg := Config{RowsPath: "data.klines", RowSplit: ",", DateField: float64(0), ValueField: float64(2)}
	rows, err := ParseJSONRows(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 2 || rows[0].Date != "2026-11-01" || rows[0].Value != "4000.1" {
		t.Fatalf("解析结果错误: %+v", rows)
	}
}

// TestParseJSONKeyPath 键含 "." 的路径（腾讯 us.INX）。
func TestParseJSONKeyPath(t *testing.T) {
	body := []byte(`{"data":{"us.INX":{"day":[["2026-11-01","1","5200.5"]]}}}`)
	cfg := Config{RowsPath: []any{"data", "us.INX", "day"}, RowSplit: ",", DateField: float64(0), ValueField: float64(2)}
	rows, err := ParseJSONRows(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 1 || rows[0].Value != "5200.5" {
		t.Fatalf("键路径解析错误: %+v", rows)
	}
}

// TestParseCSV 列映射 + 日期格式。
func TestParseCSV(t *testing.T) {
	body := []byte("DATE,OPEN,HIGH,LOW,CLOSE\n01/02/1990,17.24,17.24,17.24,17.24\n01/03/1990,18.19,18.19,18.19,18.19\n")
	cfg := Config{DateColumn: "DATE", ValueColumn: "CLOSE", DateFormat: "%m/%d/%Y"}
	rows, err := ParseCSVRows(body, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if len(rows) != 2 || rows[0].Date != "01/02/1990" {
		t.Fatalf("CSV 解析错误: %+v", rows)
	}
}

// TestNormalizeDropsMissing 缺失值不入库。
func TestNormalizeDropsMissing(t *testing.T) {
	rows := []RawRow{
		{Date: "2026-11-01", Value: "1.5"},
		{Date: "2026-11-02", Value: "-"},
		{Date: "", Value: "2.0"},
		{Date: "2026-11-03", Value: "1,234"},
	}
	rel := func(d time.Time) (time.Time, error) { return d, nil }
	obs, dropped := Normalize(rows, "market.global.vix", "点", "cboe", "ev_x", "", 1, rel, "test")
	if len(obs) != 2 || dropped != 2 {
		t.Fatalf("obs=%d dropped=%d, want 2/2", len(obs), dropped)
	}
}

// TestNormalizeDedupe 同观测日保留最后一条。
func TestNormalizeDedupe(t *testing.T) {
	rows := []RawRow{
		{Date: "2026-11-01", Value: "1"},
		{Date: "2026-11-01", Value: "2"},
	}
	rel := func(d time.Time) (time.Time, error) { return d, nil }
	obs, _ := Normalize(rows, "market.global.vix", "点", "cboe", "ev_x", "", 1, rel, "test")
	if len(obs) != 1 || obs[0].Value != 2 {
		t.Fatalf("去重错误: %+v", obs)
	}
}

// TestNormalizeDropsSaturdayCopy 铁律 1：删周六复制行。
func TestNormalizeDropsSaturdayCopy(t *testing.T) {
	rows := []RawRow{
		{Date: "2026-11-06", Value: "100"}, // 周五
		{Date: "2026-11-07", Value: "100"}, // 周六：复制周五收盘
		{Date: "2026-11-09", Value: "101"}, // 周一
	}
	rel := func(d time.Time) (time.Time, error) { return d, nil }
	obs, dropped := Normalize(rows, "market.cn_equity.csi300", "点", "t", "ev", "", 1, rel, "test")
	if len(obs) != 2 || dropped != 1 {
		t.Fatalf("obs=%d dropped=%d, want 2/1", len(obs), dropped)
	}
	for _, o := range obs {
		if o.ObsDate == "2026-11-07" {
			t.Fatal("周六复制行必须删除")
		}
	}
	// 非交易日类序列（政策/月频）周六发布是正常的，不能删。
	obs2, dropped2 := Normalize(rows, "policy.news", "条", "t", "ev", "", 1, rel, "test")
	if len(obs2) != 3 || dropped2 != 0 {
		t.Fatalf("policy 序列不得套用交易日铁律: obs=%d dropped=%d", len(obs2), dropped2)
	}
}

// TestParseRSS 文档行。
func TestParseRSS(t *testing.T) {
	body := []byte(`<?xml version="1.0"?><rss version="2.0"><channel>
<title>FRB</title>
<item><title>Press Release 1</title><link>https://example.com/1</link>
<description><![CDATA[<p>Hello <b>world</b></p>]]></description>
<pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate></item>
</channel></rss>`)
	docs, err := ParseRSS(body, "federal_reserve", 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(docs) != 1 {
		t.Fatalf("docs = %d", len(docs))
	}
	if docs[0].Title != "Press Release 1" || strings.Contains(docs[0].Body, "<p>") {
		t.Fatalf("RSS 解析错误: %+v", docs[0])
	}
	if docs[0].URL == nil || *docs[0].URL != "https://example.com/1" {
		t.Fatal("URL 丢失")
	}
}
