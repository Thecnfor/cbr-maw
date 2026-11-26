//! `dimension_dispersion` 黄金向量回归：逐点一致（容差 1e-8）+ 结构表回归。
//!
//! 权威口径：`contracts/golden-vectors/dimension_dispersion_reference.json`
//! （由旧版 Python `data/seed/gen_tool_golden.py` 在真实 PIT 库上生成）。
//!
//! 数据源：`data/seed/pit_real_obs.jsonl`（真实 PIT 库导出，27 序列 / 60313 条观测）。
//!
//! 说明：种子数据**原样落库**（含旧版混合精度的派生序列），不调用
//! `ingest::recompute_derived` —— 黄金向量就是在这些存储值上算出来的，
//! 重算只会把「变化 >1e-9」的行改写掉，反而偏离黄金口径。
//! 派生重算本身的一致性由 `tests/golden.rs` 单独覆盖。

use cbr_kernel::pit::SeriesCatalog;
use cbr_kernel::tools::dispersion;
use cbr_kernel::workspace::Workspace;
use serde_json::Value;
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
    repo_root().join("contracts/golden-vectors/dimension_dispersion_reference.json")
}

/// 把 seed JSONL 原样写入工作区（批量 INSERT，避免逐行 fsync）。
fn seed_workspace(ws: &Workspace, seed: &PathBuf) -> usize {
    let raw = std::fs::read_to_string(seed).expect("read seed");
    let mut written = 0usize;
    let mut batch: Vec<String> = Vec::with_capacity(2048);
    let flush = |ws: &Workspace, batch: &mut Vec<String>| -> usize {
        if batch.is_empty() {
            return 0;
        }
        let n = batch.len();
        let sql = format!(
            "INSERT OR REPLACE INTO series_obs(series_id, obs_date, value, release_time, source, unit) \
             VALUES {}",
            batch.join(",")
        );
        ws.conn.execute_batch(&sql).expect("insert seed batch");
        batch.clear();
        n
    };
    for line in raw.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let record: Value = serde_json::from_str(line).expect("seed line is json");
        let series_id = record["series_id"].as_str().expect("series_id");
        let obs_date = record["obs_date"].as_str().expect("obs_date");
        let Some(value) = record["value"].as_f64() else {
            continue;
        };
        let release_time = record["release_time"].as_str().expect("release_time");
        let esc = |s: &str| s.replace('\'', "''");
        batch.push(format!(
            "('{}', CAST('{}' AS DATE), {:?}, CAST('{}' AS TIMESTAMP), '{}', '{}')",
            esc(series_id),
            esc(obs_date),
            value,
            esc(release_time),
            esc(record["source"].as_str().unwrap_or("")),
            esc(record["unit"].as_str().unwrap_or("")),
        ));
        written += 1;
        if batch.len() >= 2048 {
            flush(ws, &mut batch);
        }
    }
    flush(ws, &mut batch);
    written
}

/// dispersion / z / dominant_dim 与黄金向量逐点一致（容差 1e-8）。
#[test]
fn dimension_dispersion_matches_golden_vector() {
    let seed = seed_path();
    let golden = golden_path();
    if !seed.exists() || !golden.exists() {
        eprintln!("跳过：缺少 seed 或 golden");
        return;
    }
    let db_path =
        std::env::temp_dir().join(format!("cbr-disp-golden-{}.duckdb", std::process::id()));
    let _ = std::fs::remove_file(&db_path);
    let ws = Workspace::open(&db_path).expect("open workspace");
    let seeded = seed_workspace(&ws, &seed);
    assert!(seeded > 60_000, "seed 行数异常: {seeded}");

    let catalog = SeriesCatalog::load(&repo_root().to_string_lossy());
    let computed = cbr_kernel::cfsi::series(&ws, "2100-01-01", &catalog).expect("cfsi series");
    let structure = dispersion::series(&computed);

    let raw = std::fs::read_to_string(&golden).expect("read golden");
    let doc: Value = serde_json::from_str(&raw).expect("parse golden");
    let tolerance = 1e-8;
    let index_of: std::collections::BTreeMap<&str, usize> = computed
        .calendar
        .iter()
        .enumerate()
        .map(|(i, d)| (d.as_str(), i))
        .collect();

    let mut checked = 0usize;
    let mut disp_mismatches: Vec<String> = Vec::new();
    let mut z_mismatches: Vec<String> = Vec::new();
    let mut dom_mismatches: Vec<String> = Vec::new();
    let mut null_mismatches: Vec<String> = Vec::new();

    for row in doc["rows"].as_array().expect("golden rows") {
        let Some(day) = row["date"].as_str() else {
            continue;
        };
        let Some(&idx) = index_of.get(day) else {
            continue;
        };
        checked += 1;

        match (row["dispersion"].as_f64(), structure.dispersion[idx]) {
            (None, None) => {}
            (Some(e), Some(g)) => {
                if (e - g).abs() > tolerance && disp_mismatches.len() < 10 {
                    disp_mismatches.push(format!("{day}: got {g:.12} expected {e:.12}"));
                }
            }
            (e, g) => {
                if null_mismatches.len() < 10 {
                    null_mismatches.push(format!("{day} dispersion: got {g:?} expected {e:?}"));
                }
            }
        }

        match (row["z"].as_f64(), structure.z[idx]) {
            (None, None) => {}
            (Some(e), Some(g)) => {
                if (e - g).abs() > tolerance && z_mismatches.len() < 10 {
                    z_mismatches.push(format!("{day}: got {g:.12} expected {e:.12}"));
                }
            }
            (e, g) => {
                if null_mismatches.len() < 10 {
                    null_mismatches.push(format!("{day} z: got {g:?} expected {e:?}"));
                }
            }
        }

        let expected_dom = row["dominant_dim"].as_str().map(str::to_string);
        let got_dom = structure.dominant[idx].clone();
        if expected_dom != got_dom && dom_mismatches.len() < 10 {
            dom_mismatches.push(format!("{day}: got {got_dom:?} expected {expected_dom:?}"));
        }
    }

    assert!(checked > 2800, "只比对到 {checked} 行，日历对不上");
    assert!(
        disp_mismatches.is_empty(),
        "dispersion 与黄金向量不一致：\n{}",
        disp_mismatches.join("\n")
    );
    assert!(
        z_mismatches.is_empty(),
        "z 与黄金向量不一致：\n{}",
        z_mismatches.join("\n")
    );
    assert!(
        dom_mismatches.is_empty(),
        "dominant_dim 与黄金向量不一致：\n{}",
        dom_mismatches.join("\n")
    );
    assert!(
        null_mismatches.is_empty(),
        "缺失状态与黄金向量不一致：\n{}",
        null_mismatches.join("\n")
    );

    // 训练期冻结统计（golden 直接给了 train_mean / train_std）。
    let mean = doc["train_mean"].as_f64().expect("train_mean");
    let std = doc["train_std"].as_f64().expect("train_std");
    assert!(
        (structure.train_mean - mean).abs() <= tolerance,
        "train_mean: got {} expected {mean}",
        structure.train_mean
    );
    assert!(
        (structure.train_std - std).abs() <= tolerance,
        "train_std: got {} expected {std}",
        structure.train_std
    );

    eprintln!(
        "dimension_dispersion：{checked} 行 dispersion/z/dominant_dim 逐点一致（容差 {tolerance}）"
    );
    drop(ws);
    let _ = std::fs::remove_file(&db_path);
}
