// Package evidence 实现三级哈希与来源证据（契约 §6）。
//
// 哈希口径与旧版 Python 逐字节一致：
//
//	sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
//
// 因此本包自实现紧凑 JSON 序列化（键升序、无多余空白、非 ASCII 原样输出、
// 浮点用最短往返表示且不带指数尾零差异），不依赖 encoding/json 的默认转义。
package evidence

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"math"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// SourceEvidence 是一次取数行为的来源证据（契约 §3 collect.run / §5 PIT）。
//
// 每个进入下游的数值都必须携带本结构，否则视为无证据数值。
type SourceEvidence struct {
	EvidenceID     string `json:"evidence_id"`
	SourceID       string `json:"source_id"`
	HTTPStatus     *int   `json:"http_status,omitempty"`
	ResponseSHA256 string `json:"response_sha256,omitempty"`
	RequestURL     string `json:"request_url,omitempty"`
	FetchedAt      string `json:"fetched_at"`
	FileSHA256     string `json:"file_sha256,omitempty"`
	File           string `json:"file,omitempty"`
	Hash           string `json:"hash"`
}

// FileEvidence 是 inbox.ingest 的文件级证据（契约 inbox.ingest.response）。
type FileEvidence struct {
	EvidenceID     string  `json:"evidence_id"`
	SourceID       *string `json:"source_id"`
	DeclaredSource *string `json:"declared_source"`
	Rows           int     `json:"rows"`
	DroppedRows    int     `json:"dropped_rows"`
	Hash           string  `json:"hash"`
	// 文件级溯源：文件名 / 本地路径 / 抓取或读取时刻。
	File     string `json:"file,omitempty"`
	FilePath string `json:"file_path,omitempty"`
	ReadAt   string `json:"read_at,omitempty"`
}

// SHA256Hex 返回字节串的 64 位小写 hex。
func SHA256Hex(b []byte) string {
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

// SHA256String 返回字符串的 64 位小写 hex。
func SHA256String(s string) string { return SHA256Hex([]byte(s)) }

// InputsHash 计算工具入参哈希（契约 §6 inputs_hash）。
func InputsHash(payload map[string]any) string {
	return SHA256Hex(CanonicalJSON(payload))
}

// EvidenceID 由 {tool, version, inputs_hash} 生成证据 ID（契约 §6 evidence_id）。
func EvidenceID(tool, version, inputsHash string) string {
	h := SHA256Hex([]byte(fmt.Sprintf("%s|%s|%s", tool, version, inputsHash)))
	return "ev_" + h[:16]
}

// Hash 计算证据载荷哈希（契约 §6 evidence_hash）。
//
// payload 至少包含 value / unit / as_of / 来源证据。
func Hash(payload map[string]any) string {
	return SHA256Hex(CanonicalJSON(payload))
}

// CanonicalJSON 以契约规定的紧凑形式序列化对象：键升序、分隔符 (",", ":")、
// 非 ASCII 原样输出（等价 Python ensure_ascii=False）。
func CanonicalJSON(v any) []byte {
	var b strings.Builder
	writeCanonical(&b, v)
	return []byte(b.String())
}

func writeCanonical(b *strings.Builder, v any) {
	switch t := v.(type) {
	case nil:
		b.WriteString("null")
	case bool:
		if t {
			b.WriteString("true")
		} else {
			b.WriteString("false")
		}
	case string:
		writeJSONString(b, t)
	case int:
		b.WriteString(strconv.FormatInt(int64(t), 10))
	case int32:
		b.WriteString(strconv.FormatInt(int64(t), 10))
	case int64:
		b.WriteString(strconv.FormatInt(t, 10))
	case uint64:
		b.WriteString(strconv.FormatUint(t, 10))
	case float64:
		b.WriteString(formatFloat(t))
	case float32:
		b.WriteString(formatFloat(float64(t)))
	case []any:
		b.WriteByte('[')
		for i, item := range t {
			if i > 0 {
				b.WriteByte(',')
			}
			writeCanonical(b, item)
		}
		b.WriteByte(']')
	case map[string]any:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		b.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				b.WriteByte(',')
			}
			writeJSONString(b, k)
			b.WriteByte(':')
			writeCanonical(b, t[k])
		}
		b.WriteByte('}')
	default:
		// 未知类型退化为字符串，避免静默丢字段。
		writeJSONString(b, fmt.Sprint(v))
	}
}

// formatFloat 输出 Python repr 等价的最短往返表示。
func formatFloat(f float64) string {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return "null" // 与旧版 to_native 一致：NaN/Inf → null
	}
	s := strconv.FormatFloat(f, 'g', -1, 64)
	// Python repr：指数 >= 16 时用科学计数（1e+16），否则定点（1000000.0）；
	// 负指数 < -4 时用科学计数（1e-05），与 Go 'g' 一致，无需转换。
	if strings.Contains(s, "e") {
		_, exp, _ := strings.Cut(s, "e")
		if expI, err := strconv.Atoi(exp); err == nil && expI >= 0 && expI < 16 {
			s = strconv.FormatFloat(f, 'f', -1, 64)
		}
	}
	if !strings.ContainsAny(s, ".eE") {
		s += ".0"
	}
	return s
}

const hexDigits = "0123456789abcdef"

func writeJSONString(b *strings.Builder, s string) {
	b.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			b.WriteString(`\"`)
		case '\\':
			b.WriteString(`\\`)
		case '\n':
			b.WriteString(`\n`)
		case '\r':
			b.WriteString(`\r`)
		case '\t':
			b.WriteString(`\t`)
		case '\b':
			b.WriteString(`\b`)
		case '\f':
			b.WriteString(`\f`)
		default:
			if r < 0x20 {
				b.WriteString(`\u00`)
				b.WriteByte(hexDigits[(r>>4)&0xF])
				b.WriteByte(hexDigits[r&0xF])
				continue
			}
			if r == utf8.RuneError {
				b.WriteString(`�`)
				continue
			}
			b.WriteRune(r)
		}
	}
	b.WriteByte('"')
}
