//! knowledge_search：时点过滤的知识库检索工具。
//!
//! 对齐旧版 `commorcial/src/cbr/tools/kb_search.py`：工具层再做一次
//! `published_at <= as_of` 防御性校验（双保险）。

use super::source::DataSource;
use super::{param_str, param_usize, rv, ToolOutput};
use crate::error::Result;
use crate::numeric::r;
use serde_json::{json, Map, Value};

pub fn compute(
    params: &Map<String, Value>,
    as_of: &str,
    source: &dyn DataSource,
) -> Result<ToolOutput> {
    let query = param_str(params, "query")
        .ok_or_else(|| {
            crate::error::KernelError::invalid_params("knowledge_search 缺少 query")
                .with_detail(json!({"reason": "缺少必填参数 query", "field": "query"}))
        })?
        .to_string();
    if query.is_empty() || query.chars().count() > 500 {
        return Err(
            crate::error::KernelError::invalid_params("query 长度必须在 1..500")
                .with_detail(json!({"reason": "query 长度必须在 1..500 字符", "field": "query"})),
        );
    }
    let top_k = param_usize(params, "top_k", 5);
    let tags: Option<Vec<String>> = params.get("tags").and_then(|v| v.as_array()).map(|arr| {
        arr.iter()
            .filter_map(|t| t.as_str().map(str::to_string))
            .collect()
    });

    let hits = source
        .kb_search(&query, as_of, top_k, tags.as_deref())
        .ok_or_else(|| {
            crate::error::KernelError::data_missing("知识库索引缺失").with_detail(
                json!({"reason": "索引尚未构建，请先调用 kb.index", "index_version": "kb-bm25-v1"}),
            )
        })?;

    let as_of_day = &as_of[..10.min(as_of.len())];
    let mut records: Vec<Value> = Vec::new();
    let mut dropped_future = 0usize;
    for hit in hits {
        let published = hit["published_at"].as_str().map(str::to_string);
        if let Some(day) = &published {
            if &day[..10.min(day.len())] > as_of_day {
                dropped_future += 1;
                continue;
            }
        }
        records.push(hit);
    }

    let result_count = records.len();
    let top = records.first();
    let summary =
        match top {
            Some(hit) => {
                format!(
            "时点 {as_of} 检索「{query}」命中 {result_count} 个片段；top1={}（{}，score={}）。",
            hit["text"].as_str().unwrap_or("").chars().take(24).collect::<String>(),
            hit["published_at"].as_str().unwrap_or("NA"),
            hit["score"].as_f64().map(|s| format!("{s:.2}")).unwrap_or_else(|| "NA".to_string())
        )
            }
            None => format!("时点 {as_of} 检索「{query}」无命中（或全部晚于时点被过滤）。"),
        };

    let mut data = Map::new();
    data.insert("query".into(), json!(query));
    data.insert("as_of".into(), json!(as_of_day));
    data.insert("top_k".into(), json!(top_k));
    data.insert("tags".into(), tags.map(|t| json!(t)).unwrap_or(Value::Null));
    data.insert("result_count".into(), json!(result_count));
    data.insert("dropped_future".into(), json!(dropped_future));
    data.insert("results".into(), Value::Array(records));
    data.insert("unit_map".into(), json!({}));

    Ok(ToolOutput {
        data,
        unit: None,
        value: None,
        title: format!("知识检索：{query}"),
        summary,
    })
}

/// 供 `kb.search` 复用的打分辅助：把检索结果转换为契约 `KbHit`。
pub fn to_kb_hit(record: &Value) -> Value {
    json!({
        "chunk_id": record["chunk_id"].clone(),
        "score": record["score"].as_f64().map(rv).unwrap_or(json!(r(0.0).unwrap_or(0.0))),
        "text": record["text"].clone(),
        "document_id": record["document_id"].clone(),
        "locator": record["locator"].clone(),
        "published_at": record.get("published_at").cloned().unwrap_or(Value::Null),
        "source_id": record.get("source_id").cloned().unwrap_or(Value::Null),
    })
}
