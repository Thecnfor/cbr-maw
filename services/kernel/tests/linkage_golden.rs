//! `capital_linkage` 黄金向量回归：三组配对逐点一致（容差 1e-8）+ 三条防退化断言。
//!
//! 权威口径：`contracts/golden-vectors/capital_linkage_reference.json`
//! （由旧版 Python `data/seed/gen_tool_golden.py` 在真实 PIT 库上生成）。
//!
//! 数据源：`data/seed/pit_real_obs.jsonl`（真实 PIT 库导出，27 序列 / 60313 条观测）。
//! 本测试用内存数据源（不建 DuckDB 库）：口径只依赖「日频并集日历 + 两序列取值」，
//! 与存储实现无关，因此不必付出分钟级落库成本。
//!
//! 防退化断言：
//! ① 水平口径（levels）会与黄金向量明显不一致 → 实现必须用 pct_change；
//! ② as_of 之后的数据扰动不影响 as_of 的结果（PIT 无泄漏）；
//! ③ 窗口内有效配对不足 → `insufficient_data`，且**不返回 0**。

use cbr_kernel::cfsi::CfsiSeries;
use cbr_kernel::numeric::sign_tie;
use cbr_kernel::tools::source::DataSource;
use cbr_kernel::tools::{linkage, ToolOutput};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::PathBuf;

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .unwrap()
}

fn seed_path() -> PathBuf {
    repo_root().join("data/seed/pit_real_obs.jsonl")
}

fn golden_path() -> PathBuf {
    repo_root().join("contracts/golden-vectors/capital_linkage_reference.json")
}

fn cfsi_golden_path() -> PathBuf {
    repo_root().join("contracts/golden-vectors/cfsi_stress_pca_q90_reference.json")
}

/// 内存数据源：从 seed JSONL 读全部序列，并给出日频并集日历与 CFSI 主值。
struct SeedSource {
    series: BTreeMap<String, Vec<(String, f64)>>,
    calendar: Vec<String>,
    cfsi: BTreeMap<String, f64>,
}

impl SeedSource {
    fn load(seed: &PathBuf) -> SeedSource {
        let raw = std::fs::read_to_string(seed).expect("read seed");
        let mut series: BTreeMap<String, Vec<(String, f64)>> = BTreeMap::new();
        let mut days: std::collections::BTreeSet<String> = std::collections::BTreeSet::new();
        for line in raw.lines() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            let record: Value = serde_json::from_str(line).expect("seed line is json");
            let series_id = record["series_id"].as_str().expect("series_id").to_string();
            let obs_date = record["obs_date"].as_str().expect("obs_date").to_string();
            let Some(value) = record["value"].as_f64() else {
                continue;
            };
            // 日历口径与内核一致：只有日频序列参与并集。
            if record["frequency"].as_str() == Some("daily") {
                days.insert(obs_date.clone());
            }
            series.entry(series_id).or_default().push((obs_date, value));
        }
        for rows in series.values_mut() {
            rows.sort_by(|a, b| a.0.cmp(&b.0));
        }
        SeedSource {
            series,
            calendar: days.into_iter().collect(),
            cfsi: BTreeMap::new(),
        }
    }

    /// 附上 CFSI 主值（用于领先性诊断）：来自 CFSI 黄金向量。
    fn with_cfsi(mut self, path: &PathBuf) -> SeedSource {
        let raw = std::fs::read_to_string(path).expect("read cfsi golden");
        let doc: Value = serde_json::from_str(&raw).expect("parse cfsi golden");
        for row in doc["rows"].as_array().expect("rows") {
            let day = row["date"].as_str().expect("date");
            if let Some(v) = row["cfsi"].as_f64() {
                self.cfsi.insert(day.to_string(), v);
            }
        }
        self
    }
}

impl DataSource for SeedSource {
    fn history(&self, series_id: &str, as_of: &str, lookback: Option<usize>) -> Vec<(String, f64)> {
        let Some(rows) = self.series.get(series_id) else {
            return Vec::new();
        };
        let mut out: Vec<(String, f64)> = rows
            .iter()
            .filter(|(day, _)| day.as_str() <= as_of)
            .cloned()
            .collect();
        if let Some(limit) = lookback {
            if limit > 0 && out.len() > limit {
                out = out.split_off(out.len() - limit);
            }
        }
        out
    }

    fn daily_calendar(&self, as_of: &str) -> Option<Vec<String>> {
        Some(
            self.calendar
                .iter()
                .filter(|d| d.as_str() <= as_of)
                .cloned()
                .collect(),
        )
    }

    fn cfsi_series(&self, as_of: &str) -> Option<CfsiSeries> {
        if self.cfsi.is_empty() {
            return None;
        }
        let calendar: Vec<String> = self
            .calendar
            .iter()
            .filter(|d| d.as_str() <= as_of)
            .cloned()
            .collect();
        let cfsi: Vec<Option<f64>> = calendar.iter().map(|d| self.cfsi.get(d).copied()).collect();
        Some(CfsiSeries {
            calendar,
            cfsi,
            dims: Vec::new(),
            loadings: BTreeMap::new(),
            tau: 0.0,
            q75: 0.0,
            q99: 0.0,
            train_end: "2021-12-31".to_string(),
            pca_applied: true,
        })
    }
}

fn invoke(source: &SeedSource, series_a: &str, series_b: &str, as_of: &str) -> ToolOutput {
    let mut params = serde_json::Map::new();
    params.insert("series_a".into(), Value::String(series_a.to_string()));
    params.insert("series_b".into(), Value::String(series_b.to_string()));
    let merged = cbr_kernel::tools::merge_params("capital_linkage", &params).expect("merge");
    linkage::compute(&merged, as_of, source).expect("capital_linkage")
}

const PAIRS: [(&str, &str, &str); 3] = [
    (
        "csi300_x_northbound",
        "market.cn_equity.csi300",
        "crossborder.flows.northbound_net",
    ),
    ("usdcny_x_vix", "market.fx.usdcny", "market.global.vix"),
    (
        "csi300_x_sp500",
        "market.cn_equity.csi300",
        "market.global.sp500",
    ),
];

/// 水平口径的滚动 Kendall tau（**仅用于防退化断言**：证明黄金向量锁定的是变化率口径）。
fn level_mode_tau(a: &[Option<f64>], b: &[Option<f64>], window: usize) -> Vec<Option<f64>> {
    let min_pairs = 15usize.max(window / 2);
    let mut out = vec![None; a.len()];
    for (i, slot) in out.iter_mut().enumerate().skip(window - 1) {
        let start = i + 1 - window;
        let pairs: Vec<(f64, f64)> = (start..=i)
            .filter_map(|j| match (a[j], b[j]) {
                (Some(x), Some(y)) => Some((x, y)),
                _ => None,
            })
            .collect();
        if pairs.len() < min_pairs {
            continue;
        }
        let k = pairs.len();
        let mut acc = 0.0f64;
        for p in 0..k {
            for q in (p + 1)..k {
                // 并列取 0（numpy `np.sign` 语义；`f64::signum` 会把 ±0.0 记成 ±1）。
                let sa = sign_tie(pairs[p].0 - pairs[q].0);
                let sb = sign_tie(pairs[p].1 - pairs[q].1);
                acc += sa * sb;
            }
        }
        *slot = Some(acc / ((k * (k - 1)) as f64 / 2.0));
    }
    out
}

/// 三组配对的 tau / z 逐点一致（容差 1e-8），训练期统计与前瞻剖面也对齐。
#[test]
fn capital_linkage_matches_golden_vector() {
    let seed = seed_path();
    let golden = golden_path();
    let cfsi_golden = cfsi_golden_path();
    if !seed.exists() || !golden.exists() {
        eprintln!("跳过：缺少 seed 或 golden");
        return;
    }
    let source = SeedSource::load(&seed).with_cfsi(&cfsi_golden);
    let doc: Value = serde_json::from_str(&std::fs::read_to_string(&golden).expect("read golden"))
        .expect("json");
    let tolerance = 1e-8;

    let mut total_checked = 0usize;
    for (pair_name, series_a, series_b) in PAIRS {
        let pair = &doc["pairs"][pair_name];
        let rows = pair["rows"].as_array().expect("golden rows");
        let computed =
            linkage::series(&source, series_a, series_b, 90, "2100-01-01").expect("linkage series");
        let index_of: BTreeMap<&str, usize> = computed
            .calendar
            .iter()
            .enumerate()
            .map(|(i, d)| (d.as_str(), i))
            .collect();

        let mut checked = 0usize;
        let mut mismatches: Vec<String> = Vec::new();
        for row in rows {
            let Some(day) = row["date"].as_str() else {
                continue;
            };
            let Some(&idx) = index_of.get(day) else {
                continue;
            };
            checked += 1;
            let got_tau = computed.tau[idx];
            let got_z = computed.z[idx];
            match (row["tau"].as_f64(), got_tau) {
                (None, None) => {}
                (Some(e), Some(g)) => {
                    if (e - g).abs() > tolerance && mismatches.len() < 10 {
                        mismatches.push(format!("{day} tau: got {g:.12} expected {e:.12}"));
                    }
                }
                (e, g) => {
                    if mismatches.len() < 10 {
                        mismatches.push(format!("{day} tau: got {g:?} expected {e:?}"));
                    }
                }
            }
            match (row["z"].as_f64(), got_z) {
                (None, None) => {}
                (Some(e), Some(g)) => {
                    if (e - g).abs() > tolerance && mismatches.len() < 10 {
                        mismatches.push(format!("{day} z: got {g:.12} expected {e:.12}"));
                    }
                }
                (e, g) => {
                    if mismatches.len() < 10 {
                        mismatches.push(format!("{day} z: got {g:?} expected {e:?}"));
                    }
                }
            }
        }
        assert!(
            checked > 2800,
            "{pair_name}: 只比对到 {checked} 行，日历对不上"
        );
        assert!(
            mismatches.is_empty(),
            "{pair_name} 与黄金向量不一致：\n{}",
            mismatches.join("\n")
        );

        // 训练期统计（冻结口径）
        let mean = pair["train_mean"].as_f64().expect("train_mean");
        let std = pair["train_std"].as_f64().expect("train_std");
        assert!(
            (computed.train_mean - mean).abs() <= tolerance,
            "{pair_name} train_mean: got {} expected {mean}",
            computed.train_mean
        );
        assert!(
            (computed.train_std - std).abs() <= tolerance,
            "{pair_name} train_std: got {} expected {std}",
            computed.train_std
        );
        total_checked += checked;
        eprintln!("capital_linkage[{pair_name}]：{checked} 行 tau/z 逐点一致（容差 {tolerance}）");
    }
    assert!(total_checked > 8400, "总比对行数异常: {total_checked}");
}

/// 领先性剖面与黄金向量一致（golden 的 corr 保留 6 位小数，容差 1e-6）。
#[test]
fn capital_linkage_lead_profile_matches_golden() {
    let seed = seed_path();
    let golden = golden_path();
    let cfsi_golden = cfsi_golden_path();
    if !seed.exists() || !golden.exists() {
        eprintln!("跳过：缺少 seed 或 golden");
        return;
    }
    let source = SeedSource::load(&seed).with_cfsi(&cfsi_golden);
    let doc: Value = serde_json::from_str(&std::fs::read_to_string(&golden).expect("read golden"))
        .expect("json");
    for (pair_name, series_a, series_b) in PAIRS {
        let pair = &doc["pairs"][pair_name];
        let computed =
            linkage::series(&source, series_a, series_b, 90, "2100-01-01").expect("linkage series");
        let cfsi_map = source.cfsi.clone();
        let (profile, lead_type) =
            linkage::lead_profile(&computed.calendar, &computed.tau, &cfsi_map);
        for (h, corr) in &profile {
            let expected = pair["lead_profile"]
                .as_array()
                .expect("lead_profile")
                .iter()
                .find(|item| item["h"].as_u64() == Some(*h as u64))
                .and_then(|item| item["corr"].as_f64())
                .expect("corr");
            let got = corr.expect("corr computed");
            assert!(
                (got - expected).abs() <= 1e-6,
                "{pair_name} h={h}: got {got:.8} expected {expected:.8}"
            );
        }
        // 峰值 h ≥ 20 → leading；否则 contemporaneous
        let peak_h = profile
            .iter()
            .filter_map(|(h, c)| c.map(|v| (*h, v)))
            .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap())
            .map(|(h, _)| h)
            .expect("peak");
        let expected_type = if peak_h >= 20 {
            "leading"
        } else {
            "contemporaneous"
        };
        assert_eq!(lead_type, expected_type, "{pair_name} lead_type");
        eprintln!("capital_linkage[{pair_name}]：lead_profile 一致，峰值 h={peak_h} → {lead_type}");
    }
}

/// 防退化 ①：水平口径（levels）与黄金向量明显不同 → 实现必须走 pct_change。
#[test]
fn capital_linkage_level_mode_would_fail_golden() {
    let seed = seed_path();
    let golden = golden_path();
    if !seed.exists() || !golden.exists() {
        eprintln!("跳过：缺少 seed 或 golden");
        return;
    }
    let source = SeedSource::load(&seed);
    let doc: Value = serde_json::from_str(&std::fs::read_to_string(&golden).expect("read golden"))
        .expect("json");
    let (pair_name, series_a, series_b) = PAIRS[0];
    let pair = &doc["pairs"][pair_name];

    // 水平口径：直接对水平值算滚动 Kendall tau（不做 pct_change）。
    let calendar = &source.calendar;
    let map_a: BTreeMap<String, f64> = source.series[series_a].iter().cloned().collect();
    let map_b: BTreeMap<String, f64> = source.series[series_b].iter().cloned().collect();
    let a: Vec<Option<f64>> = calendar.iter().map(|d| map_a.get(d).copied()).collect();
    let b: Vec<Option<f64>> = calendar.iter().map(|d| map_b.get(d).copied()).collect();
    let level_tau = level_mode_tau(&a, &b, 90);

    // 黄金向量是变化率口径：水平口径必须对不上（否则说明黄金向量本身可被水平口径复现）。
    let mut level_differs = 0usize;
    let mut compared = 0usize;
    for row in pair["rows"].as_array().expect("rows") {
        let Some(day) = row["date"].as_str() else {
            continue;
        };
        let Some(expected) = row["tau"].as_f64() else {
            continue;
        };
        let Some(idx) = calendar.iter().position(|d| d == day) else {
            continue;
        };
        let Some(got) = level_tau[idx] else { continue };
        compared += 1;
        if (got - expected).abs() > 1e-3 {
            level_differs += 1;
        }
    }
    assert!(compared > 2000, "比对行数异常: {compared}");
    assert!(
        level_differs * 10 > compared,
        "水平口径与黄金向量的差异过小（{level_differs}/{compared}）——口径校验失效"
    );
    eprintln!("capital_linkage：水平口径与黄金向量在 {level_differs}/{compared} 行不一致（口径已锁定为 pct_change）");
}

/// 防退化 ②：as_of 之后的数据扰动不影响 as_of 的结果（PIT 无泄漏）。
#[test]
fn capital_linkage_ignores_data_after_as_of() {
    let seed = seed_path();
    if !seed.exists() {
        eprintln!("跳过：缺少 seed");
        return;
    }
    let source = SeedSource::load(&seed);
    let as_of = "2024-06-28";
    let (series_a, series_b) = (PAIRS[0].1, PAIRS[0].2);

    let base = invoke(&source, series_a, series_b, as_of);

    // 扰动 as_of 之后的数据（放大 3 倍并加偏移）。
    let mut polluted = SeedSource::load(&seed);
    for series_id in [series_a, series_b] {
        if let Some(rows) = polluted.series.get_mut(series_id) {
            for (day, value) in rows.iter_mut() {
                if day.as_str() > as_of {
                    *value = *value * 3.0 + 11.0;
                }
            }
        }
    }
    let after = invoke(&polluted, series_a, series_b, as_of);

    assert_eq!(
        base.data["kendall_tau"], after.data["kendall_tau"],
        "as_of 之后的数据泄漏进了结果"
    );
    assert_eq!(base.data["z_score"], after.data["z_score"]);
    eprintln!("capital_linkage：as_of 之后的数据扰动未影响结果（PIT 校验通过）");
}

/// 防退化 ③：窗口内有效配对不足 → `insufficient_data`，且不返回 0。
#[test]
fn capital_linkage_insufficient_data_is_not_zero() {
    let mut source = SeedSource::load(&seed_path());
    let as_of = "2024-06-28";
    let (series_a, series_b) = (PAIRS[0].1, PAIRS[0].2);
    // 只保留每 3 个观测中的 1 个 → 窗口有效配对 < 50%。
    let thin: Vec<String> = source.calendar.clone();
    for series_id in [series_a, series_b] {
        if let Some(rows) = source.series.get_mut(series_id) {
            let mut out: Vec<(String, f64)> = Vec::new();
            for (i, row) in rows.iter().enumerate() {
                if i % 3 == 0 && row.0.as_str() <= as_of {
                    out.push(row.clone());
                }
            }
            *rows = out;
        }
    }
    let _ = thin;
    let out = invoke(&source, series_a, series_b, as_of);
    assert_eq!(out.data["level"], "insufficient_data");
    assert!(
        out.data["kendall_tau"].is_null(),
        "数据不足时不得返回数值（更不能是 0）"
    );
    assert!(out.value.is_none(), "数据不足时 evidence.value 必须为空");
    let limitations = out.data["limitations"].as_array().expect("limitations");
    assert!(
        limitations
            .iter()
            .any(|l| l.as_str().unwrap_or("").contains("缺失 ≠ 零值")),
        "必须显式说明缺失不等于零值"
    );
    eprintln!("capital_linkage：有效配对不足 → insufficient_data（未返回 0）");
}
