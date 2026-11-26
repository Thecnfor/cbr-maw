// Package rpc 实现 NDJSON over stdio 的 JSON-RPC 2.0 传输层。
//
// stdout 只出协议消息；日志一律写 stderr（JSONL），由 logx 负责。
package rpc

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"sync"
)

// Error 是 JSON-RPC 2.0 错误对象。
type Error struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    *Data  `json:"data,omitempty"`
}

// Data 是错误明细（契约 §2）。
type Data struct {
	Kind      string         `json:"kind"`
	Retryable bool           `json:"retryable"`
	Detail    map[string]any `json:"detail"`
}

// Error 实现 error 接口。
func (e *Error) Error() string { return fmt.Sprintf("%s: %s", e.Kind(), e.Message) }

// Kind 返回错误 kind（E_xxx）。
func (e *Error) Kind() string {
	if e.Data != nil {
		return e.Data.Kind
	}
	return "E_INTERNAL"
}

// 错误码常量（契约 §2）。
const (
	CodeParse               = -32700
	CodeInvalidRequest      = -32600
	CodeMethodNotFound      = -32601
	CodeInvalidParams       = -32602
	CodeInternal            = -32603
	CodePlatformUnsupported = -32001
	CodeNotAuthorized       = -32002
	CodeSourceUnavailable   = -32003
	CodeDataMissing         = -32004
	CodeContractMismatch    = -32005
	CodeRateLimited         = -32006
	CodeTimeout             = -32007
	CodeNotInitialized      = -32008
	CodePermissionDenied    = -32009
)

// NewError 构造带契约字段的错误。
func NewError(code int, message, kind string, retryable bool, detail map[string]any) *Error {
	if detail == nil {
		detail = map[string]any{}
	}
	if _, ok := detail["reason"]; !ok {
		detail["reason"] = message
	}
	return &Error{Code: code, Message: message, Data: &Data{Kind: kind, Retryable: retryable, Detail: detail}}
}

// ErrInvalidParams 是参数错误的快捷构造。
func ErrInvalidParams(message, field string) *Error {
	detail := map[string]any{"reason": message}
	if field != "" {
		detail["field"] = field
	}
	return &Error{Code: CodeInvalidParams, Message: "参数不合法", Data: &Data{Kind: "E_INVALID_PARAMS", Retryable: false, Detail: detail}}
}

// Request 是入站消息（同时容纳请求与响应/通知）。
type Request struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      *string         `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params"`
}

// Response 是出站消息。
type Response struct {
	JSONRPC string  `json:"jsonrpc"`
	ID      *string `json:"id"`
	Result  any     `json:"result,omitempty"`
	Error   *Error  `json:"error,omitempty"`
}

// Handler 处理单个已解析的请求。
type Handler func(id *string, params json.RawMessage) (any, *Error)

// Server 是单线程（串行）消息循环。
type Server struct {
	in  io.Reader
	out io.Writer

	mu      sync.Mutex
	writeMu sync.Mutex

	handlers map[string]Handler
	stop     chan struct{}
	once     sync.Once
}

// NewServer 构造服务端。
func NewServer(in io.Reader, out io.Writer) *Server {
	return &Server{in: in, out: out, handlers: map[string]Handler{}, stop: make(chan struct{})}
}

// Register 注册方法处理器。
func (s *Server) Register(method string, handler Handler) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.handlers[method] = handler
}

// Stop 结束消息循环（shutdown 后调用）。
func (s *Server) Stop() {
	s.once.Do(func() { close(s.stop) })
}

// Serve 运行消息循环，直到 stdin EOF 或 Stop。
func (s *Server) Serve() error {
	reader := bufio.NewReaderSize(s.in, 1<<20)
	for {
		select {
		case <-s.stop:
			return nil
		default:
		}
		line, err := reader.ReadBytes('\n')
		if len(line) > 0 {
			s.handleLine(trimLine(line))
		}
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
	}
}

func trimLine(b []byte) []byte {
	for len(b) > 0 && (b[len(b)-1] == '\n' || b[len(b)-1] == '\r') {
		b = b[:len(b)-1]
	}
	return b
}

func (s *Server) handleLine(line []byte) {
	if len(line) == 0 {
		return
	}
	var req Request
	if err := json.Unmarshal(line, &req); err != nil {
		s.send(Response{JSONRPC: "2.0", Error: NewError(CodeParse, "行不是合法 JSON", "E_PARSE", false, map[string]any{"reason": "行不是合法 JSON"})})
		return
	}
	if req.JSONRPC != "2.0" || req.Method == "" {
		s.send(Response{JSONRPC: "2.0", ID: req.ID, Error: NewError(CodeInvalidRequest, "缺 method 或 jsonrpc 版本错误", "E_INVALID_REQUEST", false, map[string]any{"reason": "缺 method 或 jsonrpc 版本错误"})})
		return
	}
	s.mu.Lock()
	handler, ok := s.handlers[req.Method]
	s.mu.Unlock()
	if !ok {
		s.send(Response{JSONRPC: "2.0", ID: req.ID, Error: NewError(CodeMethodNotFound, "未知方法 "+req.Method, "E_METHOD_NOT_FOUND", false, map[string]any{"reason": "未知方法", "method": req.Method})})
		return
	}
	result, rpcErr := handler(req.ID, req.Params)
	if rpcErr != nil {
		s.send(Response{JSONRPC: "2.0", ID: req.ID, Error: rpcErr})
		return
	}
	s.send(Response{JSONRPC: "2.0", ID: req.ID, Result: result})
}

func (s *Server) send(resp Response) {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	enc := json.NewEncoder(s.out)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(resp)
}
