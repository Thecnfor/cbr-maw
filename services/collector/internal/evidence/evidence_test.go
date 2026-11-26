package evidence

import (
	"strings"
	"testing"
)

// TestCanonicalJSONMatchesPython 校验紧凑 JSON 与 Python json.dumps(sort_keys=True,
// separators=(",",":"), ensure_ascii=False) 的字节一致。
func TestCanonicalJSONMatchesPython(t *testing.T) {
	cases := []struct {
		in   map[string]any
		want string
	}{
		{map[string]any{"b": 1, "a": 2}, `{"a":2,"b":1}`},
		{map[string]any{"name": "沪深300", "v": 1.5}, `{"name":"沪深300","v":1.5}`},
		{map[string]any{"x": []any{1, 2, 3}}, `{"x":[1,2,3]}`},
		{map[string]any{"n": nil, "t": true}, `{"n":null,"t":true}`},
		{map[string]any{"f": 1000000.0}, `{"f":1000000.0}`},
		{map[string]any{"f": 1e-05}, `{"f":1e-05}`}, // Python repr 同款科学计数
		{map[string]any{"f": 1e16}, `{"f":1e+16}`},  // 指数 >= 16 用科学计数
		{map[string]any{"f": 0.0001}, `{"f":0.0001}`},
		{map[string]any{"s": "a\"b\n"}, `{"s":"a\"b\n"}`},
	}
	for _, c := range cases {
		got := string(CanonicalJSON(c.in))
		if got != c.want {
			t.Fatalf("CanonicalJSON = %s, want %s", got, c.want)
		}
	}
}

func TestSHA256KnownVector(t *testing.T) {
	// sha256("abc") 的标准向量。
	got := SHA256String("abc")
	want := "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
	if got != want {
		t.Fatalf("SHA256String(abc) = %s, want %s", got, want)
	}
}

func TestEvidenceIDFormat(t *testing.T) {
	inputsHash := InputsHash(map[string]any{"series_id": "market.global.vix", "as_of": "2026-11-25"})
	id := EvidenceID("risk_measure", "1.0.0", inputsHash)
	if !strings.HasPrefix(id, "ev_") || len(id) != 19 {
		t.Fatalf("evidence_id 格式错误: %s", id)
	}
	// 相同输入必须得到相同 evidence_id（可重算）。
	if again := EvidenceID("risk_measure", "1.0.0", inputsHash); again != id {
		t.Fatal("evidence_id 不可复现")
	}
}

func TestHashStable(t *testing.T) {
	payload := map[string]any{"value": 1.5, "unit": "点", "as_of": "2026-11-25"}
	a := Hash(payload)
	b := Hash(payload)
	if a != b || len(a) != 64 {
		t.Fatalf("evidence hash 不稳定或长度错误: %s", a)
	}
}
