// Package output 写规范化中间文件（NDJSON）与证据清单。
//
// Go 侧只产出中间文件 + 证据，**不写 DuckDB**；落库由 kernel 的 pit.ingest 完成。
package output

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// WriteNDJSON 把任意记录逐行写成 UTF-8 NDJSON，返回写入路径。
func WriteNDJSON(dir, filename string, records []any) (string, error) {
	if dir == "" {
		return "", fmt.Errorf("未配置中间文件目录")
	}
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("创建中间文件目录失败: %w", err)
	}
	path := filepath.Join(dir, sanitize(filename))
	f, err := os.Create(path)
	if err != nil {
		return "", fmt.Errorf("创建中间文件失败: %w", err)
	}
	defer f.Close()
	w := bufio.NewWriter(f)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	for _, rec := range records {
		if err := enc.Encode(rec); err != nil {
			return "", fmt.Errorf("写入 NDJSON 失败: %w", err)
		}
	}
	if err := w.Flush(); err != nil {
		return "", fmt.Errorf("刷新中间文件失败: %w", err)
	}
	return path, nil
}

// sanitize 把序列 ID 之类的字符串变成安全文件名。
func sanitize(name string) string {
	return strings.NewReplacer("/", "_", "\\", "_", ":", "_", "*", "_", "?", "_", "\"", "_", "<", "_", ">", "_", "|", "_").Replace(name)
}
