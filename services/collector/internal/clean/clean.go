// Package clean 实现投喂箱与抓取共用的数值/日期/编码清洗规则。
//
// 规则对齐旧版 commorcial/src/cbr/ingest/inbox.py：
//   - 编码探测：UTF-8(BOM) → UTF-8 → GB18030 → GBK → Latin-1
//   - 占位符（-, N/A, null, 无, 暂无 …）→ 缺失，**不是 0**
//   - 千分位逗号、百分号、货币符号剥离
//   - 紧凑日期 YYYYMMDD、Excel 序列号、中文年月日
package clean

import (
	"bytes"
	"crypto/sha1" //nolint:gosec // 与旧版 doc_id 口径一致，非安全用途
	"crypto/sha256"
	"encoding/hex"
	"math"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"golang.org/x/text/encoding/simplifiedchinese"
	"golang.org/x/text/transform"
)

// JunkTokens 是缺失值占位符（小写比较）。
var JunkTokens = map[string]bool{
	"": true, "--": true, "---": true, "—": true, "－": true,
	"n/a": true, "na": true, "null": true, "none": true, "nan": true,
	"无": true, "暂无": true, "-": true, ".": true,
}

// IsJunk 判断文本是否占位符。
func IsJunk(s string) bool {
	return JunkTokens[strings.ToLower(strings.TrimSpace(s))]
}

// DecodeText 按优先级探测编码并解码为 UTF-8。
//
// 返回的错误只在所有候选都失败时出现；Latin-1 能解码任意字节，
// 因此实际几乎总成功——但会返回选中的编码供审计。
func DecodeText(data []byte) (string, error) {
	text, _, err := DecodeTextWithEncoding(data)
	return text, err
}

// DecodeTextWithEncoding 额外返回选中的编码名。
func DecodeTextWithEncoding(data []byte) (string, string, error) {
	if len(data) >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF {
		return string(data[3:]), "utf-8-sig", nil
	}
	if utf8.Valid(data) {
		return string(data), "utf-8", nil
	}
	if text, ok := decodeWith(simplifiedchinese.GB18030.NewDecoder(), data); ok {
		return text, "gb18030", nil
	}
	if text, ok := decodeWith(simplifiedchinese.GBK.NewDecoder(), data); ok {
		return text, "gbk", nil
	}
	// Latin-1：逐字节映射到 rune。
	var b strings.Builder
	for _, c := range data {
		b.WriteRune(rune(c))
	}
	return b.String(), "latin-1", nil
}

func decodeWith(t transform.Transformer, data []byte) (string, bool) {
	out, _, err := transform.Bytes(t, data)
	if err != nil {
		return "", false
	}
	if !utf8.Valid(out) {
		return "", false
	}
	// x/text 解码器遇到非法字节会输出 U+FFFD 而不报错；出现替换符即视为解码失败。
	if bytes.ContainsRune(out, utf8.RuneError) {
		return "", false
	}
	return string(out), true
}

// ParseNumber 清洗数值文本；返回 (值, 是否有效)。
//
// 缺失占位符返回 ok=false —— 调用方必须丢弃该行，**不得补 0**。
func ParseNumber(raw string) (float64, bool) {
	s := strings.TrimSpace(raw)
	if IsJunk(s) {
		return 0, false
	}
	s = strings.NewReplacer(",", "", "，", "", "%", "", "％", "", " ", "", " ", "").Replace(s)
	s = strings.TrimLeft(s, "¥$€£￥")
	s = strings.TrimSpace(s)
	if s == "" {
		return 0, false
	}
	v, err := strconv.ParseFloat(s, 64)
	if err != nil || math.IsNaN(v) || math.IsInf(v, 0) {
		return 0, false
	}
	return v, true
}

// ParseDate 解析日期文本为本地日期（无时区）。
//
// 支持：标准日期、紧凑 YYYYMMDD、中文年月日、Excel 序列号。
// format 同时接受 Go 布局与旧版 Python strftime 格式（如 %m/%d/%Y）。
func ParseDate(raw, format string) (time.Time, bool) {
	s := strings.TrimSpace(raw)
	if IsJunk(s) {
		return time.Time{}, false
	}
	if format != "" {
		for _, layout := range []string{format, strftimeToGo(format)} {
			if t, err := time.Parse(layout, s); err == nil {
				return dateOnly(t), true
			}
		}
	}
	// 纯数字：紧凑日期或 Excel 序列号。
	if n, err := strconv.ParseFloat(s, 64); err == nil {
		if n >= 19000101 && n <= 21001231 && n == math.Trunc(n) {
			if t, err := time.Parse("20060102", strconv.FormatInt(int64(n), 10)); err == nil {
				return dateOnly(t), true
			}
		}
		if n >= 20000 && n <= 70000 {
			// Excel 序列号原点 1899-12-30。
			base := time.Date(1899, 12, 30, 0, 0, 0, 0, time.UTC)
			return dateOnly(base.AddDate(0, 0, int(n))), true
		}
	}
	s = trimTrailingDash(chineseDate.Replace(s))
	if t, ok := parseLooseDate(s); ok {
		return dateOnly(t), true
	}
	return time.Time{}, false
}

var chineseDate = strings.NewReplacer("年", "-", "月", "-", "日", "")

// trimTrailingDash 处理「2026年11月」→「2026-11-」这类缺日的日期。
func trimTrailingDash(s string) string {
	return strings.TrimSuffix(strings.TrimSpace(s), "-")
}

// strftimeToGo 把常见的 Python strftime 格式转换为 Go 布局。
//
// shortcut: 只覆盖来源配置里实际出现的 %Y %m %d %H %M %S %y %b；
// 需要更多指令时补映射表。
func strftimeToGo(format string) string {
	if !strings.Contains(format, "%") {
		return format
	}
	r := strings.NewReplacer(
		"%Y", "2006", "%m", "01", "%d", "02",
		"%H", "15", "%M", "04", "%S", "05",
		"%y", "06", "%b", "Jan",
	)
	return r.Replace(format)
}

func parseLooseDate(s string) (time.Time, bool) {
	s = strings.TrimSpace(s)
	s = strings.ReplaceAll(s, "/", "-")
	if i := strings.IndexAny(s, " T"); i > 0 {
		s = s[:i]
	}
	layouts := []string{"2006-1-2", "2006-1-2 15:04:05", "2006-01-02", "01-02-2006", "1/2/2006"}
	for _, layout := range layouts {
		if t, err := time.Parse(layout, s); err == nil {
			return t, true
		}
	}
	// 补零后重试 2006-1-2 这类格式。
	parts := strings.Split(s, "-")
	if len(parts) == 2 && parts[0] != "" && parts[1] != "" {
		// 「2026-11」这类缺日：按当月 1 日。
		if t, err := time.Parse("2006-01-02", parts[0]+"-"+pad2(parts[1])+"-01"); err == nil {
			return t, true
		}
	}
	if len(parts) == 3 {
		norm := strings.Join([]string{parts[0], pad2(parts[1]), pad2(parts[2])}, "-")
		if t, err := time.Parse("2006-01-02", norm); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

func pad2(s string) string {
	if len(s) == 1 {
		return "0" + s
	}
	return s
}

func dateOnly(t time.Time) time.Time {
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// SHA256String 返回 64 位小写 hex。
func SHA256String(s string) string {
	sum := sha256.Sum256([]byte(s))
	return hex.EncodeToString(sum[:])
}

// SHA1Hex 返回 40 位小写 hex（仅用于与旧版 doc_id 口径对齐）。
func SHA1Hex(s string) string {
	sum := sha1.Sum([]byte(s)) //nolint:gosec // 见函数注释
	return hex.EncodeToString(sum[:])
}

// ContentHash 返回标题+正文的 32 位内容哈希（对齐旧版 content_hash）。
func ContentHash(title, body string) string {
	return SHA256String(title + "\n" + body)[:32]
}

// FooterPattern 匹配尾部说明行（单位/来源/合计 …），这些行不是数据。
var FooterPrefixes = []string{
	"单位", "说明", "备注", "注释", "数据来源", "来源", "合计", "总计", "平均", "均值",
	"unit", "source", "note", "notes", "total", "summary",
}

// IsFooter 判断首列文本是否为尾部说明行。
func IsFooter(firstCell string) bool {
	s := strings.ToLower(strings.TrimSpace(firstCell))
	for _, p := range FooterPrefixes {
		if strings.HasPrefix(s, p) {
			return true
		}
	}
	return false
}
