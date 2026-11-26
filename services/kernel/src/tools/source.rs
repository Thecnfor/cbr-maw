//! 工具运行上下文：数据读取接口 + 共享风险信号读取。
//!
//! 工具只通过本 trait 读数据（PIT 过滤在实现侧强制），
//! 便于单测用内存实现替换 DuckDB。

use serde_json::Value;

/// 一条观测：(obs_date "YYYY-MM-DD", value)。
pub type ObsRow = (String, f64);

pub trait DataSource {
    /// 时点历史：`release_time <= as_of`，按 obs_date 升序。
    fn history(&self, series_id: &str, as_of: &str, lookback: Option<usize>) -> Vec<ObsRow>;

    /// 共享多模态风险信号（`forecast` 工具读取）；未就绪返回 None。
    fn risk_signal(&self, _as_of: &str) -> Option<Value> {
        None
    }

    /// CFSI 六维序列（`dimension_dispersion` / `capital_linkage` 工具）；需要 DuckDB 宽表，内存实现返回 None。
    fn cfsi_series(&self, _as_of: &str) -> Option<crate::cfsi::CfsiSeries> {
        None
    }

    /// 全部日频序列的交易日并集（`capital_linkage` 对齐窗口用）；内存实现返回 None。
    fn daily_calendar(&self, _as_of: &str) -> Option<Vec<String>> {
        None
    }

    /// 知识库检索（`knowledge_search` 工具）；未建索引返回 None。
    fn kb_search(
        &self,
        _query: &str,
        _as_of: &str,
        _top_k: usize,
        _tags: Option<&[String]>,
    ) -> Option<Vec<Value>> {
        None
    }
}

/// 内存实现（测试用）。
#[derive(Default, Clone)]
pub struct MemorySource {
    pub series: std::collections::BTreeMap<String, Vec<ObsRow>>,
    pub signal: Option<Value>,
    pub kb: Option<Vec<Value>>,
}

impl MemorySource {
    pub fn with_series(mut self, series_id: &str, rows: Vec<ObsRow>) -> Self {
        self.series.insert(series_id.to_string(), rows);
        self
    }
}

impl DataSource for MemorySource {
    fn history(&self, series_id: &str, as_of: &str, lookback: Option<usize>) -> Vec<ObsRow> {
        let Some(rows) = self.series.get(series_id) else {
            return Vec::new();
        };
        let mut out: Vec<ObsRow> = rows
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

    fn risk_signal(&self, _as_of: &str) -> Option<Value> {
        self.signal.clone()
    }

    fn kb_search(
        &self,
        _query: &str,
        _as_of: &str,
        top_k: usize,
        _tags: Option<&[String]>,
    ) -> Option<Vec<Value>> {
        self.kb
            .as_ref()
            .map(|hits| hits.iter().take(top_k).cloned().collect())
    }
}
