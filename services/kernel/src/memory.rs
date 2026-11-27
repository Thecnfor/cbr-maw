//! 三库记忆（MI / LLR / HLR）：嵌入式 LanceDB 实现（ADR-010）。
//!
//! 设计决议（docs/24 §D5–D7）：
//! - **单表 + `store` 判别列**：`mi` / `llr` / `hlr` 共用一套检索代码，跨库 MMR 可行；
//! - **kernel 唯一写入者**：Dart 只发 `memory.upsert` / `memory.search`；
//! - **PIT 硬过滤**：检索前强制 `available_at <= as_of`（LanceDB 标量前过滤）；
//! - **诚实降级**：无向量（未配置 embedder 或向量化失败）时只走 FTS/BM25，并在结果里写明。
//!
//! MMR（最大边际相关）不在 LanceDB 的 Rust 重排器里（只有 RRF），这里按公式实现
//! 约 30 行：`argmax_{i∉S} λ·rel(i) − (1−λ)·max_{j∈S} cos(i,j)`。

use std::path::Path;
use std::sync::Arc;

use lancedb::arrow::arrow_array::{
    builder::{BooleanBuilder, FixedSizeListBuilder, Float32Builder, StringBuilder},
    Array, ArrayRef, FixedSizeListArray, Float32Array, RecordBatch, StringArray,
};
use lancedb::arrow::arrow_schema::{DataType, Field, Schema, SchemaRef};
use lancedb::index::scalar::FtsIndexBuilder;
use lancedb::index::Index;
use lancedb::query::{ExecutableQuery, QueryBase};
use lancedb::{connect, Connection, Table};
use serde_json::{json, Map, Value};

use crate::error::{ErrorKind, KernelError, Result};

/// 向量维度（BGE-small-zh-v1.5 = 512）。
pub const EMBED_DIM: usize = 512;
/// 表名。
pub const TABLE: &str = "memory";
/// 三库枚举。
pub const STORES: [&str; 3] = ["mi", "llr", "hlr"];

/// 记忆记录。
#[derive(Debug, Clone, Default)]
pub struct MemoryRow {
    pub id: String,
    pub store: String,
    pub as_of: String,
    pub available_at: String,
    pub subject: String,
    pub kind: String,
    pub text: String,
    pub vector: Option<Vec<f32>>,
    pub payload: Value,
}

/// 检索请求。
pub struct SearchRequest<'a> {
    pub store: Option<&'a str>,
    pub as_of: &'a str,
    pub text: &'a str,
    pub subject: Option<&'a str>,
    pub kind: Option<&'a str>,
    pub top_k: usize,
    /// MMR 多样性系数：1.0 = 纯相关，0.0 = 纯多样。
    pub mmr_lambda: f32,
}

/// 检索命中。
#[derive(Debug, Clone)]
pub struct MemoryHit {
    pub id: String,
    pub store: String,
    pub as_of: String,
    pub available_at: String,
    pub subject: String,
    pub kind: String,
    pub text: String,
    pub payload: Value,
    pub score: f32,
    pub vector: Option<Vec<f32>>,
}

/// 向量化能力。kernel 不亲自联网：实现由本地模型（fastembed）或外部注入提供。
pub trait Embedder: Send + Sync {
    fn dim(&self) -> usize;
    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
}

/// LanceDB 句柄 + 专用 tokio runtime（同步门面，见 docs/24 §D11）。
pub struct Memory {
    rt: tokio::runtime::Runtime,
    table: Table,
    embedder: Option<Arc<dyn Embedder>>,
    fts_jieba: Option<bool>,
}

fn schema() -> SchemaRef {
    Arc::new(Schema::new(vec![
        Field::new("id", DataType::Utf8, false),
        Field::new("store", DataType::Utf8, false),
        Field::new("as_of", DataType::Utf8, false),
        Field::new("available_at", DataType::Utf8, false),
        Field::new("subject", DataType::Utf8, false),
        Field::new("kind", DataType::Utf8, false),
        Field::new("text", DataType::Utf8, false),
        Field::new(
            "vector",
            DataType::FixedSizeList(Arc::new(Field::new("item", DataType::Float32, false)), EMBED_DIM as i32),
            false,
        ),
        Field::new("has_vector", DataType::Boolean, false),
        Field::new("payload", DataType::Utf8, false),
    ]))
}

/// 把 `as_of` 上界规范成「当日结束」。
///
/// `available_at` 是 RFC3339（`2024-01-02T09:30:00Z`），而调用方常传裸日期
/// （`2024-01-02`）。直接做字符串比较时 `"2024-01-02T09:30:00Z" <= "2024-01-02"`
/// 为假——**当日可得的记录会被误判成未来**。这里补齐到当日 23:59:59Z。
fn as_of_upper_bound(as_of: &str) -> String {
    let trimmed = as_of.trim();
    if trimmed.len() == 10 && trimmed.as_bytes().get(4) == Some(&b'-') {
        format!("{trimmed}T23:59:59Z")
    } else {
        trimmed.to_string()
    }
}

/// 转义 SQL 字符串字面量（只用于我们自己的枚举值与 ISO 时间，仍做转义防注入）。
fn quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

fn batches_to_hits(batches: &[RecordBatch]) -> Result<Vec<MemoryHit>> {
    let mut hits = Vec::new();
    for batch in batches {
        let col = |name: &str| -> Result<&ArrayRef> {
            batch
                .column_by_name(name)
                .ok_or_else(|| KernelError::new(ErrorKind::Internal, format!("LanceDB 结果缺少列 {name}")))
        };
        let ids = col("id")?.as_any().downcast_ref::<StringArray>();
        let scores = batch
            .column_by_name("_distance")
            .and_then(|c| c.as_any().downcast_ref::<Float32Array>());
        let (Some(ids), Some(stores), Some(as_ofs), Some(avails), Some(subjects), Some(kinds), Some(texts), Some(payloads)) = (
            ids,
            col("store")?.as_any().downcast_ref::<StringArray>(),
            col("as_of")?.as_any().downcast_ref::<StringArray>(),
            col("available_at")?.as_any().downcast_ref::<StringArray>(),
            col("subject")?.as_any().downcast_ref::<StringArray>(),
            col("kind")?.as_any().downcast_ref::<StringArray>(),
            col("text")?.as_any().downcast_ref::<StringArray>(),
            col("payload")?.as_any().downcast_ref::<StringArray>(),
        ) else {
            return Err(KernelError::new(ErrorKind::Internal, "LanceDB 结果列类型不符"));
        };
        let vectors = batch
            .column_by_name("vector")
            .and_then(|c| c.as_any().downcast_ref::<FixedSizeListArray>())
            .and_then(|list| {
                list.iter()
                    .map(|item| {
                        item.and_then(|arr| {
                            arr.as_any()
                                .downcast_ref::<Float32Array>()
                                .map(|f| f.values().to_vec())
                        })
                    })
                    .collect::<Option<Vec<Vec<f32>>>>()
            });
        for i in 0..ids.len() {
            hits.push(MemoryHit {
                id: ids.value(i).to_string(),
                store: stores.value(i).to_string(),
                as_of: as_ofs.value(i).to_string(),
                available_at: avails.value(i).to_string(),
                subject: subjects.value(i).to_string(),
                kind: kinds.value(i).to_string(),
                text: texts.value(i).to_string(),
                payload: serde_json::from_str(payloads.value(i)).unwrap_or(Value::Null),
                score: scores.map(|s| s.value(i)).unwrap_or(0.0),
                vector: vectors.as_ref().and_then(|v| v.get(i).cloned()),
            });
        }
    }
    Ok(hits)
}

fn cosine(a: &[f32], b: &[f32]) -> f32 {
    let mut dot = 0.0f32;
    let mut na = 0.0f32;
    let mut nb = 0.0f32;
    for (x, y) in a.iter().zip(b.iter()) {
        dot += x * y;
        na += x * x;
        nb += y * y;
    }
    if na == 0.0 || nb == 0.0 {
        0.0
    } else {
        dot / (na.sqrt() * nb.sqrt())
    }
}

/// MMR 重排。`relevance` 必须已归一化到 [0,1]，越大越相关。
pub fn mmr(candidates: &[MemoryHit], relevance: &[f32], lambda: f32, k: usize) -> Vec<usize> {
    let mut order: Vec<usize> = Vec::new();
    let mut remaining: Vec<usize> = (0..candidates.len()).collect();
    while order.len() < k && !remaining.is_empty() {
        let mut best = remaining[0];
        let mut best_score = f32::NEG_INFINITY;
        for &idx in &remaining {
            let redundancy = order
                .iter()
                .filter_map(|&j| candidates[idx].vector.as_ref().zip(candidates[j].vector.as_ref()))
                .map(|(a, b)| cosine(a, b))
                .fold(f32::NEG_INFINITY, f32::max);
            let redundancy = if redundancy == f32::NEG_INFINITY { 0.0 } else { redundancy };
            let score = lambda * relevance[idx] - (1.0 - lambda) * redundancy;
            if score > best_score {
                best_score = score;
                best = idx;
            }
        }
        order.push(best);
        remaining.retain(|&x| x != best);
    }
    order
}


/// 打开或创建记忆表，并在 `text` 上建 FTS 索引（无向量时的降级检索路径）。
fn ensure_table(rt: &tokio::runtime::Runtime, db: &Connection) -> Result<(Table, Option<bool>)> {
    rt.block_on(async {
        let names = db
            .table_names()
            .execute()
            .await
            .map_err(|e| KernelError::new(ErrorKind::Internal, format!("列举 LanceDB 表失败: {e}")))?;
        if names.iter().any(|n| n == TABLE) {
            let table = db
                .open_table(TABLE)
                .execute()
                .await
                .map_err(|e| KernelError::new(ErrorKind::Internal, format!("打开记忆表失败: {e}")))?;
            // 既有表的 tokenizer 无法回读（Lance 未暴露），如实报告为未知。
            return Ok((table, None));
        }
        let table = db
            .create_empty_table(TABLE, schema())
            .execute()
            .await
            .map_err(|e| KernelError::new(ErrorKind::Internal, format!("创建记忆表失败: {e}")))?;
        // 中文分词：用内置 ICU 分词（无需外部词典文件，实测中文可切）。
        // jieba 需要 `LANCE_LANGUAGE_MODEL_HOME` 下的词典文件，缺文件时会静默退化。
        let icu = FtsIndexBuilder::default().base_tokenizer("icu".to_string());
        let fts_jieba = match table.create_index(&["text"], Index::FTS(icu)).execute().await {
            Ok(_) => true,
            Err(_) => {
                table
                    .create_index(&["text"], Index::FTS(FtsIndexBuilder::default()))
                    .execute()
                    .await
                    .map_err(|e| KernelError::new(ErrorKind::Internal, format!("创建 FTS 索引失败: {e}")))?;
                false
            }
        };
        Ok((table, Some(fts_jieba)))
    })
}

impl Memory {
    /// 打开（或创建）`<workspace>/memory.lance`。首次调用会建表与 FTS 索引。
    pub fn open(root: &Path, embedder: Option<Arc<dyn Embedder>>) -> Result<Self> {
        let rt = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(|e| KernelError::new(ErrorKind::Internal, format!("tokio runtime 启动失败: {e}")))?;
        let dir = root.join("memory.lance");
        std::fs::create_dir_all(&dir)
            .map_err(|e| KernelError::new(ErrorKind::Internal, format!("创建记忆目录失败: {e}")))?;
        let uri = dir.to_string_lossy().to_string();
        let db = rt
            .block_on(async { connect(&uri).execute().await })
            .map_err(|e| KernelError::new(ErrorKind::Internal, format!("LanceDB 连接失败: {e}")))?;
        let (table, fts_jieba) = ensure_table(&rt, &db)?;
        Ok(Self { rt, table, embedder, fts_jieba })
    }

    pub fn embedding_ready(&self) -> bool {
        self.embedder.is_some()
    }

    /// 写入/覆盖（按 `id` 幂等）。
    pub fn upsert(&self, rows: &mut [MemoryRow]) -> Result<usize> {
        if rows.is_empty() {
            return Ok(0);
        }
        for row in rows.iter() {
            if !STORES.contains(&row.store.as_str()) {
                return Err(KernelError::new(
                    ErrorKind::InvalidParams,
                    format!("未知记忆库 {}（只允许 mi/llr/hlr）", row.store),
                ));
            }
            if row.id.trim().is_empty() {
                return Err(KernelError::new(ErrorKind::InvalidParams, "记忆记录缺少 id"));
            }
            if row.available_at.trim().is_empty() {
                return Err(KernelError::new(
                    ErrorKind::InvalidParams,
                    format!("记忆记录 {} 缺少 available_at（PIT 硬约束）", row.id),
                ));
            }
        }
        // 向量化：只有配置了 embedder 且该行尚未带向量时才算。
        if let Some(embedder) = &self.embedder {
            let pending: Vec<usize> = rows
                .iter()
                .enumerate()
                .filter(|(_, r)| r.vector.is_none() && !r.text.trim().is_empty())
                .map(|(i, _)| i)
                .collect();
            if !pending.is_empty() {
                let texts: Vec<String> = pending.iter().map(|&i| rows[i].text.clone()).collect();
                let mut vectors = embedder.embed(&texts)?;
                if vectors.len() != pending.len() {
                    return Err(KernelError::new(
                        ErrorKind::Internal,
                        "embedder 返回条数与输入不一致（脏降级拒绝执行）",
                    ));
                }
                for (slot, &i) in pending.iter().enumerate() {
                    let vec = std::mem::take(&mut vectors[slot]);
                    if vec.len() != EMBED_DIM {
                        return Err(KernelError::new(
                            ErrorKind::Internal,
                            format!("向量维度不符：期望 {EMBED_DIM}，实际 {}", vec.len()),
                        ));
                    }
                    rows[i].vector = Some(vec);
                }
            }
        }

        let n = rows.len();
        let mut ids = StringBuilder::new();
        let mut stores = StringBuilder::new();
        let mut as_ofs = StringBuilder::new();
        let mut avails = StringBuilder::new();
        let mut subjects = StringBuilder::new();
        let mut kinds = StringBuilder::new();
        let mut texts = StringBuilder::new();
        let mut has_vector = BooleanBuilder::new();
        let mut payloads = StringBuilder::new();
        let mut vectors = FixedSizeListBuilder::new(Float32Builder::new(), EMBED_DIM as i32)
            .with_field(Arc::new(Field::new("item", DataType::Float32, false)));

        for row in rows.iter() {
            ids.append_value(&row.id);
            stores.append_value(&row.store);
            as_ofs.append_value(&row.as_of);
            avails.append_value(&row.available_at);
            subjects.append_value(&row.subject);
            kinds.append_value(&row.kind);
            texts.append_value(&row.text);
            let payload = if row.payload.is_null() {
                "{}".to_string()
            } else {
                row.payload.to_string()
            };
            payloads.append_value(payload);
            match &row.vector {
                Some(v) => {
                    for x in v.iter() {
                        vectors.values().append_value(*x);
                    }
                    vectors.append(true);
                    has_vector.append_value(true);
                }
                None => {
                    for _ in 0..EMBED_DIM {
                        vectors.values().append_value(0.0);
                    }
                    vectors.append(true);
                    has_vector.append_value(false);
                }
            }
        }

        let batch = RecordBatch::try_new(
            schema(),
            vec![
                Arc::new(ids.finish()) as ArrayRef,
                Arc::new(stores.finish()),
                Arc::new(as_ofs.finish()),
                Arc::new(avails.finish()),
                Arc::new(subjects.finish()),
                Arc::new(kinds.finish()),
                Arc::new(texts.finish()),
                Arc::new(vectors.finish()),
                Arc::new(has_vector.finish()),
                Arc::new(payloads.finish()),
            ],
        )
        .map_err(|e| KernelError::new(ErrorKind::Internal, format!("构造 RowBatch 失败: {e}")))?;

        self.rt.block_on(async {
            let mut merge = self.table.merge_insert(&["id"]);
            merge.when_matched_update_all(None);
            merge.when_not_matched_insert_all();
            merge
                .execute(Box::new(lancedb::arrow::arrow_array::RecordBatchIterator::new(
                    vec![Ok::<RecordBatch, lancedb::arrow::arrow_schema::ArrowError>(batch)],
                    schema(),
                )))
                .await
                .map_err(|e| KernelError::new(ErrorKind::Internal, format!("写入记忆失败: {e}")))?;
            // LanceDB 的 FTS 索引不会自动覆盖新写入的片段：每次写入后增量重建，
            // 否则 `memory.search` 的 FTS 降级通道看不到刚写入的记录（实测会静默返回空）。
            self.table
                .optimize(lancedb::table::OptimizeAction::Index(
                    lancedb::table::OptimizeOptions::default(),
                ))
                .await
                .map_err(|e| KernelError::new(ErrorKind::Internal, format!("重建记忆索引失败: {e}")))
        })?;
        Ok(n)
    }

    /// 检索：有向量走 ANN（多取候选再 MMR），无向量走 FTS。
    pub fn search(&self, req: &SearchRequest<'_>) -> Result<(Vec<MemoryHit>, &'static str)> {
        let upper = as_of_upper_bound(req.as_of);
        let mut filter = format!("available_at <= {}", quote(&upper));
        if let Some(store) = req.store {
            if !STORES.contains(&store) {
                return Err(KernelError::new(
                    ErrorKind::InvalidParams,
                    format!("未知记忆库 {store}（只允许 mi/llr/hlr）"),
                ));
            }
            filter.push_str(&format!(" AND store = {}", quote(store)));
        }
        if let Some(subject) = req.subject {
            filter.push_str(&format!(" AND subject = {}", quote(subject)));
        }
        if let Some(kind) = req.kind {
            filter.push_str(&format!(" AND kind = {}", quote(kind)));
        }

        let vector = self.embed_query(req.text)?;
        let mode = if vector.is_some() { "ann" } else { "fts" };
        let fetch_k = if vector.is_some() {
            (req.top_k * 4).max(req.top_k)
        } else {
            req.top_k
        };

        let batches = self.rt.block_on(async {
            let query = self.table.query();
            let stream = match &vector {
                Some(v) => {
                    query
                        .nearest_to(v.as_slice())
                        .map_err(|e| KernelError::new(ErrorKind::Internal, format!("向量查询构造失败: {e}")))?
                        .only_if(&filter)
                        .limit(fetch_k)
                        .execute()
                        .await
                }
                None => {
                    query
                        .full_text_search(lancedb::index::scalar::FullTextSearchQuery::new(req.text.to_string()))
                        .only_if(&filter)
                        .limit(fetch_k)
                        .execute()
                        .await
                }
            }
            .map_err(|e| KernelError::new(ErrorKind::DataMissing, format!("记忆检索失败: {e}")))?;
            futures::TryStreamExt::try_collect::<Vec<RecordBatch>>(stream)
                .await
                .map_err(|e| KernelError::new(ErrorKind::DataMissing, format!("记忆检索读取失败: {e}")))
        })?;

        let mut hits = batches_to_hits(&batches)?;
        if vector.is_some() && hits.len() > req.top_k && req.mmr_lambda < 1.0 {
            // 距离越小越相似；按 1/(1+d) 归一化后做 MMR。
            let relevance: Vec<f32> = hits.iter().map(|h| 1.0 / (1.0 + h.score.max(0.0))).collect();
            let order = mmr(&hits, &relevance, req.mmr_lambda.clamp(0.0, 1.0), req.top_k);
            hits = order.into_iter().map(|i| hits[i].clone()).collect();
        } else {
            hits.truncate(req.top_k);
        }
        Ok((hits, mode))
    }

    /// 按条件列举（不做向量检索）。用于 HLR 结算这类「按时间扫一遍」的场景。
    pub fn list(
        &self,
        store: &str,
        as_of_max: &str,
        limit: usize,
    ) -> Result<Vec<MemoryHit>> {
        if !STORES.contains(&store) {
            return Err(KernelError::new(
                ErrorKind::InvalidParams,
                format!("未知记忆库 {store}（只允许 mi/llr/hlr）"),
            ));
        }
        let upper = as_of_upper_bound(as_of_max);
        let filter = format!(
            "store = {} AND available_at <= {}",
            quote(store),
            quote(&upper)
        );
        let batches = self.rt.block_on(async {
            let stream = self
                .table
                .query()
                .only_if(&filter)
                .limit(limit.max(1))
                .execute()
                .await
                .map_err(|e| KernelError::new(ErrorKind::DataMissing, format!("列举记忆失败: {e}")))?;
            futures::TryStreamExt::try_collect::<Vec<RecordBatch>>(stream)
                .await
                .map_err(|e| KernelError::new(ErrorKind::DataMissing, format!("列举记忆读取失败: {e}")))
        })?;
        batches_to_hits(&batches)
    }

    fn embed_query(&self, text: &str) -> Result<Option<Vec<f32>>> {
        let Some(embedder) = &self.embedder else {
            return Ok(None);
        };
        if text.trim().is_empty() {
            return Ok(None);
        }
        let mut vectors = embedder.embed(&[text.to_string()])?;
        let vector = vectors
            .pop()
            .ok_or_else(|| KernelError::new(ErrorKind::Internal, "embedder 未返回查询向量"))?;
        if vector.len() != EMBED_DIM {
            return Err(KernelError::new(
                ErrorKind::Internal,
                format!("查询向量维度不符：期望 {EMBED_DIM}，实际 {}", vector.len()),
            ));
        }
        Ok(Some(vector))
    }

    pub fn stats(&self) -> Result<Value> {
        let count = self
            .rt
            .block_on(async { self.table.count_rows(None).await })
            .map_err(|e| KernelError::new(ErrorKind::Internal, format!("统计记忆行数失败: {e}")))?;
        let mut per_store = Map::new();
        for store in STORES {
            let n = self
                .rt
                .block_on(async {
                    self.table
                        .count_rows(Some(format!("store = {}", quote(store))))
                        .await
                })
                .map_err(|e| KernelError::new(ErrorKind::Internal, format!("统计 {store} 失败: {e}")))?;
            per_store.insert(store.to_string(), json!(n));
        }
        Ok(json!({
            "table": TABLE,
            "rows": count,
            "per_store": per_store,
            "embedding_ready": self.embedder.is_some(),
            "embed_dim": EMBED_DIM,
            "mmr": true,
            "pit_prefilter": true,
            "fts_tokenizer": match self.fts_jieba {
                Some(true) => "icu",
                Some(false) => "simple",
                None => "unknown",
            },
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mmr_prefers_diverse_when_lambda_low() {
        let mk = |id: &str, v: Vec<f32>| MemoryHit {
            id: id.into(),
            store: "mi".into(),
            as_of: "2024-01-01".into(),
            available_at: "2024-01-01T00:00:00Z".into(),
            subject: "all".into(),
            kind: "k".into(),
            text: String::new(),
            payload: Value::Null,
            score: 0.0,
            vector: Some(v),
        };
        let hits = vec![
            mk("a", vec![1.0, 0.0]),
            mk("b", vec![0.99, 0.01]),
            mk("c", vec![0.0, 1.0]),
        ];
        let relevance = [1.0, 0.99, 0.5];
        let order = mmr(&hits, &relevance, 0.3, 2);
        assert_eq!(hits[order[0]].id, "a");
        assert_eq!(hits[order[1]].id, "c", "低 λ 时第二篇应选多样而非近似重复");
    }
}
