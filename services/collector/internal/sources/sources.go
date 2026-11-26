// Package sources 读取来源台账（来源规格）并实现台账视图。
//
// 配置读取顺序（契约 §1）：
//  1. <data_home>/configs/sources.json     用户覆盖
//  2. <resource_home>/configs/sources.json 安装包只读
//  3. <repo>/configs/sources.json          开发期仓库
//  4. <repo>/services/collector/configs/sources.json  本服务自带的迁移产物
//  5. <repo>/docs/legacy-configs/sources.yaml        旧 YAML 兼容回退
//
// JSON 是唯一真源；YAML 只做兼容读取，且不新增字段语义。
package sources

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"gopkg.in/yaml.v3"

	"cbr-maw/services/collector/internal/series"
)

// Source 是台账中的一条来源规格。
type Source struct {
	ID              string         `json:"id" yaml:"id"`
	Kind            string         `json:"kind" yaml:"kind"`
	Enabled         bool           `json:"enabled" yaml:"enabled"`
	Series          []string       `json:"series" yaml:"series"`
	Documents       bool           `json:"documents" yaml:"documents"`
	IntervalSeconds int            `json:"interval_seconds" yaml:"interval_seconds"`
	ReleaseLagDays  *int           `json:"release_lag_days" yaml:"release_lag_days"`
	PublishHour     *int           `json:"publish_hour" yaml:"publish_hour"`
	PublishMinute   *int           `json:"publish_minute" yaml:"publish_minute"`
	TZOffset        string         `json:"tz_offset" yaml:"tz_offset"`
	BackupFor       string         `json:"backup_for" yaml:"backup_for"`
	Subject         string         `json:"subject" yaml:"subject"`
	SourceName      string         `json:"source_name" yaml:"source_name"`
	Tier            string         `json:"tier" yaml:"tier"`
	AccessMode      string         `json:"access_mode" yaml:"access_mode"`
	AuthStatus      string         `json:"authorization_status" yaml:"authorization_status"`
	EndpointStatus  string         `json:"endpoint_status" yaml:"endpoint_status"`
	Notes           string         `json:"notes" yaml:"notes"`
	Params          map[string]any `json:"params" yaml:"params"`

	// 运行期状态（不落配置文件）。
	Reachability  string  `json:"-" yaml:"-"`
	LastSuccessAt *string `json:"-" yaml:"-"`
	LastError     *string `json:"-" yaml:"-"`
	LastFailure   string  `json:"-" yaml:"-"`
}

// Ledger 是全部来源规格 + 全局默认值。
type Ledger struct {
	Version   int      `json:"version"`
	UserAgent string   `json:"user_agent"`
	Defaults  Defaults `json:"defaults"`
	Sources   []Source `json:"sources"`

	// LoadedFrom 记录实际读取的配置文件（用于诊断与审计）。
	LoadedFrom string `json:"-"`
	// Warnings 记录回退/兼容读取时发现的问题。
	Warnings []string `json:"-"`
}

// Defaults 是抓取行为默认值。
type Defaults struct {
	TimeoutSeconds            int `json:"timeout_seconds"`
	Retries                   int `json:"retries"`
	StaleThresholdDays        int `json:"stale_threshold_days"`
	MonthlyStaleThresholdDays int `json:"monthly_stale_threshold_days"`
	MinIntervalSeconds        int `json:"min_interval_seconds"`
}

func defaultDefaults() Defaults {
	return Defaults{
		TimeoutSeconds:            20,
		Retries:                   2,
		StaleThresholdDays:        3,
		MonthlyStaleThresholdDays: 40,
		MinIntervalSeconds:        2,
	}
}

// Load 按既定顺序读取来源台账。repoRoot 可为空。
func Load(dataHome, resourceHome, repoRoot string) (*Ledger, error) {
	candidates := []string{}
	if dataHome != "" {
		candidates = append(candidates, filepath.Join(dataHome, "configs", "sources.json"))
	}
	if resourceHome != "" {
		candidates = append(candidates, filepath.Join(resourceHome, "configs", "sources.json"))
	}
	if repoRoot != "" {
		candidates = append(candidates,
			filepath.Join(repoRoot, "configs", "sources.json"),
			filepath.Join(repoRoot, "services", "collector", "configs", "sources.json"),
		)
	}
	for _, path := range candidates {
		if _, err := os.Stat(path); err == nil {
			ledger, err := loadJSON(path)
			if err != nil {
				return nil, err
			}
			return ledger, nil
		}
	}
	if repoRoot != "" {
		yamlPath := filepath.Join(repoRoot, "docs", "legacy-configs", "sources.yaml")
		if _, err := os.Stat(yamlPath); err == nil {
			ledger, err := loadYAML(yamlPath)
			if err != nil {
				return nil, err
			}
			return ledger, nil
		}
	}
	return nil, fmt.Errorf("来源台账缺失：已尝试 %s 与 legacy-configs/sources.yaml", strings.Join(candidates, ", "))
}

func loadJSON(path string) (*Ledger, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取来源台账 %s 失败: %w", path, err)
	}
	ledger := &Ledger{Defaults: defaultDefaults()}
	if err := json.Unmarshal(raw, ledger); err != nil {
		return nil, fmt.Errorf("解析来源台账 %s 失败: %w", path, err)
	}
	ledger.LoadedFrom = path
	ledger.normalize()
	if err := ledger.validate(); err != nil {
		return nil, err
	}
	return ledger, nil
}

// yamlDoc 是旧 YAML 的顶层结构。
type yamlDoc struct {
	Sources []Source `yaml:"sources"`
}

func loadYAML(path string) (*Ledger, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("读取旧 YAML 台账 %s 失败: %w", path, err)
	}
	var doc yamlDoc
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		return nil, fmt.Errorf("解析旧 YAML 台账 %s 失败: %w", path, err)
	}
	ledger := &Ledger{
		Version:    0,
		UserAgent:  "cbr-maw-collector/0.1.0 (+https://github.com/Thecnfor/cbr-maw)",
		Defaults:   defaultDefaults(),
		Sources:    doc.Sources,
		LoadedFrom: path,
		Warnings:   []string{"已回退到旧 YAML 台账（兼容读取），建议迁移到 configs/sources.json"},
	}
	ledger.normalize()
	if err := ledger.validate(); err != nil {
		return nil, err
	}
	return ledger, nil
}

// normalize 补齐缺省值、把 akshare 旧 kind 适配为公开 HTTP 端点。
func (l *Ledger) normalize() {
	if l.UserAgent == "" {
		l.UserAgent = "cbr-maw-collector/0.1.0 (+https://github.com/Thecnfor/cbr-maw)"
	}
	if l.Defaults.TimeoutSeconds <= 0 {
		l.Defaults.TimeoutSeconds = 20
	}
	if l.Defaults.Retries < 0 {
		l.Defaults.Retries = 2
	}
	if l.Defaults.StaleThresholdDays <= 0 {
		l.Defaults.StaleThresholdDays = 3
	}
	if l.Defaults.MonthlyStaleThresholdDays <= 0 {
		l.Defaults.MonthlyStaleThresholdDays = 40
	}
	if l.Defaults.MinIntervalSeconds < 0 {
		l.Defaults.MinIntervalSeconds = 2
	}
	for i := range l.Sources {
		s := &l.Sources[i]
		if s.TZOffset == "" {
			s.TZOffset = "+08:00"
		}
		if s.Tier == "" {
			s.Tier = "t1Public"
		}
		if s.AccessMode == "" {
			s.AccessMode = "publicHttp"
		}
		if s.AuthStatus == "" {
			s.AuthStatus = "notRequired"
		}
		if s.EndpointStatus == "" {
			s.EndpointStatus = "known"
		}
		if s.Subject == "" && len(s.Series) > 0 {
			if spec, ok := series.Specs[series.Canonical(s.Series[0])]; ok {
				s.Subject = spec.Name
			}
		}
		if s.SourceName == "" {
			if name, ok := s.Params["source"].(string); ok && name != "" {
				s.SourceName = name
			} else {
				s.SourceName = s.ID
			}
		}
		if s.Kind == "akshare" {
			adoptAkshare(s)
		}
		if s.Notes == "" && s.BackupFor != "" {
			s.Notes = "备源：" + s.BackupFor + " 不可用时自动接替"
		}
	}
}

// akshareAdapters 把旧 akshare 函数调用复刻为等价公开 HTTP 端点（不引入 Python）。
//
// 见 docs/11-实施设计.md §8.1：「Go 侧直接请求公开 HTTP 端点（复刻 akshare 的行为）」。
var akshareAdapters = map[string]struct {
	URL       string
	Query     map[string]any
	RowsPath  string
	DateField string
	Columns   map[string]string // 中文列名 → 上游字段
}{
	"bond_zh_us_yield_em": {
		URL:       "https://datacenter.eastmoney.com/api/data/get",
		Query:     map[string]any{"type": "RPTA_WEB_TREASURYYIELD", "sty": "ALL", "st": "SOLAR_DATE", "sr": "-1", "token": "894050c76af8597a853f5b408b759f5d", "p": "1", "ps": "500", "pageNo": "1", "pageNum": "1"},
		RowsPath:  "result.data",
		DateField: "SOLAR_DATE",
		Columns: map[string]string{
			"中国国债收益率2年":  "EMM00588704",
			"中国国债收益率5年":  "EMM00166462",
			"中国国债收益率10年": "EMM00166466",
			"中国国债收益率30年": "EMM00166469",
			"美国国债收益率2年":  "EMG00001306",
			"美国国债收益率10年": "EMG00001310",
		},
	},
}

func adoptAkshare(s *Source) {
	fn, _ := s.Params["func"].(string)
	adapter, ok := akshareAdapters[fn]
	if !ok {
		s.Notes = strings.TrimSpace(s.Notes + " 未提供 akshare 等价 HTTP 适配器，标记为不可抓取")
		s.Enabled = false
		s.EndpointStatus = "notApplicable"
		return
	}
	valueColumn, _ := s.Params["value_column"].(string)
	field, ok := adapter.Columns[valueColumn]
	if !ok {
		s.Enabled = false
		s.EndpointStatus = "notApplicable"
		return
	}
	s.Kind = "http_json"
	s.Params["url"] = adapter.URL
	s.Params["query"] = adapter.Query
	s.Params["rows_path"] = adapter.RowsPath
	s.Params["date_field"] = adapter.DateField
	s.Params["value_field"] = field
	s.Notes = strings.TrimSpace(s.Notes + " 由 akshare 等价 HTTP 端点复刻（不引入 Python）")
	s.EndpointStatus = "toVerify"
}

func (l *Ledger) validate() error {
	if len(l.Sources) == 0 {
		return errors.New("来源台账为空")
	}
	seen := map[string]bool{}
	for _, s := range l.Sources {
		if s.ID == "" {
			return errors.New("来源台账存在缺少 id 的条目")
		}
		if seen[s.ID] {
			return fmt.Errorf("来源台账 id 重复: %s", s.ID)
		}
		seen[s.ID] = true
		switch s.Kind {
		case "http_json", "http_csv", "rss":
		case "akshare":
			// 已被 adoptAkshare 处理；未知函数会置 enabled=false。
		default:
			return fmt.Errorf("来源 %s 的 kind 不受支持: %s", s.ID, s.Kind)
		}
		if _, ok := s.Params["url"].(string); !ok && s.Kind != "akshare" {
			return fmt.Errorf("来源 %s 缺少 params.url", s.ID)
		}
	}
	return nil
}

// Get 按 ID 查来源。
func (l *Ledger) Get(id string) (*Source, bool) {
	for i := range l.Sources {
		if l.Sources[i].ID == id {
			return &l.Sources[i], true
		}
	}
	return nil, false
}

// Backups 返回某主源的备源（按台账顺序）。
func (l *Ledger) Backups(primaryID string) []*Source {
	var out []*Source
	for i := range l.Sources {
		if l.Sources[i].BackupFor == primaryID && l.Sources[i].Enabled {
			out = append(out, &l.Sources[i])
		}
	}
	return out
}

// SeriesSources 返回负责某序列的全部来源（主源在前、备源在后）。
func (l *Ledger) SeriesSources(seriesID string) []*Source {
	canon := series.Canonical(seriesID)
	var primaries, backups []*Source
	for i := range l.Sources {
		s := &l.Sources[i]
		for _, sid := range s.Series {
			if series.Canonical(sid) != canon {
				continue
			}
			if s.BackupFor != "" {
				backups = append(backups, s)
			} else {
				primaries = append(primaries, s)
			}
			break
		}
	}
	return append(primaries, backups...)
}

// List 返回台账视图（sources.list 响应体），按 ID 排序。
func (l *Ledger) List(includeDisabled bool) []Entry {
	entries := make([]Entry, 0, len(l.Sources))
	for i := range l.Sources {
		s := &l.Sources[i]
		if !includeDisabled && !s.Enabled {
			continue
		}
		entries = append(entries, Entry{
			ID:                  s.ID,
			Modality:            modalityOf(s),
			Subject:             s.Subject,
			SourceName:          s.SourceName,
			Tier:                s.Tier,
			AccessMode:          s.AccessMode,
			AuthorizationStatus: s.AuthStatus,
			EndpointStatus:      s.EndpointStatus,
			Reachability:        s.Reachability,
			SeriesIDs:           canonicalSeries(s.Series),
			LastSuccessAt:       s.LastSuccessAt,
			LastError:           s.LastError,
			Notes:               nullable(s.Notes),
		})
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].ID < entries[j].ID })
	return entries
}

// Entry 是 sources.list 的 SourceLedgerEntry。
type Entry struct {
	ID                  string   `json:"id"`
	Modality            string   `json:"modality"`
	Subject             string   `json:"subject"`
	SourceName          string   `json:"source_name"`
	Tier                string   `json:"tier"`
	AccessMode          string   `json:"access_mode"`
	AuthorizationStatus string   `json:"authorization_status"`
	EndpointStatus      string   `json:"endpoint_status"`
	Reachability        string   `json:"reachability"`
	SeriesIDs           []string `json:"series_ids"`
	LastSuccessAt       *string  `json:"last_success_at"`
	LastError           *string  `json:"last_error"`
	Notes               *string  `json:"notes"`
}

func modalityOf(s *Source) string {
	if s.Documents {
		return "text"
	}
	return "numeric"
}

func canonicalSeries(ids []string) []string {
	out := make([]string, 0, len(ids))
	for _, id := range ids {
		out = append(out, series.Canonical(id))
	}
	return out
}

func nullable(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// State 是可达性五态（契约 §3）。
type State string

const (
	StateReachable   State = "reachable"
	StateNeedAuth    State = "need_auth"
	StateNeedLogin   State = "need_login"
	StateRestricted  State = "restricted"
	StateUnreachable State = "unreachable"
)
