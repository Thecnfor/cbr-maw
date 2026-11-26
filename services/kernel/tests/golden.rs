//! 黄金向量回归：CFSI 逐日与旧版 Python 实现在真实 PIT 库上的结果逐点一致（容差 1e-8）。
//!
//! 数据源：`data/seed/pit_real_obs.jsonl`（真实 PIT 库导出，27 序列 / 60313 条观测）。
//! 若该文件不存在，测试跳过（不伪造数据）。
//!
//! 派生序列不直接入库，由内核重算 —— 同时验证派生重算与旧版一致。

use cbr_kernel::{cfsi, ingest, pit, workspace::Workspace};
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
    repo_root().join("contracts/golden-vectors/cfsi_stress_pca_q90_reference.json")
}

/// 把 seed JSONL 原样写入临时工作区（含派生序列的历史值）。
///
/// 说明：旧版 PIT 库里派生序列是**混合精度**的 —— 2615 行由导入落库（`38.05`），
/// 262 行由 `derive.recompute_derived` 写回（`38.050000000000004`）。
/// 黄金向量是在这些存储值上算出来的，因此回归测试必须原样复现输入，
/// 否则恰好落在并列分位上的 97 天会错位一格。派生重算本身另有独立测试。
fn seed_workspace(ws: &Workspace, seed: &PathBuf, include_derived: bool) -> usize {
    let raw = std::fs::read_to_string(seed).expect("read seed");
    let derived = [
        "market.cn_bond.term_spread",
        "market.global.cn_us_spread",
        "market.fx.cnh_cny_gap",
        "market.cn_bond.cgb_index",
    ];
    let mut written = 0;
    // 批量写入：逐行 INSERT 在 NTFS 上会因每行一次 WAL fsync 而退化为分钟级。
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
        if !include_derived && derived.contains(&series_id) {
            continue;
        }
        let obs_date = record["obs_date"].as_str().expect("obs_date");
        let Some(value) = record["value"].as_f64() else {
            continue;
        };
        let release_time = record["release_time"].as_str().expect("release_time");
        // 值一律按 f64 字面量内联（与黄金向量生成时的存储值完全一致）；字符串做最小转义。
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

/// 解析 `"2018-09-04: got 70.1055099648 expected 70.0468933200"`。
fn parse_mismatch(line: &str) -> (String, f64, f64) {
    let (day, rest) = line.split_once(':').expect("mismatch format");
    let rest = rest.trim();
    let rest = rest.strip_prefix("got ").expect("got prefix");
    let (got, rest) = rest.split_once(" expected ").expect("expected sep");
    (
        day.trim().to_string(),
        got.trim().parse().expect("got f64"),
        rest.trim().parse().expect("expected f64"),
    )
}

#[test]
fn cfsi_matches_golden_vector_row_by_row() {
    let seed = seed_path();
    let golden = golden_path();
    if !seed.exists() || !golden.exists() {
        eprintln!("跳过：缺少 {} 或 {}", seed.display(), golden.display());
        return;
    }

    let db_path =
        std::env::temp_dir().join(format!("cbr-kernel-golden-{}.duckdb", std::process::id()));
    let _ = std::fs::remove_file(&db_path);
    let ws = Workspace::open(&db_path).expect("open workspace");
    let seeded = seed_workspace(&ws, &seed, true);
    assert!(seeded > 60_000, "seed 行数异常: {seeded}");

    let catalog = pit::SeriesCatalog::load(&repo_root().to_string_lossy());
    // 派生重算只会改写「缺失或值变化 >1e-9」的行，因此库内存储值原样保留。
    ingest::recompute_derived(&ws, &catalog).expect("recompute derived");

    // 全量计算（as_of 取未来，等价于旧版全样本）
    let computed = cfsi::series(&ws, "2100-01-01", &catalog).expect("compute cfsi series");

    let raw = std::fs::read_to_string(&golden).expect("read golden");
    let doc: Value = serde_json::from_str(&raw).expect("parse golden");
    let tolerance = doc["tolerance"].as_f64().unwrap_or(1e-8);
    let rows = doc["rows"].as_array().expect("golden rows");
    assert!(rows.len() > 2800, "黄金向量行数异常: {}", rows.len());

    let index_of: std::collections::BTreeMap<&str, usize> = computed
        .calendar
        .iter()
        .enumerate()
        .map(|(i, d)| (d.as_str(), i))
        .collect();

    let mut checked = 0usize;
    let mut cfsi_mismatches: Vec<String> = Vec::new();
    let mut dim_mismatches: Vec<String> = Vec::new();
    let dim_keys = [
        ("dim_equity", "equity"),
        ("dim_bond", "bond"),
        ("dim_credit", "credit"),
        ("dim_fx", "fx"),
        ("dim_crossborder", "crossborder"),
        ("dim_global", "global"),
    ];

    for row in rows {
        let Some(day) = row["date"].as_str() else {
            continue;
        };
        let Some(&idx) = index_of.get(day) else {
            continue;
        };
        checked += 1;

        // CFSI
        let expected = row["cfsi"].as_f64();
        let actual = computed.cfsi[idx];
        match (expected, actual) {
            (None, None) => {}
            (Some(e), Some(a)) => {
                if (e - a).abs() > tolerance && cfsi_mismatches.len() < 200 {
                    cfsi_mismatches.push(format!("{day}: got {a:.10} expected {e:.10}"));
                }
            }
            (e, a) => {
                if cfsi_mismatches.len() < 200 {
                    cfsi_mismatches.push(format!("{day}: 缺失不一致 got {a:?} expected {e:?}"));
                }
            }
        }

        // 维度
        for (golden_key, dim) in dim_keys {
            let expected = row["dims"][golden_key].as_f64();
            let actual = computed.dim_value(dim, idx);
            match (expected, actual) {
                (None, None) => {}
                (Some(e), Some(a)) if (e - a).abs() <= tolerance => {}
                (e, a) => {
                    if dim_mismatches.len() < 10 {
                        dim_mismatches.push(format!("{day} {dim}: got {a:?} expected {e:?}"));
                    }
                }
            }
        }
    }

    if !cfsi_mismatches.is_empty() {
        // 诊断：打印首个不一致日期的全部维度对照
        let day = cfsi_mismatches[0].split(':').next().unwrap();
        if let Some(&idx) = index_of.get(day) {
            let row = rows.iter().find(|r| r["date"] == day).unwrap();
            for (golden_key, dim) in dim_keys {
                eprintln!(
                    "{day} {dim}: got {:?} expected {:?}",
                    computed.dim_value(dim, idx),
                    row["dims"][golden_key]
                );
            }
            eprintln!("loadings: {:?}", computed.loadings);
        }
    }
    assert!(checked > 2800, "只比对到 {checked} 行，日历对不上");

    // L3：允许「成对换序」（contracts/README.md §5.1）——
    // SVD 实现不同（LAPACK gesdd vs 手写 Jacobi）会让近并列得分换序，
    // 差值小于 CDF 分辨率（1/n_train）。只允许成对互换，其余必须严格一致。
    let mut unresolved: Vec<String> = Vec::new();
    let mut swapped_pairs = 0usize;
    let mut consumed = vec![false; cfsi_mismatches.len()];
    for i in 0..cfsi_mismatches.len() {
        if consumed[i] {
            continue;
        }
        let (day_i, got_i, exp_i) = parse_mismatch(&cfsi_mismatches[i]);
        let mut paired = false;
        for j in (i + 1)..cfsi_mismatches.len() {
            if consumed[j] {
                continue;
            }
            let (day_j, got_j, exp_j) = parse_mismatch(&cfsi_mismatches[j]);
            // i 的实得等于 j 的期望，且 j 的实得等于 i 的期望 → 成对互换
            let swap_ok = (got_i - exp_j).abs() <= tolerance && (got_j - exp_i).abs() <= tolerance;
            let close_ok = (exp_i - exp_j).abs() <= 0.5; // ≤ 半个 CDF 分位点
            if swap_ok && close_ok {
                eprintln!(
                    "L3 换序对（允许）：{day_i} ↔ {day_j}（差 {:.6}）",
                    (exp_i - exp_j).abs()
                );
                consumed[i] = true;
                consumed[j] = true;
                swapped_pairs += 1;
                paired = true;
                break;
            }
        }
        if !paired {
            unresolved.push(cfsi_mismatches[i].clone());
        }
    }
    eprintln!(
        "CFSI 比对：{checked} 行，严格一致 {} 行，L3 换序对 {} 对，未解释 {} 行",
        checked - cfsi_mismatches.len(),
        swapped_pairs,
        unresolved.len()
    );
    assert!(
        unresolved.is_empty(),
        "CFSI 与黄金向量不一致（超出 L3 换序容差）：\n{}",
        unresolved.join("\n")
    );
    assert!(
        dim_mismatches.is_empty(),
        "维度分位与黄金向量不一致：\n{}",
        dim_mismatches.join("\n")
    );

    // τ 与旧版训练期冻结分位一致
    let golden_tau = doc["tau"].as_f64().expect("golden tau");
    assert!(
        (computed.tau - golden_tau).abs() <= tolerance,
        "tau 不一致: got {} expected {golden_tau}",
        computed.tau
    );
    eprintln!("黄金向量比对通过：{checked} 行 × 7 字段，容差 {tolerance}");

    drop(ws);
    let _ = std::fs::remove_file(&db_path);
}

#[test]
fn derived_recompute_matches_legacy_values() {
    let seed = seed_path();
    if !seed.exists() {
        eprintln!("跳过：缺少 {}", seed.display());
        return;
    }
    let db_path =
        std::env::temp_dir().join(format!("cbr-kernel-derived-{}.duckdb", std::process::id()));
    let _ = std::fs::remove_file(&db_path);
    let ws = Workspace::open(&db_path).expect("open workspace");
    // 只写基础序列，让内核从零重算四条派生序列
    seed_workspace(&ws, &seed, false);
    let catalog = pit::SeriesCatalog::load(&repo_root().to_string_lossy());
    let written = ingest::recompute_derived(&ws, &catalog).expect("recompute derived");
    assert_eq!(written.len(), 4, "四条派生序列都应重算: {written:?}");

    // 从 seed 里取派生序列的旧值做对照
    let raw = std::fs::read_to_string(&seed).expect("read seed");
    let mut expected: std::collections::BTreeMap<String, std::collections::BTreeMap<String, f64>> =
        std::collections::BTreeMap::new();
    for line in raw.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let record: Value = serde_json::from_str(line).unwrap();
        let series_id = record["series_id"].as_str().unwrap_or_default();
        if !series_id.contains("term_spread")
            && !series_id.contains("cn_us_spread")
            && !series_id.contains("cnh_cny_gap")
            && !series_id.contains("cgb_index")
        {
            continue;
        }
        if let (Some(day), Some(value)) = (record["obs_date"].as_str(), record["value"].as_f64()) {
            expected
                .entry(series_id.to_string())
                .or_default()
                .insert(day.to_string(), value);
        }
    }
    assert_eq!(expected.len(), 4);

    let mut checked = 0usize;
    for (series_id, values) in &expected {
        let mut stmt = ws
            .conn
            .prepare("SELECT obs_date, value FROM series_obs WHERE series_id = ?")
            .unwrap();
        let mut rows = stmt.query(duckdb::params![series_id]).unwrap();
        let mut actual: std::collections::BTreeMap<String, f64> = std::collections::BTreeMap::new();
        while let Some(row) = rows.next().unwrap() {
            let day: chrono::NaiveDate = row.get(0).unwrap();
            let value: f64 = row.get(1).unwrap();
            actual.insert(day.format("%Y-%m-%d").to_string(), value);
        }
        assert_eq!(actual.len(), values.len(), "{series_id} 行数不一致");
        for (day, want) in values {
            let got = actual
                .get(day)
                .unwrap_or_else(|| panic!("{series_id} 缺 {day}"));
            assert!(
                (got - want).abs() <= 1e-9,
                "{series_id} {day}: got {got} expected {want}"
            );
            checked += 1;
        }
    }
    eprintln!("派生序列重算一致：{checked} 行");
    drop(ws);
    let _ = std::fs::remove_file(&db_path);
}
