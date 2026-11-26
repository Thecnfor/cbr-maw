// Package parse 把上游响应解析为规范化观测行 / 文档行。
//
// 只做格式解析与字段抽取；数值清洗（占位符、千分位）复用 clean 包，
// PIT 推导复用 pit 包，证据由调用方注入。
package parse

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"encoding/xml"
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"

	"cbr-maw/services/collector/internal/clean"
)

// Observation 是规范化观测行（NDJSON 中间文件的一行）。
type Observation struct {
	SeriesID    string  `json:"series_id"`
	ObsDate     string  `json:"obs_date"`
	Value       float64 `json:"value"`
	ReleaseTime string  `json:"release_time"`
	Source      string  `json:"source"`
	Unit        string  `json:"unit"`
	EvidenceID  string  `json:"evidence_id"`
	ReleaseRule string  `json:"release_time_rule"`
}

// Document 是规范化文档行。
type Document struct {
	DocID       string  `json:"doc_id"`
	PublishTime string  `json:"publish_time"`
	Source      string  `json:"source"`
	Title       string  `json:"title"`
	Body        string  `json:"body"`
	URL         *string `json:"url"`
	Hash        string  `json:"hash"`
	EvidenceID  string  `json:"evidence_id"`
}

// Config 是从来源 params 抽取的解析参数。
type Config struct {
	RowsPath    any     `json:"rows_path"`
	RowSplit    string  `json:"row_split"`
	DateField   any     `json:"date_field"`
	ValueField  any     `json:"value_field"`
	DateColumn  string  `json:"date_column"`
	ValueColumn string  `json:"value_column"`
	DateFormat  string  `json:"date_format"`
	Sep         string  `json:"sep"`
	SkipRows    int     `json:"skiprows"`
	ValueScale  float64 `json:"value_scale"`
	Limit       int     `json:"limit"`
	Encoding    string  `json:"encoding"`
	SourceName  string  `json:"source"`
}

// RawRow 是 (原始日期文本, 原始数值文本) 对，交给 clean 统一清洗。
type RawRow struct {
	Date  string
	Value string
}

// ParseJSONRows 解析 http_json 响应。
func ParseJSONRows(body []byte, cfg Config) ([]RawRow, error) {
	var root any
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.UseNumber()
	if err := dec.Decode(&root); err != nil {
		return nil, fmt.Errorf("JSON 解析失败: %w", err)
	}
	node := lookupPath(root, cfg.RowsPath)
	rows, ok := node.([]any)
	if !ok {
		return nil, fmt.Errorf("rows_path %v 未指向数组", cfg.RowsPath)
	}
	out := make([]RawRow, 0, len(rows))
	for _, item := range rows {
		switch row := item.(type) {
		case string:
			cells := strings.Split(row, rowSplit(cfg))
			d := cellAt(cells, cfg.DateField)
			v := cellAt(cells, cfg.ValueField)
			out = append(out, RawRow{Date: d, Value: v})
		case map[string]any:
			d := fieldAt(row, cfg.DateField)
			v := fieldAt(row, cfg.ValueField)
			out = append(out, RawRow{Date: d, Value: v})
		case []any:
			out = append(out, RawRow{
				Date:  fieldAt(row, cfg.DateField),
				Value: fieldAt(row, cfg.ValueField),
			})
		}
	}
	return out, nil
}

// ParseCSVRows 解析 http_csv 响应。
func ParseCSVRows(body []byte, cfg Config) ([]RawRow, error) {
	text, err := clean.DecodeText(body)
	if err != nil {
		return nil, err
	}
	sep := cfg.Sep
	if sep == "" {
		sep = ","
	}
	reader := csv.NewReader(strings.NewReader(text))
	reader.Comma = []rune(sep)[0]
	reader.FieldsPerRecord = -1
	records, err := reader.ReadAll()
	if err != nil {
		return nil, fmt.Errorf("CSV 解析失败: %w", err)
	}
	if cfg.SkipRows > 0 && len(records) > cfg.SkipRows {
		records = records[cfg.SkipRows:]
	}
	if len(records) < 2 {
		return nil, errors.New("CSV 无表头或无数据行")
	}
	header := records[0]
	dateIdx := indexOf(header, cfg.DateColumn)
	valueIdx := indexOf(header, cfg.ValueColumn)
	if dateIdx < 0 || valueIdx < 0 {
		return nil, fmt.Errorf("CSV 缺少列 %q 或 %q", cfg.DateColumn, cfg.ValueColumn)
	}
	out := make([]RawRow, 0, len(records)-1)
	for _, rec := range records[1:] {
		if dateIdx >= len(rec) || valueIdx >= len(rec) {
			continue
		}
		out = append(out, RawRow{Date: rec[dateIdx], Value: rec[valueIdx]})
	}
	return out, nil
}

// Normalize 把 RawRow 清洗为带 PIT 的观测行。
//
// releaseRule 决定 release_time；evidenceID 由调用方注入。
func Normalize(rows []RawRow, seriesID, unit, source, evidenceID string, dateFormat string, scale float64, release func(time.Time) (time.Time, error), releaseRule string) ([]Observation, int) {
	seen := map[string]int{}
	out := make([]Observation, 0, len(rows))
	dropped := 0
	for _, r := range rows {
		obsDate, ok := clean.ParseDate(r.Date, dateFormat)
		if !ok {
			dropped++
			continue
		}
		value, ok := clean.ParseNumber(r.Value)
		if !ok {
			dropped++
			continue
		}
		if scale != 0 && scale != 1 {
			value *= scale
		}
		rel, err := release(obsDate)
		if err != nil {
			dropped++
			continue
		}
		key := obsDate.Format("2006-01-02")
		obs := Observation{
			SeriesID:    seriesID,
			ObsDate:     key,
			Value:       value,
			ReleaseTime: rel.Format(time.RFC3339),
			Source:      source,
			Unit:        unit,
			EvidenceID:  evidenceID,
			ReleaseRule: releaseRule,
		}
		if prev, exists := seen[key]; exists {
			out[prev] = obs // 同一观测日保留最后一条
			continue
		}
		seen[key] = len(out)
		out = append(out, obs)
	}
	return out, dropped
}

// rssDoc 是 RSS 2.0 / Atom 的兼容结构。
type rssDoc struct {
	Channel struct {
		Items []rssItem `xml:"item"`
	} `xml:"channel"`
	Entries []atomEntry `xml:"entry"`
}

type rssItem struct {
	Title       string `xml:"title"`
	Link        string `xml:"link"`
	Description string `xml:"description"`
	PubDate     string `xml:"pubDate"`
	GUID        string `xml:"guid"`
}

type atomEntry struct {
	Title string `xml:"title"`
	Link  struct {
		Href string `xml:"href,attr"`
	} `xml:"link"`
	Summary string `xml:"summary"`
	Content string `xml:"content"`
	Updated string `xml:"updated"`
	ID      string `xml:"id"`
}

// ParseRSS 解析 RSS/Atom 为文档行。
func ParseRSS(body []byte, sourceName string, limit int) ([]Document, error) {
	var doc rssDoc
	if err := xml.Unmarshal(body, &doc); err != nil {
		return nil, fmt.Errorf("RSS 解析失败: %w", err)
	}
	out := make([]Document, 0)
	add := func(title, link, text, pub, guid string) {
		title = strings.TrimSpace(title)
		text = strings.TrimSpace(stripTags(text))
		if title == "" && text == "" {
			return
		}
		publish := parseFeedTime(pub)
		var urlPtr *string
		if link != "" {
			urlPtr = &link
		}
		out = append(out, Document{
			DocID:       DocID(urlPtr, title, publish),
			PublishTime: publish,
			Source:      sourceName,
			Title:       title,
			Body:        text,
			URL:         urlPtr,
			Hash:        clean.ContentHash(title, text),
		})
	}
	for _, it := range doc.Channel.Items {
		add(it.Title, it.Link, it.Description, it.PubDate, it.GUID)
	}
	for _, e := range doc.Entries {
		text := e.Summary
		if text == "" {
			text = e.Content
		}
		add(e.Title, e.Link.Href, text, e.Updated, e.ID)
	}
	if limit > 0 && len(out) > limit {
		out = out[:limit]
	}
	return out, nil
}

func parseFeedTime(raw string) string {
	raw = strings.TrimSpace(raw)
	for _, layout := range []string{time.RFC1123Z, time.RFC1123, time.RFC3339, "Mon, 02 Jan 2006 15:04:05 MST", "2006-01-02T15:04:05Z"} {
		if t, err := time.Parse(layout, raw); err == nil {
			return t.Format(time.RFC3339)
		}
	}
	return time.Now().Format(time.RFC3339)
}

// lookupPath 支持 "a.b.c" 字符串路径或 []string 键序列。
func lookupPath(root any, path any) any {
	var keys []string
	switch p := path.(type) {
	case string:
		keys = strings.Split(p, ".")
	case []any:
		for _, k := range p {
			keys = append(keys, fmt.Sprint(k))
		}
	case []string:
		keys = p
	default:
		return root
	}
	node := root
	for _, key := range keys {
		m, ok := node.(map[string]any)
		if !ok {
			return nil
		}
		node = m[key]
	}
	return node
}

func rowSplit(cfg Config) string {
	if cfg.RowSplit != "" {
		return cfg.RowSplit
	}
	return ","
}

// cellAt 支持数字索引（分隔字符串行）与字符串键。
func cellAt(cells []string, idx any) string {
	switch v := idx.(type) {
	case float64:
		return pick(cells, int(v))
	case json.Number:
		n, _ := v.Int64()
		return pick(cells, int(n))
	case string:
		if n, err := strconv.Atoi(v); err == nil {
			return pick(cells, n)
		}
		return ""
	}
	return ""
}

func pick(cells []string, i int) string {
	if i < 0 || i >= len(cells) {
		return ""
	}
	return strings.TrimSpace(cells[i])
}

func fieldAt(row any, field any) string {
	switch r := row.(type) {
	case map[string]any:
		key := fmt.Sprint(field)
		if v, ok := r[key]; ok {
			return scalar(v)
		}
		// date_field/value_field 可能给出数字索引（对 map 不适用）
		return ""
	case []any:
		switch f := field.(type) {
		case float64:
			if int(f) < len(r) {
				return scalar(r[int(f)])
			}
		case json.Number:
			n, _ := f.Int64()
			if int(n) < len(r) {
				return scalar(r[int(n)])
			}
		}
	}
	return ""
}

func scalar(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return strings.TrimSpace(t)
	case json.Number:
		return t.String()
	case float64:
		return strconv.FormatFloat(t, 'f', -1, 64)
	case bool:
		return strconv.FormatBool(t)
	default:
		return fmt.Sprint(t)
	}
}

func indexOf(header []string, name string) int {
	for i, h := range header {
		if strings.EqualFold(strings.TrimSpace(h), strings.TrimSpace(name)) {
			return i
		}
	}
	return -1
}

var tagPattern = strings.NewReplacer("<", "\x00", ">", "\x01")

// stripTags 去除 RSS 描述里的 HTML 标签（保持纯文本正文）。
func stripTags(s string) string {
	var b strings.Builder
	depth := 0
	for _, r := range s {
		switch r {
		case '<':
			depth++
		case '>':
			if depth > 0 {
				depth--
			}
		default:
			if depth == 0 {
				b.WriteRune(r)
			}
		}
	}
	out := strings.TrimSpace(b.String())
	_ = tagPattern
	return out
}

// DocID 由 URL/标题/发布时间生成稳定文档 ID（对齐旧版 doc_id_for）。
func DocID(urlPtr *string, title, publishTime string) string {
	u := ""
	if urlPtr != nil {
		u = *urlPtr
	}
	return clean.SHA256String(u + "|" + title + "|" + publishTime)[:16]
}
