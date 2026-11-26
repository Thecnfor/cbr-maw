//! 规范化 JSON 与哈希（与旧版 Python 逐字节一致）。
//!
//! 旧实现：`sha256(json.dumps(obj, sort_keys=True, separators=(",",":"), ensure_ascii=False))`，
//! 浮点先过 `to_native`（NaN/Inf → null、date/datetime → isoformat）。
//!
//! 与 `serde_json` 的差异只在浮点字面量：Python 用 `repr(float)`，
//! 例如 `1e16` → `1e+16`、`1e-05` → `1e-05`、`-0.0` → `-0.0`；
//! serde_json 用 ryu，输出 `1e16` / `1e-5` / `-0.0`。
//! 因此这里自行实现 Python `repr(float)` 兼容格式化，其余（键排序、紧凑分隔符、
//! 保留中文）沿用等价规则。

use sha2::{Digest, Sha256};
use std::fmt::Write as _;

/// 规范化为可 JSON 序列化的原生结构（对应旧版 `to_native`）。
///
/// 递归处理：NaN/Inf → null；对象键排序；数组保序。
pub fn to_native(value: &serde_json::Value) -> serde_json::Value {
    match value {
        serde_json::Value::Array(items) => {
            serde_json::Value::Array(items.iter().map(to_native).collect())
        }
        serde_json::Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (key, val) in map {
                out.insert(key.clone(), to_native(val));
            }
            serde_json::Value::Object(out)
        }
        serde_json::Value::Number(num) => {
            if let Some(f) = num.as_f64() {
                if !f.is_finite() {
                    return serde_json::Value::Null;
                }
            }
            value.clone()
        }
        other => other.clone(),
    }
}

/// 规范化 JSON 字符串（键排序 + 紧凑分隔符 + 保留中文 + Python 浮点字面量）。
pub fn canonical_json(value: &serde_json::Value) -> String {
    let native = to_native(value);
    let mut out = String::new();
    write_canonical(&native, &mut out);
    out
}

fn write_canonical(value: &serde_json::Value, out: &mut String) {
    match value {
        serde_json::Value::Null => out.push_str("null"),
        serde_json::Value::Bool(true) => out.push_str("true"),
        serde_json::Value::Bool(false) => out.push_str("false"),
        serde_json::Value::Number(num) => {
            if let Some(i) = num.as_i64() {
                let _ = write!(out, "{i}");
            } else if let Some(u) = num.as_u64() {
                let _ = write!(out, "{u}");
            } else if let Some(f) = num.as_f64() {
                if f.is_finite() {
                    out.push_str(&python_repr_f64(f));
                } else {
                    out.push_str("null");
                }
            } else {
                out.push_str(&num.to_string());
            }
        }
        serde_json::Value::String(s) => {
            // serde_json 的字符串转义与 Python `ensure_ascii=False` 一致：
            // 只转义 `"`、`\` 与 < 0x20 的控制字符，非 ASCII 原样输出。
            out.push_str(&serde_json::to_string(s).expect("string serialization cannot fail"));
        }
        serde_json::Value::Array(items) => {
            out.push('[');
            for (idx, item) in items.iter().enumerate() {
                if idx > 0 {
                    out.push(',');
                }
                write_canonical(item, out);
            }
            out.push(']');
        }
        serde_json::Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            // Python `sort_keys=True` 按码位排序；UTF-8 字节序与码位序一致。
            keys.sort_unstable();
            out.push('{');
            for (idx, key) in keys.iter().enumerate() {
                if idx > 0 {
                    out.push(',');
                }
                out.push_str(&serde_json::to_string(key).expect("key serialization cannot fail"));
                out.push(':');
                write_canonical(&map[*key], out);
            }
            out.push('}');
        }
    }
}

/// Python `repr(float)` 兼容格式化。
///
/// Python 用「能往返（round-trip）的最短十进制」，并在十进制指数
/// `decpt <= -4` 或 `decpt > 16` 时改用科学计数法；指数至少两位并带符号。
/// 例：`1e16` → `1e+16`、`1e-05` → `1e-05`、`0.1` → `0.1`、`-0.0` → `-0.0`。
pub fn python_repr_f64(value: f64) -> String {
    if !value.is_finite() {
        return "null".to_string();
    }
    if value == 0.0 {
        return if value.is_sign_negative() {
            "-0.0".to_string()
        } else {
            "0.0".to_string()
        };
    }
    // Rust 的 `{:e}` 给出可往返的最短尾数（如 `1.2345e-7`）。
    let sci = format!("{value:e}");
    let (mantissa, exp) = sci.split_once('e').expect("LowerExp always emits 'e'");
    let exp: i32 = exp.parse().expect("LowerExp emits a decimal exponent");
    let negative = mantissa.starts_with('-');
    let mantissa = mantissa.trim_start_matches('-');
    let digits: String = mantissa.chars().filter(|c| c.is_ascii_digit()).collect();
    // value = 0.<digits> * 10^decpt
    let decpt = exp + 1;

    let mut out = String::new();
    if negative {
        out.push('-');
    }
    if decpt <= -4 || decpt > 16 {
        out.push_str(&digits[..1]);
        if digits.len() > 1 {
            out.push('.');
            out.push_str(&digits[1..]);
        }
        out.push('e');
        let e = decpt - 1;
        if e < 0 {
            out.push('-');
        } else {
            out.push('+');
        }
        let _ = write!(out, "{:02}", e.abs());
    } else if decpt <= 0 {
        out.push_str("0.");
        for _ in 0..-decpt {
            out.push('0');
        }
        out.push_str(&digits);
    } else if decpt as usize >= digits.len() {
        out.push_str(&digits);
        for _ in 0..(decpt as usize - digits.len()) {
            out.push('0');
        }
        out.push_str(".0");
    } else {
        out.push_str(&digits[..decpt as usize]);
        out.push('.');
        out.push_str(&digits[decpt as usize..]);
    }
    out
}

/// sha256 十六进制小写摘要。
pub fn sha256_text(text: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    hex_lower(&hasher.finalize())
}

fn hex_lower(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        let _ = write!(out, "{byte:02x}");
    }
    out
}

/// 工具入参哈希：`sha256(canonical_json({tool, version, as_of, params}))`。
pub fn compute_inputs_hash(
    tool: &str,
    version: &str,
    as_of: &str,
    params: &serde_json::Value,
) -> String {
    let payload = serde_json::json!({
        "tool": tool,
        "version": version,
        "as_of": as_of,
        "params": to_native(params),
    });
    sha256_text(&canonical_json(&payload))
}

/// 证据 ID：`"ev_" + sha256(canonical_json({tool, version, inputs_hash}))[:16]`。
pub fn compute_evidence_id(tool: &str, version: &str, inputs_hash: &str) -> String {
    let payload = serde_json::json!({
        "tool": tool,
        "version": version,
        "inputs_hash": inputs_hash,
    });
    let digest = sha256_text(&canonical_json(&payload));
    format!("ev_{}", &digest[..16])
}

/// 证据载荷哈希：`sha256(canonical_json(payload))`。
pub fn compute_evidence_hash(payload: &serde_json::Value) -> String {
    sha256_text(&canonical_json(payload))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn python_repr_matches_cpython() {
        let cases: &[(f64, &str)] = &[
            (0.1, "0.1"),
            (1.0, "1.0"),
            (-0.0, "-0.0"),
            (1e16, "1e+16"),
            (1e15, "1000000000000000.0"),
            (1e-5, "1e-05"),
            (1e-4, "0.0001"),
            (1e100, "1e+100"),
            (1.5e16, "1.5e+16"),
            (8.42, "8.42"),
            (0.35, "0.35"),
            (-1.25, "-1.25"),
            (123.456, "123.456"),
            (0.0, "0.0"),
            (1e-7, "1e-07"),
            (0.000123, "0.000123"),
        ];
        for (value, expected) in cases {
            assert_eq!(python_repr_f64(*value), *expected, "value={value}");
        }
    }

    #[test]
    fn canonical_json_sorts_keys_and_keeps_chinese() {
        let value = json!({"b": 1, "a": {"z": [1, 2], "y": "中文"}});
        assert_eq!(
            canonical_json(&value),
            "{\"a\":{\"y\":\"中文\",\"z\":[1,2]},\"b\":1}"
        );
    }

    #[test]
    fn golden_hash_vectors_match_legacy_python() {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../contracts/golden-vectors/hash_vectors.json"
        );
        let raw = std::fs::read_to_string(path).expect("read golden vectors");
        let doc: serde_json::Value = serde_json::from_str(&raw).expect("parse golden vectors");
        let vectors = doc["vectors"].as_array().expect("vectors array");
        assert!(!vectors.is_empty());
        for vector in vectors {
            let name = vector["name"].as_str().unwrap_or_default();
            let tool = vector["tool"].as_str().expect("tool");
            let version = vector["version"].as_str().expect("version");
            let as_of = vector["as_of"].as_str().expect("as_of");
            let params = &vector["params"];

            let canonical = canonical_json(&json!({
                "tool": tool, "version": version, "as_of": as_of, "params": params,
            }));
            assert_eq!(
                canonical,
                vector["canonical_json"].as_str().unwrap(),
                "canonical {name}"
            );

            let inputs_hash = sha256_text(&canonical);
            assert_eq!(
                inputs_hash,
                vector["inputs_hash"].as_str().unwrap(),
                "inputs_hash {name}"
            );

            let evidence_id = compute_evidence_id(tool, version, &inputs_hash);
            assert_eq!(
                evidence_id,
                vector["evidence_id"].as_str().unwrap(),
                "evidence_id {name}"
            );

            let evidence_hash = compute_evidence_hash(&vector["evidence_payload"]);
            assert_eq!(
                evidence_hash,
                vector["evidence_hash"].as_str().unwrap(),
                "evidence_hash {name}"
            );
        }
    }
}
