// Package logx 把日志以 JSONL 写到 stderr，保证 stdout 只出协议消息。
package logx

import (
	"encoding/json"
	"io"
	"os"
	"sync"
	"time"
)

// Logger 是 stderr JSONL 日志器。
type Logger struct {
	mu      sync.Mutex
	out     io.Writer
	sidecar string
	level   int
}

var levels = map[string]int{"debug": 0, "info": 1, "warn": 2, "error": 3}

// New 构造日志器。
func New(sidecar, level string) *Logger {
	lv, ok := levels[level]
	if !ok {
		lv = 1
	}
	return &Logger{out: os.Stderr, sidecar: sidecar, level: lv}
}

func (l *Logger) log(level, msg string, fields map[string]any) {
	if levels[level] < l.level {
		return
	}
	entry := map[string]any{
		"ts":      time.Now().Format(time.RFC3339),
		"level":   level,
		"sidecar": l.sidecar,
		"msg":     msg,
	}
	for k, v := range fields {
		entry[k] = v
	}
	raw, err := json.Marshal(entry)
	if err != nil {
		return
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	_, _ = l.out.Write(append(raw, '\n'))
}

// Debug 记录调试日志。
func (l *Logger) Debug(msg string, fields map[string]any) { l.log("debug", msg, fields) }

// Info 记录信息日志。
func (l *Logger) Info(msg string, fields map[string]any) { l.log("info", msg, fields) }

// Warn 记录警告日志。
func (l *Logger) Warn(msg string, fields map[string]any) { l.log("warn", msg, fields) }

// Error 记录错误日志。
func (l *Logger) Error(msg string, fields map[string]any) { l.log("error", msg, fields) }
