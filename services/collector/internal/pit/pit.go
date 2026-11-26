// Package pit 实现 Point-in-Time 发布时点（release_time）推导。
//
// 契约 §5 四要素：release_lag_days + publish_hour/publish_minute + tz_offset。
// 规则（与 docs/legacy-configs/sources.yaml 注释一致）：
//   - A 股 / 中债 / 港股：观测日当日 18:00 (+08:00)
//   - 隔夜海外因子（VIX / SP500 / US10Y）：观测日次日 09:00 (+08:00)
//   - 月频：按发布日（release_lag_days 取目录值，至少 1 天）
//   - 无发布列 → 保守规则，依据写入 release_time_rule
package pit

import (
	"fmt"
	"strconv"
	"strings"
	"time"

	"cbr-maw/services/collector/internal/series"
)

// Rule 是单个来源/序列的发布时点规则。
type Rule struct {
	LagDays int    // 观测日到发布日的时滞（自然日）
	Hour    int    // 发布小时（本地时区）
	Minute  int    // 发布分钟
	TZ      string // 时区偏移，如 "+08:00"
	// Basis 是规则来源说明，写入 release_time_rule，供审计。
	Basis string
}

// DefaultRule 返回某序列在「无发布列」时的保守规则。
//
// 依据写入 Rule.Basis；优先级：隔夜海外 > 月频 > 境内日频。
func DefaultRule(seriesID string) Rule {
	sid := series.Canonical(seriesID)
	switch {
	case series.IsOverseas(sid):
		lag := max(series.ReleaseLagDays(sid), 1)
		return Rule{LagDays: lag, Hour: 9, Minute: 0, TZ: "+08:00",
			Basis: fmt.Sprintf("隔夜海外因子保守规则：obs_date +%d 天 09:00 +08:00（美股收盘后北京时间次日可得）", lag)}
	case series.IsMonthly(sid):
		lag := max(series.ReleaseLagDays(sid), 1)
		return Rule{LagDays: lag, Hour: 10, Minute: 0, TZ: "+08:00",
			Basis: fmt.Sprintf("月频保守规则：obs_date +%d 天 10:00 +08:00（按发布日近似，未给发布列）", lag)}
	default:
		lag := series.ReleaseLagDays(sid)
		return Rule{LagDays: lag, Hour: 18, Minute: 0, TZ: "+08:00",
			Basis: "境内日频保守规则：obs_date 当日 18:00 +08:00（收盘后披露）"}
	}
}

// RuleFromParams 用来源配置覆盖默认规则；未给出的字段回落到默认值。
func RuleFromParams(seriesID string, lagDays, hour, minute *int, tz string) Rule {
	r := DefaultRule(seriesID)
	if lagDays != nil {
		r.LagDays = *lagDays
	}
	if hour != nil {
		r.Hour = *hour
	}
	if minute != nil {
		r.Minute = *minute
	}
	if tz != "" {
		r.TZ = tz
	}
	r.Basis = "来源配置声明的发布时点（release_lag_days / publish_hour / tz_offset）"
	return r
}

// Describe 返回写入 release_time_rule 的可查字符串。
func (r Rule) Describe() string {
	return fmt.Sprintf("obs_date +%d 天 %02d:%02d %s；%s", r.LagDays, r.Hour, r.Minute, r.TZ, r.Basis)
}

// ReleaseTime 把观测日推导为带时区的 release_time（RFC3339）。
func (r Rule) ReleaseTime(obsDate time.Time) (time.Time, error) {
	loc, err := parseTZ(r.TZ)
	if err != nil {
		return time.Time{}, err
	}
	y, m, d := obsDate.Date()
	return time.Date(y, m, d+r.LagDays, r.Hour, r.Minute, 0, 0, loc), nil
}

func parseTZ(tz string) (*time.Location, error) {
	tz = strings.TrimSpace(tz)
	if tz == "" || tz == "+08:00" || tz == "Asia/Shanghai" {
		return time.FixedZone("+08:00", 8*3600), nil
	}
	if len(tz) == 6 && (tz[0] == '+' || tz[0] == '-') && tz[3] == ':' {
		sign := 1
		if tz[0] == '-' {
			sign = -1
		}
		hh, err1 := strconv.Atoi(tz[1:3])
		mm, err2 := strconv.Atoi(tz[4:6])
		if err1 != nil || err2 != nil {
			return nil, fmt.Errorf("非法时区偏移 %q", tz)
		}
		return time.FixedZone(tz, sign*(hh*3600+mm*60)), nil
	}
	loc, err := time.LoadLocation(tz)
	if err != nil {
		return nil, fmt.Errorf("未知时区 %q: %w", tz, err)
	}
	return loc, nil
}
