//! 工作区（DuckDB）生命周期、schema 与迁移。

use crate::error::{KernelError, Result};
use duckdb::Connection;
use serde_json::{json, Value};
use std::path::{Path, PathBuf};

/// 当前 schema 版本（与 `initialize.result.schema_version` 一致）。
pub const SCHEMA_VERSION: i64 = 3;

/// 已知历史版本（供 `workspace.migrate` 报错时列出）。
pub const AVAILABLE_VERSIONS: [i64; 3] = [1, 2, 3];

const SCHEMA_SQL: &str = r#"
CREATE TABLE IF NOT EXISTS meta(key VARCHAR PRIMARY KEY, value VARCHAR);

CREATE TABLE IF NOT EXISTS series_obs(
  series_id VARCHAR NOT NULL,
  obs_date DATE NOT NULL,
  value DOUBLE,
  release_time TIMESTAMP NOT NULL,
  source VARCHAR,
  unit VARCHAR,
  PRIMARY KEY(series_id, obs_date)
);

CREATE TABLE IF NOT EXISTS documents(
  doc_id VARCHAR PRIMARY KEY,
  publish_time TIMESTAMP NOT NULL,
  source VARCHAR,
  title VARCHAR,
  body VARCHAR,
  url VARCHAR,
  hash VARCHAR
);

CREATE TABLE IF NOT EXISTS series_meta(
  series_id VARCHAR PRIMARY KEY,
  name VARCHAR,
  source VARCHAR,
  frequency VARCHAR,
  coverage_start DATE,
  coverage_end DATE,
  release_lag_days INTEGER,
  pit_grade VARCHAR,
  unit VARCHAR,
  notes VARCHAR
);

CREATE TABLE IF NOT EXISTS signals(
  as_of DATE PRIMARY KEY,
  signal_id VARCHAR,
  value DOUBLE,
  level VARCHAR,
  dims VARCHAR,
  missing_dims VARCHAR,
  limitations VARCHAR,
  model_version VARCHAR,
  label_version VARCHAR,
  evidence_id VARCHAR
);

CREATE TABLE IF NOT EXISTS cfsi_history(
  as_of DATE PRIMARY KEY,
  cfsi DOUBLE,
  level VARCHAR,
  tau DOUBLE,
  dims VARCHAR,
  missing_dims VARCHAR,
  limitations VARCHAR,
  index_version VARCHAR,
  label_version VARCHAR
);

CREATE TABLE IF NOT EXISTS features(
  feature_id VARCHAR PRIMARY KEY,
  series_id VARCHAR,
  as_of DATE,
  name VARCHAR,
  value DOUBLE,
  unit VARCHAR,
  domain VARCHAR
);

CREATE TABLE IF NOT EXISTS ingest_batches(
  batch_id VARCHAR PRIMARY KEY,
  source VARCHAR,
  path VARCHAR,
  created_at TIMESTAMP,
  series_json VARCHAR,
  rows INTEGER,
  coverage_gate VARCHAR
);

CREATE TABLE IF NOT EXISTS audit_events(
  event_id VARCHAR PRIMARY KEY,
  ts TIMESTAMP,
  event_type VARCHAR,
  role VARCHAR,
  tool_name VARCHAR,
  detail VARCHAR
);

CREATE TABLE IF NOT EXISTS idempotency(
  idem_key VARCHAR PRIMARY KEY,
  method VARCHAR,
  result_json VARCHAR,
  created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS kb_chunks(
  chunk_id VARCHAR PRIMARY KEY,
  doc_id VARCHAR,
  title VARCHAR,
  source VARCHAR,
  publish_time DATE,
  url VARCHAR,
  tags VARCHAR,
  section VARCHAR,
  text VARCHAR,
  index_text VARCHAR,
  chunk_index INTEGER
);

CREATE TABLE IF NOT EXISTS kb_meta(key VARCHAR PRIMARY KEY, value VARCHAR);
"#;

pub struct Workspace {
    pub conn: Connection,
    pub path: PathBuf,
}

/// 与工作区一一对应的记忆目录（`<workspace>.memory`）。
///
/// 不用父目录：同一目录下多个工作区会共用一份记忆库（bench 分片互相污染）。
pub fn memory_root(workspace: &Path) -> PathBuf {
    PathBuf::from(format!("{}.memory", workspace.display()))
}

impl Workspace {
    pub fn open(path: &Path) -> Result<Self> {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                std::fs::create_dir_all(parent).map_err(|e| {
                    KernelError::internal(format!("无法创建工作区目录 {}: {e}", parent.display()))
                })?;
            }
        }
        let conn = Connection::open(path).map_err(|e| {
            KernelError::internal(format!("无法打开工作区 {}: {e}", path.display()))
        })?;
        let ws = Self {
            conn,
            path: path.to_path_buf(),
        };
        ws.initialize_schema()?;
        Ok(ws)
    }

    fn initialize_schema(&self) -> Result<()> {
        self.conn
            .execute_batch(SCHEMA_SQL)
            .map_err(|e| KernelError::internal(format!("初始化 schema 失败: {e}")))?;
        let current = self.schema_version()?;
        if current < SCHEMA_VERSION {
            self.migrate_to(SCHEMA_VERSION)?;
        }
        Ok(())
    }

    pub fn schema_version(&self) -> Result<i64> {
        let mut stmt = self
            .conn
            .prepare("SELECT value FROM meta WHERE key = 'schema_version'")
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let mut rows = stmt
            .query([])
            .map_err(|e| KernelError::internal(e.to_string()))?;
        if let Some(row) = rows
            .next()
            .map_err(|e| KernelError::internal(e.to_string()))?
        {
            let raw: String = row
                .get(0)
                .map_err(|e| KernelError::internal(e.to_string()))?;
            return Ok(raw.parse::<i64>().unwrap_or(0));
        }
        // 新库：版本由已有表结构决定；空库视为最新版本（首启即建全表）。
        self.set_meta("schema_version", &SCHEMA_VERSION.to_string())?;
        Ok(SCHEMA_VERSION)
    }

    fn migrate_to(&self, target: i64) -> Result<()> {
        if target > SCHEMA_VERSION {
            return Err(KernelError::contract_mismatch(format!(
                "目标 schema 版本 {target} 高于本内核支持的 {SCHEMA_VERSION}"
            ))
            .with_detail(json!({"target_version": target, "available": AVAILABLE_VERSIONS})));
        }
        // v1→v2→v3 均为增量表/列；建表语句本身幂等，迁移只更新版本号。
        self.conn
            .execute_batch(SCHEMA_SQL)
            .map_err(|e| KernelError::internal(format!("迁移失败: {e}")))?;
        self.set_meta("schema_version", &target.to_string())?;
        Ok(())
    }

    pub fn migrate(&self, target: i64) -> Result<Value> {
        if !AVAILABLE_VERSIONS.contains(&target) {
            return Err(
                KernelError::contract_mismatch(format!("目标版本 {target} 不存在")).with_detail(
                    json!({"target_version": target, "available": AVAILABLE_VERSIONS}),
                ),
            );
        }
        let from = self.schema_version()?;
        if target == from {
            return Ok(json!({"from": from, "to": target}));
        }
        if target < from {
            return Err(KernelError::contract_mismatch(format!(
                "不支持降级迁移 {from} → {target}"
            ))
            .with_detail(json!({"from": from, "to": target})));
        }
        self.migrate_to(target)?;
        Ok(json!({"from": from, "to": target}))
    }

    pub fn set_meta(&self, key: &str, value: &str) -> Result<()> {
        self.conn
            .execute(
                "INSERT INTO meta(key, value) VALUES (?, ?) \
                 ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                duckdb::params![key, value],
            )
            .map_err(|e| KernelError::internal(e.to_string()))?;
        Ok(())
    }

    pub fn get_meta(&self, key: &str) -> Result<Option<String>> {
        let mut stmt = self
            .conn
            .prepare("SELECT value FROM meta WHERE key = ?")
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let mut rows = stmt
            .query(duckdb::params![key])
            .map_err(|e| KernelError::internal(e.to_string()))?;
        match rows
            .next()
            .map_err(|e| KernelError::internal(e.to_string()))?
        {
            Some(row) => Ok(Some(
                row.get::<usize, String>(0)
                    .map_err(|e| KernelError::internal(e.to_string()))?,
            )),
            None => Ok(None),
        }
    }

    pub fn info(&self) -> Result<Value> {
        let series_count = self.scalar_i64("SELECT count(DISTINCT series_id) FROM series_obs")?;
        let obs_count = self.scalar_i64("SELECT count(*) FROM series_obs")?;
        let last_ingest_at = self.get_meta("last_ingest_at")?;
        let size_bytes = std::fs::metadata(&self.path)
            .map(|m| m.len() as i64)
            .unwrap_or(0);
        Ok(json!({
            "path": self.path.display().to_string(),
            "size_bytes": size_bytes,
            "schema_version": self.schema_version()?,
            "series_count": series_count,
            "obs_count": obs_count,
            "last_ingest_at": last_ingest_at,
        }))
    }

    pub fn scalar_i64(&self, sql: &str) -> Result<i64> {
        let mut stmt = self
            .conn
            .prepare(sql)
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let mut rows = stmt
            .query([])
            .map_err(|e| KernelError::internal(e.to_string()))?;
        match rows
            .next()
            .map_err(|e| KernelError::internal(e.to_string()))?
        {
            Some(row) => Ok(row.get::<usize, i64>(0).unwrap_or(0)),
            None => Ok(0),
        }
    }

    /// 读取序列的时点历史（`release_time <= as_of`），按 obs_date 升序。
    pub fn history(
        &self,
        series_id: &str,
        as_of_ts: &str,
        lookback: Option<usize>,
    ) -> Result<Vec<(String, f64)>> {
        let mut stmt = self
            .conn
            .prepare(
                "SELECT obs_date, value FROM series_obs \
                 WHERE series_id = ? AND release_time <= CAST(? AS TIMESTAMP) AND value IS NOT NULL \
                 ORDER BY obs_date ASC",
            )
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let mut rows = stmt
            .query(duckdb::params![series_id, as_of_ts])
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let mut out = Vec::new();
        while let Some(row) = rows
            .next()
            .map_err(|e| KernelError::internal(e.to_string()))?
        {
            let day: chrono::NaiveDate = row
                .get(0)
                .map_err(|e| KernelError::internal(e.to_string()))?;
            let value: f64 = row
                .get(1)
                .map_err(|e| KernelError::internal(e.to_string()))?;
            out.push((day.format("%Y-%m-%d").to_string(), value));
        }
        if let Some(limit) = lookback {
            if limit > 0 && out.len() > limit {
                out = out.split_off(out.len() - limit);
            }
        }
        Ok(out)
    }

    /// 幂等键命中则返回已存结果。
    pub fn idempotent_result(&self, key: &str) -> Result<Option<Value>> {
        let mut stmt = self
            .conn
            .prepare("SELECT result_json FROM idempotency WHERE idem_key = ?")
            .map_err(|e| KernelError::internal(e.to_string()))?;
        let mut rows = stmt
            .query(duckdb::params![key])
            .map_err(|e| KernelError::internal(e.to_string()))?;
        match rows
            .next()
            .map_err(|e| KernelError::internal(e.to_string()))?
        {
            Some(row) => {
                let raw: String = row
                    .get(0)
                    .map_err(|e| KernelError::internal(e.to_string()))?;
                Ok(serde_json::from_str(&raw).ok())
            }
            None => Ok(None),
        }
    }

    pub fn remember_idempotent(&self, key: &str, method: &str, result: &Value) -> Result<()> {
        self.conn
            .execute(
                "INSERT INTO idempotency(idem_key, method, result_json, created_at) \
                 VALUES (?, ?, ?, now()) ON CONFLICT(idem_key) DO NOTHING",
                duckdb::params![
                    key,
                    method,
                    serde_json::to_string(result).unwrap_or_default()
                ],
            )
            .map_err(|e| KernelError::internal(e.to_string()))?;
        Ok(())
    }
}

#[cfg(test)]
mod memory_root_tests {
    use super::memory_root;
    use std::path::Path;

    #[test]
    fn memory_root_is_per_workspace() {
        let a = memory_root(Path::new("/tmp/a.duckdb"));
        let b = memory_root(Path::new("/tmp/b.duckdb"));
        assert_eq!(a.to_string_lossy(), "/tmp/a.duckdb.memory");
        assert_ne!(a, b, "不同工作区不得共用记忆目录");
        // 同一目录下的工作区也必须分开（历史 bug 的回归点）。
        assert_eq!(a.parent(), b.parent());
    }
}
