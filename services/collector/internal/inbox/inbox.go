// Package inbox 实现投喂箱清洗（inbox.ingest）。
//
// 对齐旧版 commorcial/src/cbr/ingest/inbox.py 的口径：
//   - 支持 CSV / TSV / TXT / JSON / JSONL / XLSX / ZIP（zip 内递归识别）
//   - 编码探测、表头提升、脏行剔除、千分位/货币符、占位符、紧凑日期、Excel 序列号
//   - 长表 / 宽表 / 语料三形态自动识别
//   - 列名 → 序列自动映射（海外因子优先、长关键词优先、未命中 custom.*）
//   - 逐文件结论：accepted（含 series_id / rows / release_time_rule / evidence）
//     与 rejected（原因 + rejected/<file>.error.txt），脏文件不阻断其它文件
//   - 产出规范化 NDJSON 中间文件，交给 kernel 的 pit.ingest 落库（Go 不写 DuckDB）
package inbox

import (
	"archive/zip"
	"bytes"
	"encoding/csv"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/xuri/excelize/v2"

	"cbr-maw/services/collector/internal/clean"
	"cbr-maw/services/collector/internal/evidence"
	"cbr-maw/services/collector/internal/parse"
	"cbr-maw/services/collector/internal/pit"
	"cbr-maw/services/collector/internal/series"
)

// SupportedExt 是支持的文件扩展名。
var SupportedExt = map[string]bool{
	".csv": true, ".tsv": true, ".txt": true,
	".xlsx": true,
	".json": true, ".jsonl": true, ".ndjson": true,
	".zip": true,
}

var skipFiles = map[string]bool{"readme.txt": true, ".ds_store": true, "thumbs.db": true}

// Table 是从一个文件/工作表解析出的二维表（已提升表头、清理列名）。
type Table struct {
	Hint   string // 用于 custom.* 命名与映射兜底的文件名提示
	Header []string
	Rows   [][]string
}

// Options 是清洗参数。
type Options struct {
	DeclaredSource  string
	AsOf            string
	Overrides       map[string]string // 列名 → 序列 ID 覆盖
	IntermediateDir string            // NDJSON 产出目录
	RejectedDir     string            // 拒绝文件目录
	Now             time.Time
}

// Accepted 是一个被接受的文件结论。
type Accepted struct {
	File            string                 `json:"file"`
	SeriesID        string                 `json:"series_id"`
	Rows            int                    `json:"rows"`
	ReleaseTimeRule string                 `json:"release_time_rule"`
	Evidence        *evidence.FileEvidence `json:"evidence"`
	// MappingBasis 说明该 series_id 是精确命中 / 列名命中 / 文件名命中 / 自定义。
	MappingBasis string `json:"mapping_basis,omitempty"`

	writtenPath string
}

// Rejected 是一个被拒绝的文件结论。
type Rejected struct {
	File      string  `json:"file"`
	Reason    string  `json:"reason"`
	ErrorFile *string `json:"error_file"`
}

// Result 是 inbox.ingest 的响应体。
type Result struct {
	BatchID  string     `json:"batch_id"`
	Accepted []Accepted `json:"accepted"`
	Rejected []Rejected `json:"rejected"`
}

// Extend evidence package with the file-level shape used by the contract.
// (Declared here to keep the response type local to the inbox domain.)

// MappingRules 返回可查的列名映射规则表（设置页展示 / 覆盖依据）。
func MappingRules() []series.MappingRule { return series.MappingRules() }

// Ingest 处理一个投递文件或压缩包，返回逐文件结论。
//
// 单个成员文件失败只记入 rejected，不中断其它成员。
func Ingest(path string, opts Options) (*Result, error) {
	info, err := os.Stat(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, &MissingError{Path: path}
		}
		return nil, err
	}
	if info.IsDir() {
		return nil, fmt.Errorf("path 必须是文件，不能是目录：%s", path)
	}
	if opts.Now.IsZero() {
		opts.Now = time.Now()
	}
	result := &Result{
		BatchID:  "batch_" + opts.Now.Format("20060102_150405"),
		Accepted: []Accepted{},
		Rejected: []Rejected{},
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取投递文件失败: %w", err)
	}
	if err := ensureDirs(opts); err != nil {
		return nil, err
	}
	members, err := expand(path, data)
	if err != nil {
		result.Rejected = append(result.Rejected, reject(opts, path, err))
		return result, nil
	}
	for _, m := range members {
		accepted := processMember(m, opts, result.BatchID)
		if accepted == nil {
			continue
		}
		if accepted.err != nil {
			result.Rejected = append(result.Rejected, reject(opts, m.name, accepted.err))
			continue
		}
		result.Accepted = append(result.Accepted, accepted.items...)
	}
	return result, nil
}

// MissingError 表示投递文件不存在（映射为 E_DATA_MISSING）。
type MissingError struct{ Path string }

func (e *MissingError) Error() string { return "文件不存在：" + e.Path }

func ensureDirs(opts Options) error {
	for _, dir := range []string{opts.IntermediateDir, opts.RejectedDir} {
		if dir == "" {
			continue
		}
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return fmt.Errorf("创建目录 %s 失败: %w", dir, err)
		}
	}
	return nil
}

// member 是压缩包内（或单文件）的一个待处理成员。
type member struct {
	name string // 展示用文件名（zip 内为相对路径）
	data []byte
}

func expand(path string, data []byte) ([]member, error) {
	ext := strings.ToLower(filepath.Ext(path))
	if ext != ".zip" {
		if !SupportedExt[ext] {
			return nil, fmt.Errorf("不支持的文件类型：%s", ext)
		}
		return []member{{name: filepath.Base(path), data: data}}, nil
	}
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, fmt.Errorf("ZIP 解析失败: %w", err)
	}
	names := make([]string, 0, len(zr.File))
	byName := map[string]*zip.File{}
	for _, f := range zr.File {
		name := f.Name
		if strings.HasSuffix(name, "/") || strings.Contains(name, "__MACOSX") ||
			strings.HasPrefix(filepath.Base(name), "~$") || skipFiles[strings.ToLower(filepath.Base(name))] {
			continue
		}
		if filepath.Ext(name) == "" || !SupportedExt[strings.ToLower(filepath.Ext(name))] {
			continue
		}
		if strings.ToLower(filepath.Ext(name)) == ".zip" {
			continue
		}
		names = append(names, name)
		byName[name] = f
	}
	if len(names) == 0 {
		return nil, errors.New("ZIP 压缩包中未发现可识别的数据文件")
	}
	sort.Strings(names)
	out := make([]member, 0, len(names))
	for _, name := range names {
		rc, err := byName[name].Open()
		if err != nil {
			return nil, fmt.Errorf("读取压缩包成员 %s 失败: %w", name, err)
		}
		content, err := io.ReadAll(rc)
		rc.Close()
		if err != nil {
			return nil, fmt.Errorf("读取压缩包成员 %s 失败: %w", name, err)
		}
		out = append(out, member{name: name, data: content})
	}
	return out, nil
}

type memberOutcome struct {
	items []Accepted
	err   error
}

func processMember(m member, opts Options, batchID string) *memberOutcome {
	tables, err := LoadTables(m.name, m.data)
	if err != nil {
		return &memberOutcome{err: err}
	}
	var items []Accepted
	hadContent := false
	for _, table := range tables {
		if len(table.Rows) == 0 {
			continue
		}
		hadContent = true
		if docs := extractDocuments(table); len(docs) > 0 {
			item, err := writeDocuments(m.name, table.Hint, docs, m.data, opts, batchID)
			if err != nil {
				return &memberOutcome{err: err}
			}
			items = append(items, item)
			continue
		}
		obs, err := extractObservations(table, opts.Overrides)
		if err != nil {
			return &memberOutcome{err: err}
		}
		if len(obs.groups) == 0 {
			continue
		}
		for _, group := range obs.groups {
			dropped := obs.dropped
			if group.Dropped > 0 {
				dropped = group.Dropped
			}
			item, err := writeObservations(m.name, table.Hint, group, dropped, m.data, opts, batchID)
			if err != nil {
				return &memberOutcome{err: err}
			}
			items = append(items, item)
		}
	}
	if !hadContent {
		return &memberOutcome{err: errors.New("文件为空或无有效数据行")}
	}
	if len(items) == 0 {
		return &memberOutcome{err: errors.New("未能识别出有效日期/数值序列或标题/正文文档列")}
	}
	return &memberOutcome{items: items}
}

func reject(opts Options, name string, cause error) Rejected {
	base := filepath.Base(name)
	out := Rejected{File: base, Reason: shortReason(cause)}
	if opts.RejectedDir != "" {
		path := filepath.Join(opts.RejectedDir, base+".error.txt")
		_ = os.WriteFile(path, []byte(cause.Error()), 0o644)
		out.ErrorFile = &path
	}
	return out
}

func shortReason(err error) string {
	msg := err.Error()
	switch {
	case strings.Contains(msg, "不支持的文件类型"):
		return "不支持的文件类型"
	case strings.Contains(msg, "未能识别"):
		return "表头无法识别为任何规范序列"
	case strings.Contains(msg, "ZIP"):
		return "压缩包解析失败"
	case strings.Contains(msg, "空"):
		return "文件为空或无有效数据行"
	default:
		return msg
	}
}

// LoadTables 按扩展名读取一个或多个表（xlsx 多工作表各自成表）。
func LoadTables(name string, data []byte) ([]Table, error) {
	ext := strings.ToLower(filepath.Ext(name))
	stem := strings.TrimSuffix(filepath.Base(name), filepath.Ext(name))
	switch ext {
	case ".csv", ".tsv", ".txt":
		table, err := loadDelimited(stem, data, ext)
		if err != nil {
			return nil, err
		}
		return []Table{table}, nil
	case ".xlsx":
		return loadXLSX(stem, data)
	case ".json", ".jsonl", ".ndjson":
		table, err := loadJSON(stem, data, ext)
		if err != nil {
			return nil, err
		}
		return []Table{table}, nil
	default:
		return nil, fmt.Errorf("不支持的文件类型：%s", ext)
	}
}

func loadDelimited(stem string, data []byte, ext string) (Table, error) {
	text, err := clean.DecodeText(data)
	if err != nil {
		return Table{}, err
	}
	sep := ','
	if ext == ".tsv" {
		sep = '\t'
	} else if !strings.Contains(text, ",") && strings.Contains(text, "\t") {
		sep = '\t'
	}
	reader := csv.NewReader(strings.NewReader(text))
	reader.Comma = sep
	reader.FieldsPerRecord = -1
	reader.LazyQuotes = true
	records, err := reader.ReadAll()
	if err != nil {
		return Table{}, fmt.Errorf("文本表格解析失败: %w", err)
	}
	return buildTable(stem, records), nil
}

func loadXLSX(stem string, data []byte) ([]Table, error) {
	f, err := excelize.OpenReader(bytes.NewReader(data))
	if err != nil {
		return nil, fmt.Errorf("Excel 解析失败: %w", err)
	}
	defer f.Close()
	sheets := f.GetSheetList()
	out := []Table{}
	for _, sheet := range sheets {
		rows, err := f.GetRows(sheet)
		if err != nil {
			continue
		}
		hint := stem
		if len(sheets) > 1 {
			hint = stem + "_" + sheet
		}
		table := buildTable(hint, rows)
		if len(table.Rows) > 0 {
			out = append(out, table)
		}
	}
	if len(out) == 0 {
		return nil, errors.New("Excel 无有效工作表或全部为空")
	}
	return out, nil
}

func loadJSON(stem string, data []byte, ext string) (Table, error) {
	text, err := clean.DecodeText(data)
	if err != nil {
		return Table{}, err
	}
	text = strings.TrimSpace(text)
	if text == "" {
		return Table{}, errors.New("JSON 内容为空")
	}
	var records []map[string]any
	if ext == ".jsonl" || ext == ".ndjson" {
		for _, line := range strings.Split(text, "\n") {
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			var rec map[string]any
			if err := json.Unmarshal([]byte(line), &rec); err != nil {
				return Table{}, fmt.Errorf("JSONL 行解析失败: %w", err)
			}
			records = append(records, rec)
		}
	} else {
		var payload any
		if err := json.Unmarshal([]byte(text), &payload); err != nil {
			return Table{}, fmt.Errorf("JSON 解析失败: %w", err)
		}
		records = jsonRecords(payload)
	}
	if len(records) == 0 {
		return Table{}, errors.New("JSON 顶层结构需为对象或记录列表")
	}
	header := orderedKeys(records)
	rows := make([][]string, 0, len(records))
	for _, rec := range records {
		row := make([]string, len(header))
		for i, key := range header {
			row[i] = jsonScalar(rec[key])
		}
		rows = append(rows, row)
	}
	return buildTable(stem, append([][]string{header}, rows...)), nil
}

func jsonRecords(payload any) []map[string]any {
	switch v := payload.(type) {
	case []any:
		out := make([]map[string]any, 0, len(v))
		for _, item := range v {
			if rec, ok := item.(map[string]any); ok {
				out = append(out, rec)
			}
		}
		return out
	case map[string]any:
		for _, key := range []string{"data", "records", "rows", "items", "documents", "series"} {
			if list, ok := v[key].([]any); ok {
				return jsonRecords(list)
			}
		}
		return []map[string]any{v}
	default:
		return nil
	}
}

func orderedKeys(records []map[string]any) []string {
	seen := map[string]bool{}
	var keys []string
	for _, rec := range records {
		for k := range rec {
			if !seen[k] {
				seen[k] = true
				keys = append(keys, k)
			}
		}
	}
	sort.Strings(keys)
	return keys
}

func jsonScalar(v any) string {
	switch t := v.(type) {
	case nil:
		return ""
	case string:
		return t
	case float64:
		return strconvF(t)
	case bool:
		if t {
			return "true"
		}
		return "false"
	default:
		return fmt.Sprint(t)
	}
}

func strconvF(f float64) string {
	return strings.TrimSuffix(strings.TrimRight(fmt.Sprintf("%.10f", f), "0"), ".")
}

// buildTable 做表头提升、列名清理、空行/尾部说明行剔除。
func buildTable(hint string, raw [][]string) Table {
	raw = trimEmpty(raw)
	if len(raw) == 0 {
		return Table{Hint: hint}
	}
	raw = promoteHeader(raw)
	header := make([]string, len(raw[0]))
	seen := map[string]int{}
	for i, col := range raw[0] {
		name := strings.TrimSpace(strings.TrimPrefix(col, "\ufeff"))
		name = strings.NewReplacer("\r", " ", "\n", " ").Replace(name)
		if name == "" || strings.HasPrefix(strings.ToLower(name), "unnamed:") || strings.EqualFold(name, "nan") {
			name = fmt.Sprintf("col_%d", i)
		}
		if n, ok := seen[name]; ok {
			seen[name] = n + 1
			name = fmt.Sprintf("%s_%d", name, n)
		} else {
			seen[name] = 1
		}
		header[i] = name
	}
	rows := make([][]string, 0, len(raw)-1)
	for _, row := range raw[1:] {
		row = fitRow(row, len(header))
		if isBlank(row) {
			continue
		}
		if len(row) > 0 && clean.IsFooter(row[0]) {
			continue
		}
		rows = append(rows, row)
	}
	return Table{Hint: hint, Header: header, Rows: rows}
}

func promoteHeader(raw [][]string) [][]string {
	if len(raw) < 2 {
		return raw
	}
	unnamed := 0
	for _, col := range raw[0] {
		lower := strings.ToLower(strings.TrimSpace(col))
		if lower == "" || strings.HasPrefix(lower, "unnamed:") {
			unnamed++
		}
	}
	if float64(unnamed)/float64(max(len(raw[0]), 1)) < 0.5 {
		return raw
	}
	limit := min(5, len(raw)-1)
	for i := 0; i < limit; i++ {
		cells := raw[i]
		nonEmpty := 0
		hasHeaderWord := false
		for _, c := range cells {
			t := strings.ToLower(strings.TrimSpace(c))
			if t == "" || t == "nan" {
				continue
			}
			nonEmpty++
			if isHeaderWord(t) {
				hasHeaderWord = true
			}
		}
		if nonEmpty >= 2 && hasHeaderWord {
			promoted := make([][]string, 0, len(raw)-i-1)
			header := make([]string, len(cells))
			for j, c := range cells {
				t := strings.TrimSpace(c)
				if t == "" || strings.EqualFold(t, "nan") {
					t = fmt.Sprintf("col_%d", j)
				}
				header[j] = t
			}
			promoted = append(promoted, header)
			promoted = append(promoted, raw[i+1:]...)
			return promoted
		}
	}
	return raw
}

func isHeaderWord(s string) bool {
	for _, w := range []string{"date", "日期", "时间", "time", "series", "指标", "value", "数值", "title", "标题", "body", "正文", "source", "来源", "代码", "code"} {
		if strings.Contains(s, w) {
			return true
		}
	}
	return false
}

func trimEmpty(raw [][]string) [][]string {
	for len(raw) > 0 && isBlank(raw[0]) {
		raw = raw[1:]
	}
	for len(raw) > 0 && isBlank(raw[len(raw)-1]) {
		raw = raw[:len(raw)-1]
	}
	return raw
}

func isBlank(row []string) bool {
	for _, c := range row {
		if strings.TrimSpace(c) != "" {
			return false
		}
	}
	return true
}

// fitRow 把行对齐到表头宽度：缺列补空，多出的单元格丢弃。
//
// 多出单元格几乎总是未加引号的千分位/分隔符造成的列错位（如 ¥4,010）；
// 表头已定义列数，多出的数据不属于任何列，保留只会污染出假的 custom 序列。
func fitRow(row []string, n int) []string {
	if len(row) == n {
		return row
	}
	out := make([]string, n)
	copy(out, row)
	return out
}

// observationGroup 是一个序列的清洗结果。
type observationGroup struct {
	SeriesID     string
	ReleaseRule  string
	MappingBasis string
	Rows         []parse.Observation
	Dropped      int
}

type observationResult struct {
	groups  []observationGroup
	dropped int
}

// columnCandidates 与旧版 custom.py 的列候选对齐。
var (
	dateColumns = []string{"date", "trade_date", "obs_date", "日期", "交易日期", "时间", "time", "datetime"}
	// publish_time 是真实发布列，优先于观测日；date/time 只在没有发布列时兜底。
	releaseColumns = []string{"release_time", "publish_time", "发布时间", "公布时间", "availability_time", "released_at"}
	docTimeColumns = append(append([]string{}, releaseColumns...), dateColumns...)
	seriesColumns  = []string{"series_id", "series", "indicator", "code", "metric", "指标id", "指标编码", "指标代码", "序列", "序列id", "指标", "指标名称"}
	valueColumns   = []string{"value", "val", "close", "收盘", "收盘价", "数值", "值", "指标值", "latest", "price"}
	sourceColumns  = []string{"source", "来源", "media", "publisher"}
	titleColumns   = []string{"title", "标题", "headline", "news_title"}
	bodyColumns    = []string{"body", "content", "正文", "内容", "text", "summary"}
	urlColumns     = []string{"url", "link", "链接", "网址"}
	docIDColumns   = []string{"doc_id", "文档id", "docid", "id"}
)

func findColumn(header []string, candidates []string) (string, int) {
	lowered := make([]string, len(header))
	for i, h := range header {
		lowered[i] = strings.ToLower(strings.TrimSpace(h))
	}
	for _, cand := range candidates {
		for i, h := range lowered {
			if h == strings.ToLower(cand) {
				return header[i], i
			}
		}
	}
	return "", -1
}

// extractObservations 识别长表 / 宽表并清洗为观测行。
func extractObservations(table Table, overrides map[string]string) (observationResult, error) {
	var result observationResult
	_, dateIdx := findColumn(table.Header, dateColumns)
	if dateIdx < 0 {
		// 回退：首列若能解析出 ≥60% 日期则作为日期列。
		if len(table.Header) > 0 {
			ok := 0
			for _, row := range table.Rows {
				if _, valid := clean.ParseDate(row[0], ""); valid {
					ok++
				}
			}
			if len(table.Rows) > 0 && float64(ok)/float64(len(table.Rows)) >= 0.6 {
				dateIdx = 0
			}
		}
	}
	if dateIdx < 0 {
		return result, nil
	}
	_, releaseIdx := findColumn(table.Header, releaseColumns)
	_, sourceIdx := findColumn(table.Header, sourceColumns)
	_, seriesIdx := findColumn(table.Header, seriesColumns)
	_, valueIdx := findColumn(table.Header, valueColumns)

	// 长表模式：明确存在 series_id + value 列。
	if seriesIdx >= 0 && valueIdx >= 0 && seriesIdx != dateIdx && valueIdx != dateIdx {
		type longRow struct {
			rawSeries string
			obs       parse.Observation
		}
		groups := map[string]*observationGroup{}
		var order []string
		for _, row := range table.Rows {
			obsDate, ok := clean.ParseDate(row[dateIdx], "")
			if !ok {
				result.dropped++
				continue
			}
			value, ok := clean.ParseNumber(row[valueIdx])
			if !ok {
				result.dropped++
				continue
			}
			rawSeries := strings.TrimSpace(row[seriesIdx])
			sid, basis := series.ResolveColumn(rawSeries, table.Hint, overrides)
			rule := ruleFor(sid)
			rel, err := rule.ReleaseTime(obsDate)
			if err != nil {
				result.dropped++
				continue
			}
			if releaseIdx >= 0 {
				if explicit, ok := parseExplicitRelease(row[releaseIdx]); ok {
					rel = explicit
				}
			}
			obs := parse.Observation{
				SeriesID:    sid,
				ObsDate:     obsDate.Format("2006-01-02"),
				Value:       value,
				ReleaseTime: rel.Format(time.RFC3339),
				Source:      sourceName(row, sourceIdx, table.Hint),
				Unit:        series.Unit(sid),
				ReleaseRule: rule.Describe(),
			}
			g, ok := groups[sid]
			if !ok {
				g = &observationGroup{SeriesID: sid, ReleaseRule: rule.Describe(), MappingBasis: basis}
				groups[sid] = g
				order = append(order, sid)
			}
			g.Rows = append(g.Rows, obs)
		}
		for _, sid := range order {
			result.groups = append(result.groups, *groups[sid])
		}
		return result, nil
	}

	// 宽表模式：日期列之外的数值列逐列展开。
	skip := map[int]bool{dateIdx: true}
	if releaseIdx >= 0 {
		skip[releaseIdx] = true
	}
	if sourceIdx >= 0 {
		skip[sourceIdx] = true
	}
	seen := map[string]int{}
	// 每个序列的 dropped_rows 单独计（同一行可能在多个序列里各计一次）。
	groupDropped := map[string]int{}
	text := textColumns(table.Rows, len(table.Header))
	for colIdx, colName := range table.Header {
		if skip[colIdx] || text[colIdx] {
			continue // 纯文本列（备注/说明）不是序列
		}
		sid, basis := series.ResolveColumn(colName, table.Hint, overrides)
		rule := ruleFor(sid)
		var rows []parse.Observation
		for _, row := range table.Rows {
			obsDate, ok := clean.ParseDate(row[dateIdx], "")
			if !ok {
				groupDropped[sid]++
				continue
			}
			value, ok := clean.ParseNumber(row[colIdx])
			if !ok {
				groupDropped[sid]++ // 数值缺失：丢弃该单元格，不补 0
				continue
			}
			rel, err := rule.ReleaseTime(obsDate)
			if err != nil {
				continue
			}
			if releaseIdx >= 0 {
				if explicit, ok := parseExplicitRelease(row[releaseIdx]); ok {
					rel = explicit
				}
			}
			obs := parse.Observation{
				SeriesID:    sid,
				ObsDate:     obsDate.Format("2006-01-02"),
				Value:       value,
				ReleaseTime: rel.Format(time.RFC3339),
				Source:      sourceName(row, sourceIdx, table.Hint),
				Unit:        series.Unit(sid),
				ReleaseRule: rule.Describe(),
			}
			if idx, ok := seen[sid+obs.ObsDate]; ok {
				rows[idx] = obs
				continue
			}
			seen[sid+obs.ObsDate] = len(rows)
			rows = append(rows, obs)
		}
		if len(rows) == 0 {
			continue
		}
		result.groups = append(result.groups, observationGroup{
			SeriesID:     sid,
			ReleaseRule:  rule.Describe(),
			MappingBasis: basis,
			Rows:         rows,
			Dropped:      groupDropped[sid],
		})
	}
	return result, nil
}

// textColumns 判断哪些列是纯文本列（备注/说明/来源），不应展开为序列。
//
// 判定：该列**没有任何**可解析数值时才算文本列。这样「备注」不会被当成 custom 序列，
// 而缺失较多的指标列（少量有效值）仍会被保留——缺失的语义由逐行清洗负责，不是列级判定。
func textColumns(rows [][]string, width int) []bool {
	out := make([]bool, width)
	for col := 0; col < width; col++ {
		hasNumeric := false
		for _, row := range rows {
			if col >= len(row) {
				continue
			}
			if _, ok := clean.ParseNumber(row[col]); ok {
				hasNumeric = true
				break
			}
		}
		out[col] = !hasNumeric
	}
	return out
}

func ruleFor(seriesID string) pit.Rule {
	return pit.DefaultRule(seriesID)
}

// parseExplicitRelease 解析文件/响应里的发布列。
//
// 带时区后缀的按原样；不带时区的按来源默认时区 +08:00 解释——
// 文件里的 "18:00:00" 是北京时间，不是 UTC（标成 Z 会让数据提前 8 小时可用）。
func parseExplicitRelease(raw string) (time.Time, bool) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return time.Time{}, false
	}
	if t, err := time.Parse(time.RFC3339, raw); err == nil {
		return t, true
	}
	shanghai := time.FixedZone("+08:00", 8*3600)
	for _, layout := range []string{"2006-01-02 15:04:05", "2006-01-02T15:04:05", "2006-01-02"} {
		if t, err := time.ParseInLocation(layout, raw, shanghai); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

func sourceName(row []string, idx int, hint string) string {
	if idx >= 0 && idx < len(row) {
		if v := strings.TrimSpace(row[idx]); v != "" {
			return v
		}
	}
	return "inbox:" + hint
}

// extractDocuments 识别语料形态（标题+正文）。
func extractDocuments(table Table) []parse.Document {
	titleName, titleIdx := findColumn(table.Header, titleColumns)
	bodyName, bodyIdx := findColumn(table.Header, bodyColumns)
	if titleIdx < 0 || bodyIdx < 0 {
		return nil
	}
	_ = titleName
	_ = bodyName
	_, timeIdx := findColumn(table.Header, docTimeColumns)
	_, sourceIdx := findColumn(table.Header, sourceColumns)
	_, urlIdx := findColumn(table.Header, urlColumns)
	_, docIDIdx := findColumn(table.Header, docIDColumns)

	var out []parse.Document
	for _, row := range table.Rows {
		title := strings.TrimSpace(row[titleIdx])
		body := strings.TrimSpace(row[bodyIdx])
		if title == "" && body == "" {
			continue
		}
		publish := time.Now().Format(time.RFC3339)
		if timeIdx >= 0 {
			if t, ok := parseExplicitRelease(row[timeIdx]); ok {
				publish = t.Format(time.RFC3339)
			}
		}
		var urlPtr *string
		if urlIdx >= 0 && strings.TrimSpace(row[urlIdx]) != "" {
			u := strings.TrimSpace(row[urlIdx])
			urlPtr = &u
		}
		docID := ""
		if docIDIdx >= 0 {
			docID = strings.TrimSpace(row[docIDIdx])
		}
		if docID == "" {
			docID = parse.DocID(urlPtr, title, publish)
		}
		source := "inbox:" + table.Hint
		if sourceIdx >= 0 && strings.TrimSpace(row[sourceIdx]) != "" {
			source = strings.TrimSpace(row[sourceIdx])
		}
		out = append(out, parse.Document{
			DocID:       docID,
			PublishTime: publish,
			Source:      source,
			Title:       title,
			Body:        body,
			URL:         urlPtr,
			Hash:        clean.ContentHash(title, body),
		})
	}
	return out
}
