package clean

import (
	"testing"
	"time"
)

func TestDecodeTextEncodings(t *testing.T) {
	cases := []struct {
		name string
		data []byte
		want string
		enc  string
	}{
		{"utf8", []byte("日期,数值\n2026-11-01,1.5\n"), "日期,数值\n2026-11-01,1.5\n", "utf-8"},
		{"utf8-bom", append([]byte{0xEF, 0xBB, 0xBF}, []byte("日期,数值\n")...), "日期,数值\n", "utf-8-sig"},
		// GBK 编码的「日期」
		{"gbk", []byte{0xC8, 0xD5, 0xC6, 0xDA, ',', '1'}, "日期,1", "gbk"},
		// 0xFF 在 GB18030/GBK 中非法，只能按 Latin-1 解释
		{"latin1", []byte{0xFF, 0xFE, 0x61}, "ÿþa", "latin-1"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, enc, err := DecodeTextWithEncoding(c.data)
			if err != nil {
				t.Fatalf("DecodeTextWithEncoding: %v", err)
			}
			if got != c.want {
				t.Fatalf("decoded = %q, want %q", got, c.want)
			}
			if c.name == "gbk" && enc != "gb18030" && enc != "gbk" {
				t.Fatalf("encoding = %q, want gb18030/gbk", enc)
			}
			if c.name == "latin1" && enc != "latin-1" {
				t.Fatalf("encoding = %q, want latin-1", enc)
			}
		})
	}
}

func TestParseNumberDirtyInputs(t *testing.T) {
	cases := []struct {
		raw   string
		want  float64
		valid bool
	}{
		{"1,234.5", 1234.5, true},
		{"1，234", 1234, true},
		{"¥ 3,000", 3000, true},
		{"12.5%", 12.5, true},
		{"-", 0, false},
		{"N/A", 0, false},
		{"null", 0, false},
		{"", 0, false},
		{"暂无", 0, false},
		{"--", 0, false},
		{"0", 0, true},
	}
	for _, c := range cases {
		got, ok := ParseNumber(c.raw)
		if ok != c.valid {
			t.Fatalf("ParseNumber(%q) valid=%v, want %v", c.raw, ok, c.valid)
		}
		if ok && got != c.want {
			t.Fatalf("ParseNumber(%q) = %v, want %v", c.raw, got, c.want)
		}
	}
}

// TestMissingIsNotZero 保证缺失值不会被当成 0。
func TestMissingIsNotZero(t *testing.T) {
	for _, raw := range []string{"", "-", "N/A", "null", "nan", "无"} {
		if v, ok := ParseNumber(raw); ok {
			t.Fatalf("ParseNumber(%q) 应为缺失，却返回 %v", raw, v)
		}
	}
	if v, ok := ParseNumber("0"); !ok || v != 0 {
		t.Fatalf("ParseNumber(\"0\") 应为有效 0")
	}
}

func TestParseDateFormats(t *testing.T) {
	cases := []struct {
		raw    string
		format string
		want   string
	}{
		{"2026-11-01", "", "2026-11-01"},
		{"20261101", "", "2026-11-01"},
		{"2026年11月1日", "", "2026-11-01"},
		{"2026年11月", "", "2026-11-01"},
		{"11/01/2026", "%m/%d/%Y", "2026-11-01"},
		{"2026/11/01", "", "2026-11-01"},
		{"46310", "", "2026-10-15"}, // Excel 序列号（原点 1899-12-30，已用 Python 核对）
	}
	for _, c := range cases {
		got, ok := ParseDate(c.raw, c.format)
		if !ok {
			t.Fatalf("ParseDate(%q,%q) 解析失败", c.raw, c.format)
		}
		if s := got.Format("2006-01-02"); s != c.want {
			t.Fatalf("ParseDate(%q) = %s, want %s", c.raw, s, c.want)
		}
	}
	if _, ok := ParseDate("-", ""); ok {
		t.Fatal("占位符不应解析成日期")
	}
}

func TestIsFooter(t *testing.T) {
	for _, s := range []string{"单位：点", "数据来源：交易所", "合计", "note: x", "source: cboe"} {
		if !IsFooter(s) {
			t.Fatalf("IsFooter(%q) = false", s)
		}
	}
	if IsFooter("2026-11-01") {
		t.Fatal("日期行不应被判为尾部说明")
	}
}

func TestParseDateNoTZLeak(t *testing.T) {
	// 日期解析必须落在 UTC 零点，避免时区漂移导致 obs_date 跨日。
	got, ok := ParseDate("2026-11-01T23:30:00+08:00", "")
	if !ok {
		t.Fatal("解析失败")
	}
	if got.Location() != time.UTC || got.Hour() != 0 {
		t.Fatalf("日期未归一化到 UTC 零点: %v", got)
	}
}
