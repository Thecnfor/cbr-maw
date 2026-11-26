package service

// 数据新鲜度：以 intermediate/*.ndjson 里的**最新可用观测日**为准，不是抓取时刻。
//
// 口径来自 docs/23 §4.5 与 ADR-009 G2：
//   dead  = 最新可用日期距今 > 60 个交易日（docs/23 强制条款）
//   stale = 31..60 个交易日（ADR-009 G2：> 30 只能进历史回测/情景分析）
//   fresh = ≤ 30 个交易日（可进实时叙事）
//
// NaN 率 = 该序列在 [首日, 末日] 内、相对**同频** panel 日期并集的缺失占比
// （docs/18 §7.3 的 19.3% / 9.9% / 0.3% 就是按这个口径算出来的）。

import (
	"bufio"
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"cbr-maw/services/collector/internal/series"
	"cbr-maw/services/collector/internal/sources"
)

const (
	freshnessFresh   = "fresh"
	freshnessStale   = "stale"
	freshnessDead    = "dead"
	freshnessUnknown = "unknown"

	deadAfterTradingDays  = 60
	staleAfterTradingDays = 30
)

// dependencyFreshness 是一个依赖序列的新鲜度。
type dependencyFreshness struct {
	SeriesID        string   `json:"series_id"`
	LatestAvailable *string  `json:"latest_available"`
	Observations    int      `json:"observations"`
	NaNRate         *float64 `json:"nan_rate"`
	Freshness       string   `json:"freshness"`
}

type panelSeries struct {
	dates map[string]struct{}
	first string
	last  string
}

// panel 是 intermediate 目录下全部数值序列的观测日索引。
type panel struct {
	series  map[string]*panelSeries
	daily   []string // 日频日期并集（升序）
	monthly []string // 月频日期并集（升序）
}

// scanPanel 读取 intermediate 下的数值序列 NDJSON，按序列聚合观测日期，
// 并分别给出日频/月频的日期并集。文档行（*.documents.ndjson）不参与。
func scanPanel(dir string) *panel {
	p := &panel{series: map[string]*panelSeries{}}
	entries, err := os.ReadDir(dir)
	if err != nil {
		return p
	}
	dailySet, monthlySet := map[string]struct{}{}, map[string]struct{}{}
	for _, e := range entries {
		name := e.Name()
		if e.IsDir() || !strings.HasSuffix(name, ".ndjson") || strings.HasSuffix(name, ".documents.ndjson") {
			continue
		}
		f, err := os.Open(filepath.Join(dir, name))
		if err != nil {
			continue
		}
		sc := bufio.NewScanner(f)
		sc.Buffer(make([]byte, 0, 64*1024), 1<<20)
		for sc.Scan() {
			var rec struct {
				SeriesID string `json:"series_id"`
				ObsDate  string `json:"obs_date"`
			}
			if err := json.Unmarshal(sc.Bytes(), &rec); err != nil || rec.SeriesID == "" || rec.ObsDate == "" {
				continue
			}
			ps := p.series[rec.SeriesID]
			if ps == nil {
				ps = &panelSeries{dates: map[string]struct{}{}, first: rec.ObsDate, last: rec.ObsDate}
				p.series[rec.SeriesID] = ps
			}
			ps.dates[rec.ObsDate] = struct{}{}
			if rec.ObsDate < ps.first {
				ps.first = rec.ObsDate
			}
			if rec.ObsDate > ps.last {
				ps.last = rec.ObsDate
			}
			if series.IsMonthly(rec.SeriesID) {
				monthlySet[rec.ObsDate] = struct{}{}
			} else {
				dailySet[rec.ObsDate] = struct{}{}
			}
		}
		f.Close()
	}
	p.daily = sortedKeys(dailySet)
	p.monthly = sortedKeys(monthlySet)
	return p
}

func sortedKeys(set map[string]struct{}) []string {
	out := make([]string, 0, len(set))
	for k := range set {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func (p *panel) gridFor(seriesID string) []string {
	if series.IsMonthly(seriesID) {
		return p.monthly
	}
	return p.daily
}

// nanRate 返回序列在**全 panel 日期并集**上的缺失占比。
//
// 分母是全 panel 而不是序列自己的覆盖区间——docs/18 §7.3 的 19.3% 就是这样算的
// （北向 2342 条 / 全 panel 2902 个交易日）。用覆盖区间做分母会把停更序列算成 0%，
// 正好掩盖"已停更"这个事实。
func (p *panel) nanRate(seriesID string) *float64 {
	ps := p.series[seriesID]
	if ps == nil {
		return nil
	}
	grid := p.gridFor(seriesID)
	if len(grid) == 0 {
		return nil
	}
	rate := 1 - float64(len(ps.dates))/float64(len(grid))
	if rate < 0 {
		rate = 0
	}
	return &rate
}

// tradingDaysSince 用工作日近似交易日数。
//
// shortcut: 不扣除法定节假日，阈值判断偏保守（节假日会被算成交易日）。
// 需要精确口径时换交易所日历。
func tradingDaysSince(from, to time.Time) int {
	if !to.After(from) {
		return 0
	}
	n := 0
	for d := from.AddDate(0, 0, 1); !d.After(to); d = d.AddDate(0, 0, 1) {
		if wd := d.Weekday(); wd != time.Saturday && wd != time.Sunday {
			n++
		}
	}
	return n
}

func classifyFreshness(latest *time.Time, now time.Time) string {
	if latest == nil {
		return freshnessUnknown
	}
	days := tradingDaysSince(*latest, now)
	switch {
	case days > deadAfterTradingDays:
		return freshnessDead
	case days > staleAfterTradingDays:
		return freshnessStale
	default:
		return freshnessFresh
	}
}

// freshnessRank 用于取「最差」：数值越大越差。
// unknown（完全没有数据）比 dead（有数据但停更）更差——两者都不能进实时叙事，
// 但 unknown 连历史区间都不可用。
func freshnessRank(s string) int {
	switch s {
	case freshnessUnknown:
		return 3
	case freshnessDead:
		return 2
	case freshnessStale:
		return 1
	default:
		return 0
	}
}

func worstFreshness(a, b string) string {
	if freshnessRank(b) > freshnessRank(a) {
		return b
	}
	return a
}

// dependenciesFor 生成一个来源全部依赖序列的新鲜度。
func dependenciesFor(src *sources.Source, p *panel, now time.Time) []dependencyFreshness {
	out := make([]dependencyFreshness, 0, len(src.Series))
	for _, raw := range src.Series {
		sid := series.Canonical(raw)
		dep := dependencyFreshness{SeriesID: sid, Freshness: freshnessUnknown}
		if ps := p.series[sid]; ps != nil && ps.last != "" {
			last := ps.last
			dep.LatestAvailable = &last
			dep.Observations = len(ps.dates)
			dep.NaNRate = p.nanRate(sid)
			if t, err := time.Parse("2006-01-02", last); err == nil {
				dep.Freshness = classifyFreshness(&t, now)
			}
		}
		out = append(out, dep)
	}
	return out
}
