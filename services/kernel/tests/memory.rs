//! 三库记忆的集成测试：PIT 硬过滤、幂等覆盖、FTS 降级、统计口径。
//!
//! 不依赖网络与模型文件：`Memory::open(path, None)` 走纯 FTS 通道。

use cbr_kernel::memory::{Memory, MemoryRow, SearchRequest};
use serde_json::json;

fn row(id: &str, store: &str, available_at: &str, text: &str) -> MemoryRow {
    MemoryRow {
        id: id.to_string(),
        store: store.to_string(),
        as_of: available_at[..10].to_string(),
        available_at: available_at.to_string(),
        subject: "all".to_string(),
        kind: "event".to_string(),
        text: text.to_string(),
        vector: None,
        payload: json!({"k": id}),
    }
}

#[test]
fn pit_prefilter_excludes_rows_not_yet_available() {
    let dir = tempfile::tempdir().expect("tempdir");
    let memory = Memory::open(dir.path(), None).expect("open memory");

    let mut rows = vec![
        row("a", "mi", "2024-01-02T09:30:00Z", "北向资金净流出 87 亿，人民币承压"),
        row("b", "mi", "2025-01-02T09:30:00Z", "北向资金净流出 200 亿，人民币大幅承压"),
    ];
    memory.upsert(&mut rows).expect("upsert");

    let (hits, mode) = memory
        .search(&SearchRequest {
            store: Some("mi"),
            as_of: "2024-06-01",
            text: "北向资金",
            subject: None,
            kind: None,
            top_k: 10,
            mmr_lambda: 1.0,
        })
        .expect("search");

    assert_eq!(mode, "fts", "无 embedder 时必须如实降级到 FTS");
    let ids: Vec<&str> = hits.iter().map(|h| h.id.as_str()).collect();
    assert_eq!(ids, vec!["a"], "as_of 之后才可得的记录必须被前过滤掉");
}

#[test]
fn upsert_is_idempotent_by_id() {
    let dir = tempfile::tempdir().expect("tempdir");
    let memory = Memory::open(dir.path(), None).expect("open memory");

    let mut first = vec![row("llr:1", "llr", "2024-03-01T00:00:00Z", "浅层反思初版")];
    memory.upsert(&mut first).expect("upsert once");
    let mut second = vec![row("llr:1", "llr", "2024-03-01T00:00:00Z", "浅层反思修订版")];
    memory.upsert(&mut second).expect("upsert twice");

    let stats = memory.stats().expect("stats");
    assert_eq!(stats["rows"], 1, "同一 id 必须覆盖而不是追加");
    assert_eq!(stats["per_store"]["llr"], 1);
}

#[test]
fn rejects_unknown_store_and_missing_available_at() {
    let dir = tempfile::tempdir().expect("tempdir");
    let memory = Memory::open(dir.path(), None).expect("open memory");

    let mut bad_store = vec![row("x", "hmm", "2024-01-01T00:00:00Z", "未知库")];
    assert!(memory.upsert(&mut bad_store).is_err(), "未知 store 必须拒绝");

    let mut missing = vec![row("y", "mi", "2024-01-01T00:00:00Z", "缺时间")];
    missing[0].available_at = String::new();
    assert!(memory.upsert(&mut missing).is_err(), "缺 available_at 必须拒绝");
}


#[test]
fn same_day_rows_are_visible_when_querying_by_bare_date() {
    let dir = tempfile::tempdir().expect("tempdir");
    let memory = Memory::open(dir.path(), None).expect("open memory");

    // available_at 是 RFC3339，查询用裸日期：当天 09:30 可得的记录必须可见。
    let mut rows = vec![row("a", "mi", "2024-01-02T09:30:00Z", "当日盘中的情报")];
    memory.upsert(&mut rows).expect("upsert");

    let (hits, _) = memory
        .search(&SearchRequest {
            store: Some("mi"),
            as_of: "2024-01-02",
            text: "情报",
            subject: None,
            kind: None,
            top_k: 5,
            mmr_lambda: 1.0,
        })
        .expect("search");
    assert_eq!(hits.len(), 1, "当日可得的记录不得被字符串比较误判为未来");
}
