package rpc

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// TestServeNDJSON 一行一个消息；stdout 只有协议消息。
func TestServeNDJSON(t *testing.T) {
	in := strings.NewReader(`{"jsonrpc":"2.0","id":"1","method":"ping","params":{}}
{"jsonrpc":"2.0","id":"2","method":"nope","params":{}}
not-json
{"jsonrpc":"2.0","id":"3","method":"ping","params":{}}
`)
	out := &bytes.Buffer{}
	srv := NewServer(in, out)
	srv.Register("ping", func(id *string, _ json.RawMessage) (any, *Error) {
		return map[string]any{"pong": true}, nil
	})
	if err := srv.Serve(); err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(out.String()), "\n")
	if len(lines) != 4 {
		t.Fatalf("响应行数 = %d，期望 4：\n%s", len(lines), out.String())
	}
	var first Response
	if err := json.Unmarshal([]byte(lines[0]), &first); err != nil {
		t.Fatal(err)
	}
	if first.ID == nil || *first.ID != "1" {
		t.Fatalf("id 回传错误: %+v", first)
	}
	var second Response
	if err := json.Unmarshal([]byte(lines[1]), &second); err != nil {
		t.Fatal(err)
	}
	if second.Error == nil || second.Error.Code != CodeMethodNotFound {
		t.Fatalf("未知方法错误码错误: %+v", second.Error)
	}
	var third Response
	if err := json.Unmarshal([]byte(lines[2]), &third); err != nil {
		t.Fatal(err)
	}
	if third.Error == nil || third.Error.Code != CodeParse {
		t.Fatalf("解析错误码错误: %+v", third.Error)
	}
}

// TestErrorShapeMatchesContract 错误对象必须含 kind/retryable/detail.reason。
func TestErrorShapeMatchesContract(t *testing.T) {
	err := ErrInvalidParams("timeout_s 必须在 1..300 之间", "timeout_s")
	raw, marshalErr := json.Marshal(err)
	if marshalErr != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if uerr := json.Unmarshal(raw, &decoded); uerr != nil {
		t.Fatal(uerr)
	}
	data := decoded["data"].(map[string]any)
	if data["kind"] != "E_INVALID_PARAMS" || data["retryable"] != false {
		t.Fatalf("错误结构错误: %s", raw)
	}
	detail := data["detail"].(map[string]any)
	if detail["reason"] == "" || detail["field"] != "timeout_s" {
		t.Fatalf("detail 错误: %s", raw)
	}
}
