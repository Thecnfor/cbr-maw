//! HLR 结算：写 LLR 时把已成熟的记录复盘成 HLR（ADR-010 §1、docs/24 §D7）。
//!
//! 三个必须守住的性质：
//! 1. **未成熟不结算**：事后窗口没走完的时点不参与（否则等于用未来数据算自己）；
//! 2. **`available_at` = 结果可得日**（窗口末日），历史回放时不会被提前读到；
//! 3. **τ 缺失不猜**：缺失即跳过，不用常量兜底。

use std::fs;

use cbr_kernel::memory::{Memory, MemoryRow};
use cbr_kernel::workspace::Workspace;

/// 与 `Kernel::settle_hlr` 相同的判定口径，独立实现一遍用于校验。
fn expected_outcome(ws: &Workspace, as_of: &str, horizon: usize) -> Option<(bool, f64, f64)> {
    let calendar = cbr_kernel::reflection::trading_calendar(ws, "2026-12-31").ok()?;
    let pos = calendar.iter().position(|d| d == as_of)?;
    if pos + horizon >= calendar.len() {
        return None;
    }
    let window = &calendar[pos + 1..=pos + horizon];
    let tau = cbr_kernel::reflection::tau_on(ws, as_of).ok()??;
    let peak = cbr_kernel::reflection::peak_between(ws, window).ok()??;
    Some((peak >= tau, peak, tau))
}

fn row(id: &str, store: &str, as_of: &str, available_at: &str, level: &str) -> MemoryRow {
    MemoryRow {
        id: id.to_string(),
        store: store.to_string(),
        as_of: as_of.to_string(),
        available_at: available_at.to_string(),
        subject: "all".to_string(),
        kind: "attribution".to_string(),
        text: format!("在 {as_of} 判定 {level}"),
        vector: None,
        payload: serde_json::json!({"level": level}),
    }
}

#[test]
fn unsettled_rows_have_no_hlr_counterpart() {
    let dir = tempfile::tempdir().expect("tempdir");
    let memory = Memory::open(dir.path(), None).expect("open memory");

    // 用「今天」写一条 LLR：事后窗口必然没走完，不得被结算。
    let today = chrono::Utc::now().format("%Y-%m-%d").to_string();
    let mut rows = vec![row("llr:today", "llr", &today, &format!("{today}T10:00:00Z"), "high")];
    memory.upsert(&mut rows).expect("upsert");

    let pending = memory.list("llr", &today, 100).expect("list llr");
    assert_eq!(pending.len(), 1, "刚写入的 LLR 应当可列出");
    let hlr = memory.list("hlr", &today, 100).expect("list hlr");
    assert!(hlr.is_empty(), "未成熟的时点不得产生 HLR 记录");
}

#[test]
fn hlr_rows_carry_outcome_day_as_available_at() {
    let dir = tempfile::tempdir().expect("tempdir");
    let memory = Memory::open(dir.path(), None).expect("open memory");

    // 直接构造一条 HLR（模拟结算产物），校验 PIT 语义与字段完整性。
    let mut rows = vec![MemoryRow {
        id: "hlr:llr:2020-03-02".into(),
        store: "hlr".into(),
        as_of: "2020-03-02".into(),
        available_at: "2020-03-30T15:00:00Z".into(),
        subject: "all".into(),
        kind: "hlr_settled".into(),
        text: "在 2020-03-02 判定 high（预警）；事后 20 个交易日 CFSI 峰值 …".into(),
        vector: None,
        payload: serde_json::json!({
            "source_llr": "llr:2020-03-02",
            "level": "high",
            "alarmed": true,
            "outcome": "hit",
        }),
    }];
    memory.upsert(&mut rows).expect("upsert hlr");

    // 结果可得日之前不可见（PIT 硬约束）。
    let before = memory.list("hlr", "2020-03-29", 100).expect("list before");
    assert!(before.is_empty(), "结果可得日之前不得读到 HLR");
    let after = memory.list("hlr", "2020-03-30", 100).expect("list after");
    assert_eq!(after.len(), 1);
    assert_eq!(after[0].payload["outcome"], "hit");
}

/// 结算口径必须与 `reflection::deep` 一致：窗口内 CFSI 峰值 ≥ 当日 τ。
///
/// 用真实 PIT 库里的一个历史时点做交叉验证；库不存在时跳过（不伪造）。
#[test]
fn settlement_criterion_matches_reflection_window() {
    let pit = std::path::Path::new("/mnt/shared/recently/commorcial/data/pit_real.duckdb");
    if !pit.exists() {
        eprintln!("跳过：真实 PIT 库不存在");
        return;
    }
    let dir = tempfile::tempdir().expect("tempdir");
    let work = dir.path().join("ws.duckdb");
    fs::copy(pit, &work).expect("copy pit db");
    let ws = Workspace::open(&work).expect("open workspace");

    // 2018-05-30 是压力期时点，事后窗口必然走完。
    let as_of = "2018-05-30";
    let Some((stressed, peak, tau)) = expected_outcome(&ws, as_of, 20) else {
        eprintln!("跳过：该时点不可评估（缺 τ 或窗口未走完）");
        return;
    };
    assert!(peak.is_finite() && tau.is_finite());
    // 该时点位于 2018 年压力窗口内，事后 20 日应当仍在压力区。
    assert!(stressed, "2018-05-30 之后 20 日应处于压力区（peak={peak}, tau={tau}）");
}
