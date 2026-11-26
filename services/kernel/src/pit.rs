//! 序列目录与 PIT 时点规则（对齐 `docs/05-数据抓取与时点设计.md` §6）。

use serde_json::{json, Value};

/// 序列目录条目（真源：`data/samples/series_catalog.json`）。
#[derive(Debug, Clone)]
pub struct SeriesSpec {
    pub series_id: String,
    pub name: String,
    pub domain: String,
    pub unit: String,
    pub frequency: String,
    pub release_lag_days: i64,
    pub derived: bool,
}

/// 隔夜海外因子：观测日次日 09:00 (+08:00)。
pub const OVERSEAS_SERIES: [&str; 4] = [
    "market.global.vix",
    "market.global.sp500",
    "market.global.us10y",
    "market.global.dxy",
];

/// 派生序列 → 输入序列（顺序有意义：diff 类为 (左, 右)）。
pub fn derived_inputs(series_id: &str) -> Option<(&'static str, Option<&'static str>)> {
    match series_id {
        "market.cn_bond.term_spread" => {
            Some(("market.cn_bond.cgb_10y", Some("market.cn_bond.cgb_2y")))
        }
        "market.global.cn_us_spread" => {
            Some(("market.cn_bond.cgb_10y", Some("market.global.us10y")))
        }
        "market.fx.cnh_cny_gap" => Some(("market.fx.usdcnh", Some("market.fx.usdcny"))),
        "market.cn_bond.cgb_index" => Some(("market.cn_bond.cgb_10y", None)),
        _ => None,
    }
}

pub fn derived_unit(series_id: &str) -> &'static str {
    match series_id {
        "market.cn_bond.term_spread" | "market.global.cn_us_spread" => "bp",
        "market.fx.cnh_cny_gap" => "pips",
        _ => "点",
    }
}

/// 全部派生序列（写后重算的默认目标集合）。
pub const DERIVED_SERIES: [&str; 4] = [
    "market.cn_bond.term_spread",
    "market.global.cn_us_spread",
    "market.fx.cnh_cny_gap",
    "market.cn_bond.cgb_index",
];

/// 序列目录：从 `resource_home/data/samples/series_catalog.json` 读取，缺失则用内置兜底。
#[derive(Debug, Clone, Default)]
pub struct SeriesCatalog {
    entries: std::collections::BTreeMap<String, SeriesSpec>,
}

impl SeriesCatalog {
    pub fn load(resource_home: &str) -> Self {
        let candidates = [
            format!("{resource_home}/data/samples/series_catalog.json"),
            format!("{resource_home}/data/series_catalog.json"),
        ];
        for path in candidates {
            if let Ok(raw) = std::fs::read_to_string(&path) {
                if let Ok(value) = serde_json::from_str::<Value>(&raw) {
                    if let Some(map) = value.as_object() {
                        let mut entries = std::collections::BTreeMap::new();
                        for (series_id, spec) in map {
                            entries.insert(
                                series_id.clone(),
                                SeriesSpec {
                                    series_id: series_id.clone(),
                                    name: spec["name"].as_str().unwrap_or(series_id).to_string(),
                                    domain: spec["domain"].as_str().unwrap_or("").to_string(),
                                    unit: spec["unit"].as_str().unwrap_or("").to_string(),
                                    frequency: spec["frequency"]
                                        .as_str()
                                        .unwrap_or("daily")
                                        .to_string(),
                                    release_lag_days: spec["release_lag_days"]
                                        .as_i64()
                                        .unwrap_or(0),
                                    derived: spec["derived"].as_bool().unwrap_or(false),
                                },
                            );
                        }
                        if !entries.is_empty() {
                            return Self { entries };
                        }
                    }
                }
            }
        }
        Self::builtin()
    }

    /// 内置兜底目录（与 `data/samples/series_catalog.json` 的时点字段一致）。
    pub fn builtin() -> Self {
        let specs: Vec<(&str, &str, &str, &str, &str, i64, bool)> = vec![
            (
                "market.cn_equity.csi300",
                "沪深300指数",
                "market.cn_equity",
                "点",
                "daily",
                0,
                false,
            ),
            (
                "market.cn_equity.csi500",
                "中证500指数",
                "market.cn_equity",
                "点",
                "daily",
                0,
                false,
            ),
            (
                "market.cn_equity.turnover",
                "沪深两市成交额",
                "market.cn_equity",
                "亿元",
                "daily",
                0,
                false,
            ),
            (
                "market.cn_bond.cgb_2y",
                "2年期国债到期收益率",
                "market.cn_bond",
                "%",
                "daily",
                0,
                false,
            ),
            (
                "market.cn_bond.cgb_10y",
                "10年期国债到期收益率",
                "market.cn_bond",
                "%",
                "daily",
                0,
                false,
            ),
            (
                "market.cn_bond.repo_7d",
                "银行间7天质押式回购利率",
                "market.cn_bond",
                "%",
                "daily",
                0,
                false,
            ),
            (
                "market.cn_bond.term_spread",
                "10Y-2Y国债期限利差",
                "market.cn_bond",
                "bp",
                "daily",
                0,
                true,
            ),
            (
                "market.cn_bond.cgb_index",
                "中债国债全价指数",
                "market.cn_bond",
                "点",
                "daily",
                0,
                true,
            ),
            (
                "rates.credit.aa_spread",
                "AA级中票信用利差",
                "rates.credit",
                "bp",
                "daily",
                0,
                false,
            ),
            (
                "market.fx.usdcny",
                "美元兑人民币在岸即期汇率",
                "market.fx",
                "CNY/USD",
                "daily",
                0,
                false,
            ),
            (
                "market.fx.usdcnh",
                "美元兑离岸人民币即期汇率",
                "market.fx",
                "CNH/USD",
                "daily",
                0,
                false,
            ),
            (
                "market.fx.cnh_cny_gap",
                "离岸-在岸人民币汇差",
                "market.fx",
                "pips",
                "daily",
                0,
                true,
            ),
            (
                "market.global.dxy",
                "美元指数",
                "market.global",
                "点",
                "daily",
                0,
                false,
            ),
            (
                "market.global.vix",
                "VIX恐慌指数",
                "market.global",
                "点",
                "daily",
                0,
                false,
            ),
            (
                "market.global.sp500",
                "标普500指数",
                "market.global",
                "点",
                "daily",
                0,
                false,
            ),
            (
                "market.global.us10y",
                "美国10年期国债收益率",
                "market.global",
                "%",
                "daily",
                0,
                false,
            ),
            (
                "market.global.cn_us_spread",
                "中美10年期国债利差",
                "market.global",
                "bp",
                "daily",
                0,
                true,
            ),
            (
                "crossborder.flows.northbound_net",
                "北向资金净流入",
                "crossborder.flows",
                "亿元",
                "daily",
                0,
                false,
            ),
            (
                "crossborder.flows.southbound_net",
                "南向资金净流入",
                "crossborder.flows",
                "亿元",
                "daily",
                0,
                false,
            ),
            (
                "crossborder.holdings.northbound_hold",
                "北向持股总市值",
                "crossborder.holdings",
                "亿元",
                "daily",
                0,
                false,
            ),
            (
                "crossborder.holdings.southbound_hold",
                "南向持股总市值",
                "crossborder.holdings",
                "亿元",
                "daily",
                0,
                false,
            ),
            (
                "crossborder.flows.ah_premium",
                "AH股溢价指数",
                "crossborder.flows",
                "点",
                "daily",
                0,
                false,
            ),
            (
                "macro.pmi.manufacturing",
                "制造业PMI",
                "macro",
                "点",
                "monthly",
                1,
                false,
            ),
            (
                "macro.cpi.yoy",
                "CPI同比",
                "macro",
                "%",
                "monthly",
                10,
                false,
            ),
            (
                "macro.social_financing.yoy",
                "社融存量同比",
                "macro",
                "%",
                "monthly",
                12,
                false,
            ),
            (
                "macro.fx_reserves",
                "外汇储备",
                "macro",
                "亿美元",
                "monthly",
                7,
                false,
            ),
            (
                "macro.lpr.1y",
                "1年期贷款市场报价利率(LPR)",
                "macro",
                "%",
                "monthly",
                0,
                false,
            ),
        ];
        let mut entries = std::collections::BTreeMap::new();
        for (id, name, domain, unit, freq, lag, derived) in specs {
            entries.insert(
                id.to_string(),
                SeriesSpec {
                    series_id: id.to_string(),
                    name: name.to_string(),
                    domain: domain.to_string(),
                    unit: unit.to_string(),
                    frequency: freq.to_string(),
                    release_lag_days: lag,
                    derived,
                },
            );
        }
        Self { entries }
    }

    pub fn get(&self, series_id: &str) -> Option<&SeriesSpec> {
        self.entries.get(series_id)
    }

    pub fn all(&self) -> impl Iterator<Item = &SeriesSpec> {
        self.entries.values()
    }

    pub fn to_json(&self) -> Value {
        let mut map = serde_json::Map::new();
        for spec in self.entries.values() {
            map.insert(
                spec.series_id.clone(),
                json!({
                    "name": spec.name,
                    "domain": spec.domain,
                    "unit": spec.unit,
                    "frequency": spec.frequency,
                    "release_lag_days": spec.release_lag_days,
                    "derived": spec.derived,
                }),
            );
        }
        Value::Object(map)
    }
}

/// `release_time` 推导规则（§6.2 保守推导）。
#[derive(Debug, Clone, Copy)]
pub struct ReleaseRule {
    pub lag_days: i64,
    pub hour: u32,
    pub minute: u32,
    pub tz_offset_minutes: i32,
}

impl ReleaseRule {
    /// 由显式声明推导（`pit.ingest.params.declared`）。
    pub fn from_declared(declared: &Value, fallback: ReleaseRule) -> Self {
        ReleaseRule {
            lag_days: declared["release_lag_days"]
                .as_i64()
                .unwrap_or(fallback.lag_days),
            hour: declared["publish_hour"]
                .as_u64()
                .map(|v| v as u32)
                .unwrap_or(fallback.hour),
            minute: declared["publish_minute"]
                .as_u64()
                .map(|v| v as u32)
                .unwrap_or(fallback.minute),
            tz_offset_minutes: declared["tz_offset"]
                .as_str()
                .and_then(parse_tz_offset)
                .unwrap_or(fallback.tz_offset_minutes),
        }
    }

    /// 人类可读规则串，写入 `release_time_rule`。
    pub fn describe(&self) -> String {
        format!(
            "obs_date{:+} {}:{:02} {}",
            self.lag_days,
            self.hour,
            self.minute,
            format_tz(self.tz_offset_minutes)
        )
    }

    /// 给定观测日，推导可得时点（UTC 朴素字符串，供 DuckDB TIMESTAMP 比较）。
    pub fn apply(&self, obs_date: &str) -> Option<String> {
        let day =
            chrono::NaiveDate::parse_from_str(&obs_date[..10.min(obs_date.len())], "%Y-%m-%d")
                .ok()?;
        let shifted = day.checked_add_signed(chrono::Duration::days(self.lag_days))?;
        let naive = shifted.and_hms_opt(self.hour, self.minute, 0)?;
        let utc = naive - chrono::Duration::minutes(self.tz_offset_minutes as i64);
        Some(utc.format("%Y-%m-%d %H:%M:%S").to_string())
    }
}

/// 按序列目录的保守规则（§6.2）。
pub fn default_rule(series_id: &str, catalog: &SeriesCatalog) -> ReleaseRule {
    if OVERSEAS_SERIES.contains(&series_id) {
        return ReleaseRule {
            lag_days: 1,
            hour: 9,
            minute: 0,
            tz_offset_minutes: 480,
        };
    }
    match catalog.get(series_id) {
        Some(spec) if spec.frequency == "monthly" => ReleaseRule {
            lag_days: spec.release_lag_days.max(10),
            hour: 10,
            minute: 0,
            tz_offset_minutes: 480,
        },
        Some(spec) => ReleaseRule {
            lag_days: spec.release_lag_days,
            hour: 18,
            minute: 0,
            tz_offset_minutes: 480,
        },
        None => ReleaseRule {
            lag_days: 0,
            hour: 18,
            minute: 0,
            tz_offset_minutes: 480,
        },
    }
}

pub fn parse_tz_offset(raw: &str) -> Option<i32> {
    let raw = raw.trim();
    let sign = if raw.starts_with('-') { -1 } else { 1 };
    let body = raw.trim_start_matches(['+', '-']);
    let (hours, minutes) = match body.split_once(':') {
        Some((h, m)) => (h.parse::<i32>().ok()?, m.parse::<i32>().ok()?),
        None => (body.parse::<i32>().ok()?, 0),
    };
    Some(sign * (hours * 60 + minutes))
}

pub fn format_tz(minutes: i32) -> String {
    let sign = if minutes < 0 { '-' } else { '+' };
    let abs = minutes.abs();
    format!("{sign}{:02}:{:02}", abs / 60, abs % 60)
}

/// `as_of` 归一为当日 23:59:59（继承旧 `as_of_timestamp` 的日粒度语义）。
pub fn as_of_end_of_day(as_of: &str) -> String {
    let day = as_of.get(..10).unwrap_or(as_of);
    format!("{day} 23:59:59")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn domestic_daily_rule_is_1800_same_day() {
        let catalog = SeriesCatalog::builtin();
        let rule = default_rule("market.cn_equity.csi300", &catalog);
        assert_eq!(rule.describe(), "obs_date+0 18:00 +08:00");
        // 2026-06-30 18:00 +08:00 == 2026-06-30 10:00 UTC
        assert_eq!(rule.apply("2026-06-30").unwrap(), "2026-06-30 10:00:00");
    }

    #[test]
    fn overseas_rule_is_next_day_0900() {
        let catalog = SeriesCatalog::builtin();
        let rule = default_rule("market.global.vix", &catalog);
        assert_eq!(rule.apply("2026-06-30").unwrap(), "2026-07-01 01:00:00");
    }

    #[test]
    fn monthly_rule_uses_at_least_ten_days() {
        let catalog = SeriesCatalog::builtin();
        assert_eq!(default_rule("macro.fx_reserves", &catalog).lag_days, 10);
        assert_eq!(default_rule("macro.cpi.yoy", &catalog).lag_days, 10);
        assert_eq!(
            default_rule("macro.social_financing.yoy", &catalog).lag_days,
            12
        );
    }
}
