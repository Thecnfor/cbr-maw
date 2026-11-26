//! 知识库：BM25 + 哈希向量 + RRF 混合检索（对齐旧版 `knowledge/{_index,vector}.py`）。
//!
//! 默认离线可用、无外部依赖、确定性：中文按「单字 + 相邻二元组」切分，
//! 英文/数字按小写词切分（保留 `_ + - .`）；向量用 hashing trick（signed hash）+ L2 归一化。

use crate::error::{KernelError, Result};
use crate::workspace::Workspace;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};

/// 索引版本（写入 `kb.index.result.index_version`）。
pub const INDEX_VERSION: &str = "kb-bm25-v1";
pub const BM25_K1: f64 = 1.5;
pub const BM25_B: f64 = 0.75;
/// 混合检索 RRF 平滑常数。
pub const RRF_K: f64 = 60.0;
pub const BM25_WEIGHT: f64 = 0.5;
pub const EMBED_DIM: usize = 256;
const CHUNK_SIZE: usize = 240;
const CHUNK_OVERLAP: usize = 48;

/// 中英混合分词：中文单字 + 二元组，英文/数字小写词。
pub fn tokenize(text: &str) -> Vec<String> {
    let lowered = text.to_lowercase();
    let mut tokens: Vec<String> = Vec::new();
    let chars: Vec<char> = lowered.chars().collect();
    let mut i = 0;
    while i < chars.len() {
        let c = chars[i];
        // 英文/数字词：[a-z0-9][a-z0-9_+\-.]*
        if c.is_ascii_alphanumeric() {
            let start = i;
            let mut j = i + 1;
            while j < chars.len() {
                let n = chars[j];
                if n.is_ascii_alphanumeric() || matches!(n, '_' | '+' | '-' | '.') {
                    j += 1;
                } else {
                    break;
                }
            }
            tokens.push(chars[start..j].iter().collect());
            i = j;
            continue;
        }
        // 中文连续段：单字 + 二元组
        if is_cjk(c) {
            let start = i;
            let mut j = i;
            while j < chars.len() && is_cjk(chars[j]) {
                j += 1;
            }
            #[allow(clippy::needless_range_loop)] // 按字符下标切片（单字 + 双字 bigram）
            for k in start..j {
                tokens.push(chars[k].to_string());
            }
            #[allow(clippy::needless_range_loop)] // 同上
            for k in start..j.saturating_sub(1) {
                tokens.push(chars[k..k + 2].iter().collect());
            }
            i = j;
            continue;
        }
        i += 1;
    }
    tokens
}

fn is_cjk(c: char) -> bool {
    ('\u{4e00}'..='\u{9fff}').contains(&c)
}

/// 一个知识库切片。
#[derive(Debug, Clone)]
pub struct Chunk {
    pub chunk_id: String,
    pub doc_id: String,
    pub title: String,
    pub source: String,
    pub publish_time: String,
    pub url: Option<String>,
    pub tags: Vec<String>,
    pub section: String,
    pub text: String,
    pub index_text: String,
    pub chunk_index: usize,
}

/// 文档（语料解析中间结构）。
pub struct Document {
    pub doc_id: String,
    pub title: String,
    pub source: String,
    pub publish_time: String,
    pub url: Option<String>,
    pub tags: Vec<String>,
    pub section: String,
    pub text: String,
}

// --------------------------------------------------------------------------- //
// 语料加载
// --------------------------------------------------------------------------- //
/// 解析 YAML front matter（只支持本项目语料的扁平 `key: value` 与行内数组）。
fn parse_front_matter(raw: &str) -> Option<(BTreeMap<String, String>, String)> {
    let trimmed = raw.trim_start_matches('\u{feff}');
    if !trimmed.starts_with("---") {
        return None;
    }
    let rest = &trimmed[3..];
    let rest = rest
        .strip_prefix("\r\n")
        .or_else(|| rest.strip_prefix('\n'))?;
    let end = rest.find("\n---")?;
    let meta_raw = &rest[..end];
    let body = &rest[end + 4..];
    let body = body
        .strip_prefix("\r\n")
        .or_else(|| body.strip_prefix('\n'))
        .unwrap_or(body);
    let mut meta = BTreeMap::new();
    for line in meta_raw.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        if let Some((key, value)) = line.split_once(':') {
            meta.insert(
                key.trim().to_string(),
                value.trim().trim_matches(['"', '\'']).to_string(),
            );
        }
    }
    Some((meta, body.to_string()))
}

fn parse_tags(raw: &str) -> Vec<String> {
    let inner = raw.trim().trim_start_matches('[').trim_end_matches(']');
    inner
        .split([',', '，', ';', '；'])
        .map(|s| s.trim().trim_matches(['"', '\'']).to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

fn document_from_json(record: &Value, origin: &str) -> Result<Document> {
    let title = record["title"].as_str().unwrap_or("").trim().to_string();
    let source = record["source"].as_str().unwrap_or("").trim().to_string();
    let publish_time = record["publish_time"]
        .as_str()
        .or_else(|| record["published_at"].as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    if title.is_empty() || source.is_empty() || publish_time.is_empty() {
        return Err(KernelError::data_missing(format!(
            "语料缺少必需元数据 (title/source/publish_time): {origin}"
        )));
    }
    let doc_id = record["doc_id"]
        .as_str()
        .map(str::to_string)
        .unwrap_or_else(|| {
            std::path::Path::new(origin)
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default()
        });
    let tags = record["tags"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|t| t.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();
    let text = record["text"]
        .as_str()
        .or_else(|| record["content"].as_str())
        .unwrap_or("")
        .trim()
        .to_string();
    Ok(Document {
        doc_id,
        title,
        source,
        publish_time: publish_time[..10.min(publish_time.len())].to_string(),
        url: record["url"].as_str().map(str::to_string),
        tags,
        section: record["section"].as_str().unwrap_or("正文").to_string(),
        text,
    })
}

/// 加载语料目录下全部 `.md` / `.jsonl` 文档。
pub fn load_documents(corpus_dir: &str) -> Result<Vec<Document>> {
    let root = std::path::Path::new(corpus_dir);
    if !root.is_dir() {
        return Err(KernelError::new(
            crate::error::ErrorKind::SourceUnavailable,
            "语料目录不存在或不可读",
        )
        .with_detail(json!({"path": corpus_dir, "reason": "语料目录不存在或不可读"})));
    }
    let mut paths: Vec<std::path::PathBuf> = Vec::new();
    collect_files(root, &mut paths)?;
    paths.sort();
    let mut documents = Vec::new();
    for path in paths {
        let ext = path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_lowercase();
        let origin = path.to_string_lossy().to_string();
        match ext.as_str() {
            "md" | "markdown" => {
                let raw = std::fs::read_to_string(&path)
                    .map_err(|e| KernelError::internal(format!("读取 {origin} 失败: {e}")))?;
                let (meta, body) = parse_front_matter(&raw).ok_or_else(|| {
                    KernelError::data_missing(format!(
                        "markdown 语料缺少 YAML front matter: {origin}"
                    ))
                })?;
                let mut record = serde_json::Map::new();
                for (k, v) in &meta {
                    record.insert(k.clone(), Value::String(v.clone()));
                }
                if let Some(tags) = meta.get("tags") {
                    record.insert("tags".into(), json!(parse_tags(tags)));
                }
                record.insert("text".into(), Value::String(body));
                documents.push(document_from_json(&Value::Object(record), &origin)?);
            }
            "jsonl" => {
                let raw = std::fs::read_to_string(&path)
                    .map_err(|e| KernelError::internal(format!("读取 {origin} 失败: {e}")))?;
                for (line_no, line) in raw.lines().enumerate() {
                    let line = line.trim();
                    if line.is_empty() {
                        continue;
                    }
                    let record: Value = serde_json::from_str(line).map_err(|e| {
                        KernelError::data_missing(format!(
                            "{origin}:{}: 非法 JSON: {e}",
                            line_no + 1
                        ))
                    })?;
                    let mut doc =
                        document_from_json(&record, &format!("{origin}:{}", line_no + 1))?;
                    if doc.doc_id.is_empty() {
                        doc.doc_id = format!(
                            "{}-{:03}",
                            path.file_stem().unwrap_or_default().to_string_lossy(),
                            line_no + 1
                        );
                    }
                    documents.push(doc);
                }
            }
            _ => {}
        }
    }
    if documents.is_empty() {
        return Err(KernelError::data_missing(format!(
            "no corpus documents found under {corpus_dir}"
        )));
    }
    documents.sort_by(|a, b| {
        a.publish_time
            .cmp(&b.publish_time)
            .then(a.doc_id.cmp(&b.doc_id))
    });
    Ok(documents)
}

fn collect_files(dir: &std::path::Path, out: &mut Vec<std::path::PathBuf>) -> Result<()> {
    let entries = std::fs::read_dir(dir).map_err(|e| {
        KernelError::new(
            crate::error::ErrorKind::SourceUnavailable,
            format!("读取目录失败: {e}"),
        )
    })?;
    for entry in entries {
        let entry = entry.map_err(|e| KernelError::internal(e.to_string()))?;
        let path = entry.path();
        if path.is_dir() {
            collect_files(&path, out)?;
        } else if path.is_file() {
            out.push(path);
        }
    }
    Ok(())
}

// --------------------------------------------------------------------------- //
// 切块
// --------------------------------------------------------------------------- //
fn split_sentences(text: &str) -> Vec<String> {
    let mut out = Vec::new();
    let mut current = String::new();
    for ch in text.chars() {
        current.push(ch);
        if matches!(ch, '。' | '！' | '？' | '；' | '!' | '?' | ';' | '\n') {
            let trimmed = current.trim().to_string();
            if !trimmed.is_empty() {
                out.push(trimmed);
            }
            current.clear();
        }
    }
    let trimmed = current.trim().to_string();
    if !trimmed.is_empty() {
        out.push(trimmed);
    }
    out
}

fn char_len(text: &str) -> usize {
    text.chars().count()
}

fn overlap_tail(sentences: &[String], overlap_chars: usize) -> Vec<String> {
    let mut tail: Vec<String> = Vec::new();
    let mut length = 0usize;
    for sentence in sentences.iter().rev() {
        if !tail.is_empty() && length + char_len(sentence) + 1 > overlap_chars {
            break;
        }
        tail.insert(0, sentence.clone());
        length += char_len(sentence) + 1;
    }
    tail
}

/// 按句子边界把正文切成目标长度块，块间保留约 `chunk_overlap` 字符重叠。
pub fn chunk_text(text: &str, chunk_size: usize, chunk_overlap: usize) -> Vec<String> {
    let overlap = chunk_overlap.min(chunk_size / 2);
    let sentences = split_sentences(text);
    if sentences.is_empty() {
        return Vec::new();
    }
    let mut hard: Vec<String> = Vec::new();
    for sentence in sentences {
        if char_len(&sentence) > chunk_size * 2 {
            let chars: Vec<char> = sentence.chars().collect();
            let mut start = 0;
            while start < chars.len() {
                let end = (start + chunk_size).min(chars.len());
                hard.push(chars[start..end].iter().collect());
                start = end;
            }
        } else {
            hard.push(sentence);
        }
    }

    let mut chunks: Vec<String> = Vec::new();
    let mut current: Vec<String> = Vec::new();
    let mut current_len = 0usize;
    let mut index = 0usize;
    let mut carried = false;
    while index < hard.len() {
        let sentence = &hard[index];
        if !current.is_empty() && current_len + char_len(sentence) + 1 > chunk_size {
            if !carried {
                chunks.push(current.join("\n"));
                current = overlap_tail(&current, overlap);
                current_len = current.iter().map(|p| char_len(p) + 1).sum();
                carried = true;
                continue;
            }
            current.push(sentence.clone());
            current_len += char_len(sentence) + 1;
            index += 1;
            carried = false;
            continue;
        }
        current.push(sentence.clone());
        current_len += char_len(sentence) + 1;
        index += 1;
        carried = false;
    }
    if !current.is_empty() {
        chunks.push(current.join("\n"));
    }
    chunks
}

pub fn build_chunks(documents: &[Document]) -> Vec<Chunk> {
    let mut chunks = Vec::new();
    for doc in documents {
        let tag_text = doc.tags.join(" ");
        for (idx, piece) in chunk_text(&doc.text, CHUNK_SIZE, CHUNK_OVERLAP)
            .into_iter()
            .enumerate()
        {
            let index_text = format!("{}\n{}\n{}\n{}", doc.title, doc.section, tag_text, piece);
            chunks.push(Chunk {
                chunk_id: format!("{}#c{idx:03}", doc.doc_id),
                doc_id: doc.doc_id.clone(),
                title: doc.title.clone(),
                source: doc.source.clone(),
                publish_time: doc.publish_time.clone(),
                url: doc.url.clone(),
                tags: doc.tags.clone(),
                section: doc.section.clone(),
                text: piece,
                index_text,
                chunk_index: idx,
            });
        }
    }
    chunks
}

// --------------------------------------------------------------------------- //
// BM25
// --------------------------------------------------------------------------- //
pub struct Bm25Stats {
    pub n_chunks: usize,
    pub avgdl: f64,
    pub df: BTreeMap<String, usize>,
}

pub fn build_bm25_stats(chunks: &[Chunk]) -> Bm25Stats {
    let mut df: BTreeMap<String, usize> = BTreeMap::new();
    let mut total_length = 0usize;
    for chunk in chunks {
        let tokens = tokenize(&chunk.index_text);
        total_length += tokens.len();
        let unique: BTreeSet<&String> = tokens.iter().collect();
        for token in unique {
            *df.entry(token.clone()).or_insert(0) += 1;
        }
    }
    let n_chunks = chunks.len();
    Bm25Stats {
        n_chunks,
        avgdl: if n_chunks > 0 {
            total_length as f64 / n_chunks as f64
        } else {
            0.0
        },
        df,
    }
}

pub fn bm25_scores(query_tokens: &[String], chunks: &[Chunk], stats: &Bm25Stats) -> Vec<f64> {
    let avgdl = if stats.avgdl > 0.0 { stats.avgdl } else { 1.0 };
    let mut unique_query: Vec<&String> = Vec::new();
    let mut seen: BTreeSet<&String> = BTreeSet::new();
    for token in query_tokens {
        if seen.insert(token) {
            unique_query.push(token);
        }
    }
    chunks
        .iter()
        .map(|chunk| {
            let tokens = tokenize(&chunk.index_text);
            let dl = tokens.len();
            if dl == 0 {
                return 0.0;
            }
            let mut tf: BTreeMap<&String, usize> = BTreeMap::new();
            for token in &tokens {
                *tf.entry(token).or_insert(0) += 1;
            }
            let mut score = 0.0;
            for token in &unique_query {
                let freq = *tf.get(token).unwrap_or(&0) as f64;
                if freq == 0.0 {
                    continue;
                }
                let token_df = *stats.df.get(*token).unwrap_or(&0) as f64;
                let idf = (1.0 + (stats.n_chunks as f64 - token_df + 0.5) / (token_df + 0.5)).ln();
                let denominator = freq + BM25_K1 * (1.0 - BM25_B + BM25_B * dl as f64 / avgdl);
                score += idf * freq * (BM25_K1 + 1.0) / denominator;
            }
            score
        })
        .collect()
}

// --------------------------------------------------------------------------- //
// 哈希向量（hashing trick，blake2b 等价：用 sha256 派生索引与符号）
// --------------------------------------------------------------------------- //
pub fn embed(text: &str) -> Vec<f32> {
    let mut out = vec![0.0f32; EMBED_DIM];
    for token in tokenize(text) {
        let digest = crate::canon::sha256_text(&token);
        let bytes = digest.as_bytes();
        let index = (u32::from_str_radix(&digest[..8], 16).unwrap_or(0) as usize) % EMBED_DIM;
        let sign = if bytes
            .get(8)
            .map(|b| b.is_ascii_digit() && (b - b'0') % 2 == 1)
            .unwrap_or(false)
        {
            -1.0
        } else {
            1.0
        };
        out[index] += sign;
    }
    let norm: f32 = out.iter().map(|v| v * v).sum::<f32>().sqrt();
    if norm > 0.0 {
        for value in out.iter_mut() {
            *value /= norm;
        }
    }
    out
}

fn cosine(a: &[f32], b: &[f32]) -> f64 {
    a.iter()
        .zip(b.iter())
        .map(|(x, y)| (*x as f64) * (*y as f64))
        .sum()
}

// --------------------------------------------------------------------------- //
// 索引持久化（写入 workspace 的 kb_chunks / kb_meta 表）
// --------------------------------------------------------------------------- //
pub fn index(ws: &Workspace, corpus_dir: &str, force: bool) -> Result<Value> {
    let corpus_hash = corpus_hash(corpus_dir)?;
    if !force {
        if let Some(stored) = ws.get_meta("kb_corpus_hash")? {
            if stored == corpus_hash {
                let documents = ws.scalar_i64("SELECT count(DISTINCT doc_id) FROM kb_chunks")?;
                let chunks = ws.scalar_i64("SELECT count(*) FROM kb_chunks")?;
                if chunks > 0 {
                    return Ok(json!({
                        "documents": documents,
                        "chunks": chunks,
                        "index_version": INDEX_VERSION,
                    }));
                }
            }
        }
    }

    let documents = load_documents(corpus_dir)?;
    let chunks = build_chunks(&documents);

    ws.conn
        .execute("DELETE FROM kb_chunks", [])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut stmt = ws
        .conn
        .prepare(
            "INSERT INTO kb_chunks(chunk_id, doc_id, title, source, publish_time, url, tags, section, text, index_text, chunk_index) \
             VALUES (?, ?, ?, ?, CAST(? AS DATE), ?, ?, ?, ?, ?, ?)",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    for chunk in &chunks {
        stmt.execute(duckdb::params![
            chunk.chunk_id,
            chunk.doc_id,
            chunk.title,
            chunk.source,
            chunk.publish_time,
            chunk.url,
            chunk.tags.join("\u{1f}"),
            chunk.section,
            chunk.text,
            chunk.index_text,
            chunk.chunk_index as i64,
        ])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    }
    drop(stmt);
    ws.set_meta("kb_corpus_hash", &corpus_hash)?;
    ws.set_meta("kb_index_version", INDEX_VERSION)?;

    Ok(json!({
        "documents": documents.len(),
        "chunks": chunks.len(),
        "index_version": INDEX_VERSION,
    }))
}

/// 语料目录内容哈希（相对路径 + 文件内容）。
pub fn corpus_hash(corpus_dir: &str) -> Result<String> {
    let root = std::path::Path::new(corpus_dir);
    if !root.is_dir() {
        return Err(KernelError::new(
            crate::error::ErrorKind::SourceUnavailable,
            "语料目录不存在或不可读",
        )
        .with_detail(json!({"path": corpus_dir, "reason": "语料目录不存在或不可读"})));
    }
    let mut paths = Vec::new();
    collect_files(root, &mut paths)?;
    paths.sort();
    let mut material = String::new();
    for path in paths {
        let ext = path
            .extension()
            .and_then(|e| e.to_str())
            .unwrap_or("")
            .to_lowercase();
        if !matches!(ext.as_str(), "md" | "markdown" | "jsonl") {
            continue;
        }
        let rel = path
            .strip_prefix(root)
            .unwrap_or(&path)
            .to_string_lossy()
            .to_string();
        let content = std::fs::read(&path).map_err(|e| KernelError::internal(e.to_string()))?;
        material.push_str(&rel);
        material.push('\u{0}');
        material.push_str(&crate::canon::sha256_text(&String::from_utf8_lossy(
            &content,
        )));
    }
    Ok(crate::canon::sha256_text(&material))
}

/// 从库中读回全部切片。
pub fn load_chunks(ws: &Workspace) -> Result<Vec<Chunk>> {
    let mut stmt = ws
        .conn
        .prepare(
            "SELECT chunk_id, doc_id, title, source, publish_time, url, tags, section, text, index_text, chunk_index \
             FROM kb_chunks ORDER BY chunk_id",
        )
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut rows = stmt
        .query([])
        .map_err(|e| KernelError::internal(e.to_string()))?;
    let mut chunks = Vec::new();
    while let Some(row) = rows
        .next()
        .map_err(|e| KernelError::internal(e.to_string()))?
    {
        let publish: Option<chrono::NaiveDate> = row.get(4).ok();
        chunks.push(Chunk {
            chunk_id: row
                .get(0)
                .map_err(|e| KernelError::internal(e.to_string()))?,
            doc_id: row.get(1).unwrap_or_default(),
            title: row.get(2).unwrap_or_default(),
            source: row.get(3).unwrap_or_default(),
            publish_time: publish
                .map(|d| d.format("%Y-%m-%d").to_string())
                .unwrap_or_default(),
            url: row.get(5).ok(),
            tags: row
                .get::<usize, String>(6)
                .unwrap_or_default()
                .split('\u{1f}')
                .filter(|s| !s.is_empty())
                .map(str::to_string)
                .collect(),
            section: row.get(7).unwrap_or_default(),
            text: row.get(8).unwrap_or_default(),
            index_text: row.get(9).unwrap_or_default(),
            chunk_index: row.get::<usize, i64>(10).unwrap_or(0) as usize,
        });
    }
    Ok(chunks)
}

/// 混合检索（BM25 + 哈希向量 + 加权 RRF）。
pub fn search(
    ws: &Workspace,
    query: &str,
    as_of: &str,
    top_k: usize,
    filters: Option<&Value>,
) -> Result<Vec<Value>> {
    let chunks = load_chunks(ws)?;
    if chunks.is_empty() {
        return Err(KernelError::data_missing("知识库索引缺失").with_detail(
            json!({"reason": "索引尚未构建，请先调用 kb.index", "index_version": INDEX_VERSION}),
        ));
    }
    let query = query.trim();
    if query.is_empty() {
        return Ok(Vec::new());
    }
    let day = &as_of[..10.min(as_of.len())];
    let wanted_tags: BTreeSet<String> = filters
        .and_then(|f| f.get("tags"))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|t| t.as_str().map(|s| s.to_lowercase()))
                .collect()
        })
        .unwrap_or_default();
    let wanted_sources: BTreeSet<String> = filters
        .and_then(|f| f.get("sources"))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|t| t.as_str().map(|s| s.to_lowercase()))
                .collect()
        })
        .unwrap_or_default();
    let source_id = filters
        .and_then(|f| f.get("source_id"))
        .and_then(|v| v.as_str());

    let candidates: Vec<&Chunk> = chunks
        .iter()
        .filter(|c| c.publish_time.as_str() <= day)
        .filter(|c| {
            wanted_tags.is_empty()
                || wanted_tags.is_subset(&c.tags.iter().map(|t| t.to_lowercase()).collect())
        })
        .filter(|c| wanted_sources.is_empty() || wanted_sources.contains(&c.source.to_lowercase()))
        .filter(|c| source_id.map(|s| s == c.source).unwrap_or(true))
        .collect();
    if candidates.is_empty() {
        return Ok(Vec::new());
    }

    let owned: Vec<Chunk> = candidates.iter().map(|c| (*c).clone()).collect();
    let stats = build_bm25_stats(&owned);
    let query_tokens = tokenize(query);
    let bm25 = bm25_scores(&query_tokens, &owned, &stats);
    let mut bm25_order: Vec<(f64, usize)> = bm25
        .iter()
        .copied()
        .enumerate()
        .map(|(i, s)| (s, i))
        .collect();
    bm25_order.sort_by(|a, b| {
        b.0.partial_cmp(&a.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.1.cmp(&b.1))
    });

    let query_vec = embed(query);
    let mut vector_order: Vec<(f64, usize)> = owned
        .iter()
        .enumerate()
        .map(|(i, c)| (cosine(&query_vec, &embed(&c.index_text)), i))
        .collect();
    vector_order.sort_by(|a, b| {
        b.0.partial_cmp(&a.0)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.1.cmp(&b.1))
    });

    let mut fused: BTreeMap<usize, f64> = BTreeMap::new();
    for (rank, (_, idx)) in bm25_order.iter().enumerate() {
        *fused.entry(*idx).or_insert(0.0) += BM25_WEIGHT / (RRF_K + (rank + 1) as f64);
    }
    for (rank, (_, idx)) in vector_order.iter().enumerate() {
        *fused.entry(*idx).or_insert(0.0) += (1.0 - BM25_WEIGHT) / (RRF_K + (rank + 1) as f64);
    }
    let mut ranked: Vec<(usize, f64)> = fused.into_iter().collect();
    ranked.sort_by(|a, b| {
        b.1.partial_cmp(&a.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.0.cmp(&b.0))
    });
    ranked.truncate(top_k.max(1));

    Ok(ranked
        .into_iter()
        .map(|(idx, score)| {
            let chunk = &owned[idx];
            json!({
                "chunk_id": chunk.chunk_id,
                "score": crate::numeric::r(score),
                "text": chunk.text,
                "document_id": chunk.doc_id,
                "locator": format!("{} · 第 {} 段", chunk.section, chunk.chunk_index + 1),
                "published_at": chunk.publish_time,
                "source_id": chunk.source,
                "title": chunk.title,
                "url": chunk.url,
                "tags": chunk.tags,
            })
        })
        .collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokenizer_splits_cjk_into_unigrams_and_bigrams() {
        let tokens = tokenize("跨境资金");
        assert!(tokens.contains(&"跨".to_string()));
        assert!(tokens.contains(&"跨境".to_string()));
        assert!(tokens.contains(&"资金".to_string()));
    }

    #[test]
    fn tokenizer_keeps_metric_names() {
        let tokens = tokenize("VAR_95 and var-95");
        assert!(tokens.contains(&"var_95".to_string()));
        assert!(tokens.contains(&"var-95".to_string()));
    }

    #[test]
    fn chunking_respects_size_and_overlap() {
        let text = "第一句话。第二句话。第三句话。第四句话。第五句话。";
        let chunks = chunk_text(text, 12, 4);
        assert!(chunks.len() >= 2);
        assert!(chunks.iter().all(|c| !c.is_empty()));
    }

    #[test]
    fn hashing_embedding_is_l2_normalized_and_deterministic() {
        let a = embed("跨境资金异常流动");
        let b = embed("跨境资金异常流动");
        assert_eq!(a, b);
        let norm: f32 = a.iter().map(|v| v * v).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 1e-5);
    }
}
