//! 本地向量化（`fastembed` + BGE-small-zh-v1.5，512 维）。
//!
//! 为什么放在 kernel 而不是 Dart（docs/24 §D4）：
//! - 端点实测没有 `/v1/embeddings`，云端向量不可用；
//! - 离线、确定性、可复现是论文的硬要求；
//! - kernel 是记忆的唯一写入者，向量与记录同源落盘。
//!
//! 模型首次使用时下载到 `<workspace>/models/`，失败**不伪造**：
//! 上游退回 LanceDB FTS，并把原因写进 `memory.stats.embedding_error`。

use std::path::Path;
use std::sync::Mutex;

use sha2::Digest;

use fastembed::{
    EmbeddingModel, InitOptionsUserDefined, Pooling, TextEmbedding, TextInitOptions,
    TokenizerFiles, UserDefinedEmbeddingModel,
};

use crate::error::{ErrorKind, KernelError, Result};
use crate::memory::Embedder;

/// BGE-small-zh-v1.5 的输出维度。
const BGE_SMALL_ZH_DIM: usize = 512;
/// 离线模型目录名（与 `packaging/prefetch_embedding_model.py` 保持一致）。
const OFFLINE_DIR: &str = "bge-small-zh-v1.5";

/// 本地嵌入器。`TextEmbedding::embed` 需要 `&mut self`，故用互斥量串行化。
pub struct LocalEmbedder {
    model: Mutex<TextEmbedding>,
}

impl LocalEmbedder {
    /// 初始化模型。`cache_dir` 为模型缓存根（`<workspace>/models`）。
    ///
    /// 两条路径：
    /// 1. **离线包**：`<cache>/bge-small-zh-v1.5/` 下有 `manifest.json` 与模型文件，
    ///    逐文件校验 SHA256 后用 `try_new_from_user_defined` 加载（可复现、无网络）；
    /// 2. **HF 缓存**：交给 fastembed 自带下载（镜像缺 ETag 头时会失败，故只作兜底）。
    ///
    /// 失败时返回中文原因字符串，由调用方决定是降级还是报错。
    pub fn new(cache_dir: &Path) -> std::result::Result<Self, String> {
        let _ = std::fs::create_dir_all(cache_dir);
        let offline = cache_dir.join(OFFLINE_DIR);
        if offline.join("manifest.json").exists() {
            return Self::from_offline_dir(&offline);
        }
        // fastembed 通过环境变量读取缓存目录（无 API 参数可用）。
        std::env::set_var("FASTEMBED_CACHE_DIR", cache_dir);
        let model = TextEmbedding::try_new(
            TextInitOptions::new(EmbeddingModel::BGESmallZHV15)
                .with_max_length(512)
                .with_intra_threads(2),
        )
        .map_err(|e| {
            format!(
                "本地向量模型初始化失败：{e}
                 离线安装：python3 packaging/prefetch_embedding_model.py --out {}
                 或关闭向量化：CBR_EMBEDDING=off",
                cache_dir.display()
            )
        })?;
        Ok(Self {
            model: Mutex::new(model),
        })
    }

    /// 从离线目录加载，并逐文件校验 SHA256（清单由 `packaging/prefetch_embedding_model.py` 生成）。
    fn from_offline_dir(dir: &Path) -> std::result::Result<Self, String> {
        let manifest_raw = std::fs::read_to_string(dir.join("manifest.json"))
            .map_err(|e| format!("读取模型清单失败：{e}"))?;
        let manifest: serde_json::Value =
            serde_json::from_str(&manifest_raw).map_err(|e| format!("模型清单不是合法 JSON：{e}"))?;
        let files = manifest
            .get("files")
            .and_then(|v| v.as_object())
            .ok_or_else(|| "模型清单缺少 files 字段".to_string())?;

        let read_verified = |name: &str| -> std::result::Result<Vec<u8>, String> {
            let expected = files
                .get(name)
                .and_then(|v| v.as_str())
                .ok_or_else(|| format!("模型清单缺少 {name} 的哈希"))?;
            let bytes = std::fs::read(dir.join(name))
                .map_err(|e| format!("缺少模型文件 {name}：{e}"))?;
            let actual = format!("{:x}", sha2::Sha256::digest(&bytes));
            if actual != expected {
                return Err(format!(
                    "模型文件 {name} 校验失败（期望 {expected}，实际 {actual}）——请重跑预取脚本"
                ));
            }
            Ok(bytes)
        };

        let tokenizer_files = TokenizerFiles {
            tokenizer_file: read_verified("tokenizer.json")?,
            config_file: read_verified("config.json")?,
            special_tokens_map_file: read_verified("special_tokens_map.json")?,
            tokenizer_config_file: read_verified("tokenizer_config.json")?,
        };
        let model = UserDefinedEmbeddingModel::new(read_verified("model.onnx")?, tokenizer_files)
            .with_pooling(Pooling::Cls);
        let mut options = InitOptionsUserDefined::default();
        options.max_length = 512;
        options.intra_threads = Some(2);
        let embedding = TextEmbedding::try_new_from_user_defined(model, options)
            .map_err(|e| format!("离线模型加载失败：{e}"))?;
        Ok(Self {
            model: Mutex::new(embedding),
        })
    }
}

impl Embedder for LocalEmbedder {
    fn dim(&self) -> usize {
        BGE_SMALL_ZH_DIM
    }

    fn embed(&self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        if texts.is_empty() {
            return Ok(Vec::new());
        }
        let mut model = self
            .model
            .lock()
            .map_err(|_| KernelError::new(ErrorKind::Internal, "嵌入模型互斥量被污染"))?;
        model.embed(texts, Some(16)).map_err(|e| {
            KernelError::new(ErrorKind::Internal, format!("向量化失败：{e}")).with_detail(
                serde_json::json!({"reason": "本地模型推理失败", "texts": texts.len()}),
            )
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::memory::EMBED_DIM;

    #[test]
    fn dim_matches_memory_schema() {
        assert_eq!(BGE_SMALL_ZH_DIM, EMBED_DIM);
    }
}
