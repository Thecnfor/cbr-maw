//! JSON-RPC 2.0 错误码与内核错误类型（对齐 contracts/README.md §2）。

use serde_json::{json, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ErrorKind {
    Parse,
    InvalidRequest,
    MethodNotFound,
    InvalidParams,
    Internal,
    PlatformUnsupported,
    NotAuthorized,
    SourceUnavailable,
    DataMissing,
    ContractMismatch,
    RateLimited,
    Timeout,
    NotInitialized,
    PermissionDenied,
}

impl ErrorKind {
    pub fn code(self) -> i64 {
        match self {
            ErrorKind::Parse => -32700,
            ErrorKind::InvalidRequest => -32600,
            ErrorKind::MethodNotFound => -32601,
            ErrorKind::InvalidParams => -32602,
            ErrorKind::Internal => -32603,
            ErrorKind::PlatformUnsupported => -32001,
            ErrorKind::NotAuthorized => -32002,
            ErrorKind::SourceUnavailable => -32003,
            ErrorKind::DataMissing => -32004,
            ErrorKind::ContractMismatch => -32005,
            ErrorKind::RateLimited => -32006,
            ErrorKind::Timeout => -32007,
            ErrorKind::NotInitialized => -32008,
            ErrorKind::PermissionDenied => -32009,
        }
    }

    pub fn kind(self) -> &'static str {
        match self {
            ErrorKind::Parse => "E_PARSE",
            ErrorKind::InvalidRequest => "E_INVALID_REQUEST",
            ErrorKind::MethodNotFound => "E_METHOD_NOT_FOUND",
            ErrorKind::InvalidParams => "E_INVALID_PARAMS",
            ErrorKind::Internal => "E_INTERNAL",
            ErrorKind::PlatformUnsupported => "E_PLATFORM_UNSUPPORTED",
            ErrorKind::NotAuthorized => "E_NOT_AUTHORIZED",
            ErrorKind::SourceUnavailable => "E_SOURCE_UNAVAILABLE",
            ErrorKind::DataMissing => "E_DATA_MISSING",
            ErrorKind::ContractMismatch => "E_CONTRACT_MISMATCH",
            ErrorKind::RateLimited => "E_RATE_LIMITED",
            ErrorKind::Timeout => "E_TIMEOUT",
            ErrorKind::NotInitialized => "E_NOT_INITIALIZED",
            ErrorKind::PermissionDenied => "E_PERMISSION_DENIED",
        }
    }

    /// 默认 message（中文短句；具体调用可覆盖）。
    pub fn default_message(self) -> &'static str {
        match self {
            ErrorKind::Parse => "行不是合法 JSON",
            ErrorKind::InvalidRequest => "请求缺少 method/id",
            ErrorKind::MethodNotFound => "未知方法",
            ErrorKind::InvalidParams => "参数不合法",
            ErrorKind::Internal => "内部异常",
            ErrorKind::PlatformUnsupported => "该平台不支持本地计算",
            ErrorKind::NotAuthorized => "来源需授权",
            ErrorKind::SourceUnavailable => "来源不可达",
            ErrorKind::DataMissing => "必需数据缺失",
            ErrorKind::ContractMismatch => "契约或 schema 版本不匹配",
            ErrorKind::RateLimited => "被限流",
            ErrorKind::Timeout => "超时",
            ErrorKind::NotInitialized => "未握手",
            ErrorKind::PermissionDenied => "角色越权",
        }
    }

    pub fn retryable(self) -> bool {
        matches!(
            self,
            ErrorKind::SourceUnavailable | ErrorKind::RateLimited | ErrorKind::Timeout
        )
    }
}

#[derive(Debug, Clone)]
pub struct KernelError {
    pub kind: ErrorKind,
    pub message: String,
    pub detail: Value,
}

impl KernelError {
    pub fn new(kind: ErrorKind, message: impl Into<String>) -> Self {
        let message = message.into();
        Self {
            kind,
            detail: json!({"reason": message.clone()}),
            message,
        }
    }

    pub fn with_detail(mut self, detail: Value) -> Self {
        // 保证 detail.reason 始终存在（契约必填）。
        if detail.get("reason").is_none() {
            if let Value::Object(mut map) = detail {
                map.insert("reason".to_string(), Value::String(self.message.clone()));
                self.detail = Value::Object(map);
                return self;
            }
        }
        self.detail = detail;
        self
    }

    pub fn internal(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::Internal, message)
    }

    pub fn invalid_params(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::InvalidParams, message)
    }

    pub fn data_missing(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::DataMissing, message)
    }

    pub fn contract_mismatch(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::ContractMismatch, message)
    }

    pub fn not_initialized(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::NotInitialized, message)
    }

    pub fn permission_denied(message: impl Into<String>) -> Self {
        Self::new(ErrorKind::PermissionDenied, message)
    }

    pub fn method_not_found(method: &str) -> Self {
        Self::new(ErrorKind::MethodNotFound, format!("未知方法: {method}"))
    }

    pub fn to_error_object(&self) -> Value {
        json!({
            "code": self.kind.code(),
            "message": self.message,
            "data": {
                "kind": self.kind.kind(),
                "retryable": self.kind.retryable(),
                "detail": self.detail,
            }
        })
    }
}

impl std::fmt::Display for KernelError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "[{}] {}", self.kind.kind(), self.message)
    }
}

impl std::error::Error for KernelError {}

impl From<duckdb::Error> for KernelError {
    fn from(value: duckdb::Error) -> Self {
        KernelError::internal(format!("DuckDB: {value}"))
    }
}

pub type Result<T> = std::result::Result<T, KernelError>;
