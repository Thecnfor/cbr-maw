package service

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"cbr-maw/services/collector/internal/logx"
	"cbr-maw/services/collector/internal/rpc"
)

// harness 把 Service 接到一对内存管道上，走完整 JSON-RPC 路径。
type harness struct {
	t       *testing.T
	svc     *Service
	server  *rpc.Server
	out     *bytes.Buffer
	dataDir string
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	dir := t.TempDir()
	out := &bytes.Buffer{}
	logger := logx.New("collector", "error")
	svc := New(logger, "")
	srv := rpc.NewServer(bytes.NewReader(nil), out)
	svc.Register(srv)
	// 默认给一个最小台账，避免每个用例重复搭建。
	writeLedger(t, filepath.Join(dir, "data-home"), []map[string]any{{
		"id": "default", "kind": "http_json", "enabled": true,
		"series": []string{"market.global.vix"}, "params": map[string]any{"url": "http://x"},
	}})
	return &harness{t: t, svc: svc, server: srv, out: out, dataDir: dir}
}

// call 直接调用已注册的方法（绕过 stdin，但仍走 handler + 错误映射）。
func (h *harness) call(method string, params any) (any, *rpc.Error) {
	h.t.Helper()
	h.svc.mu.Lock()
	handler := h.svc.handlers(method)
	h.svc.mu.Unlock()
	raw, err := json.Marshal(params)
	if err != nil {
		h.t.Fatal(err)
	}
	result, rpcErr := handler(nil, raw)
	if rpcErr != nil || result == nil {
		return result, rpcErr
	}
	// 按真实传输口径往返一次 JSON，测试断言用 map 读取字段。
	wire, err := json.Marshal(result)
	if err != nil {
		h.t.Fatal(err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(wire, &decoded); err != nil {
		h.t.Fatal(err)
	}
	return decoded, nil
}

func (s *Service) handlers(method string) rpc.Handler {
	switch method {
	case "initialize":
		return s.handleInitialize
	case "shutdown":
		return s.handleShutdown
	case "ping":
		return s.handlePing
	case "sources.list":
		return s.handleSourcesList
	case "sources.probe":
		return s.handleSourcesProbe
	case "sources.health":
		return s.handleSourcesHealth
	case "collect.run":
		return s.handleCollectRun
	case "inbox.ingest":
		return s.handleInboxIngest
	case "events.poll":
		return s.handleEventsPoll
	}
	panic("unknown method " + method)
}

func (h *harness) init() {
	h.t.Helper()
	_, rpcErr := h.call("initialize", map[string]any{
		"contract_version": "1.0.0",
		"client_version":   "0.1.0",
		"workspace":        filepath.Join(h.dataDir, "workspace"),
		"data_home":        filepath.Join(h.dataDir, "data-home"),
		"resource_home":    filepath.Join(h.dataDir, "resource-home"),
	})
	if rpcErr != nil {
		h.t.Fatalf("initialize 失败: %+v", rpcErr)
	}
}

func writeLedger(t *testing.T, dir string, sources []map[string]any) string {
	t.Helper()
	configDir := filepath.Join(dir, "configs")
	if err := os.MkdirAll(configDir, 0o755); err != nil {
		t.Fatal(err)
	}
	ledger := map[string]any{
		"version":    1,
		"user_agent": "cbr-test/1.0",
		"defaults":   map[string]any{"timeout_seconds": 1, "retries": 0, "min_interval_seconds": 0},
		"sources":    sources,
	}
	raw, _ := json.Marshal(ledger)
	path := filepath.Join(configDir, "sources.json")
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestInitializeHandshake(t *testing.T) {
	h := newHarness(t)
	h.init()
	result, rpcErr := h.call("ping", map[string]any{})
	if rpcErr != nil {
		t.Fatalf("ping 失败: %+v", rpcErr)
	}
	m := result.(map[string]any)
	if m["pong"] != true {
		t.Fatalf("pong = %v", m["pong"])
	}
}

func TestBusinessBeforeInitialize(t *testing.T) {
	h := newHarness(t)
	_, rpcErr := h.call("sources.list", map[string]any{})
	if rpcErr == nil || rpcErr.Data.Kind != "E_NOT_INITIALIZED" {
		t.Fatalf("期望 E_NOT_INITIALIZED，实际 %+v", rpcErr)
	}
	if rpcErr.Code != -32008 {
		t.Fatalf("code = %d", rpcErr.Code)
	}
}

func TestContractMismatch(t *testing.T) {
	h := newHarness(t)
	_, rpcErr := h.call("initialize", map[string]any{
		"contract_version": "0.9.0",
		"client_version":   "0.1.0",
		"workspace":        h.dataDir,
		"data_home":        h.dataDir,
		"resource_home":    h.dataDir,
	})
	if rpcErr == nil || rpcErr.Data.Kind != "E_CONTRACT_MISMATCH" {
		t.Fatalf("期望 E_CONTRACT_MISMATCH，实际 %+v", rpcErr)
	}
	if rpcErr.Code != -32005 {
		t.Fatalf("code = %d", rpcErr.Code)
	}
}

func TestSourcesListAndProbe(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"data":{"klines":["2026-11-01,1,4000.1,4010"]}}`))
	}))
	defer srv.Close()

	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
		"id": "em_csi300", "kind": "http_json", "enabled": true,
		"series": []string{"market.cn_equity.csi300"}, "interval_seconds": 1800,
		"release_lag_days": 0, "publish_hour": 18, "publish_minute": 0, "tz_offset": "+08:00",
		"params": map[string]any{"url": srv.URL, "rows_path": "data.klines", "row_split": ",",
			"date_field": 0, "value_field": 2, "source": "eastmoney"},
	}})
	h.init()

	list, rpcErr := h.call("sources.list", map[string]any{"include_disabled": false})
	if rpcErr != nil {
		t.Fatalf("sources.list: %+v", rpcErr)
	}
	entries := list.(map[string]any)["sources"].([]any)
	if len(entries) != 1 {
		t.Fatalf("sources = %d", len(entries))
	}
	entry := entries[0].(map[string]any)
	if entry["id"] != "em_csi300" || entry["modality"] != "numeric" {
		t.Fatalf("entry = %+v", entry)
	}

	probe, rpcErr := h.call("sources.probe", map[string]any{"source_id": "em_csi300", "timeout_s": 5})
	if rpcErr != nil {
		t.Fatalf("sources.probe: %+v", rpcErr)
	}
	p := probe.(map[string]any)
	if p["state"] != "reachable" {
		t.Fatalf("state = %v, detail = %+v", p["state"], p["detail"])
	}
}

func TestProbeFiveStates(t *testing.T) {
	cases := []struct {
		status int
		want   string
	}{
		{200, "reachable"},
		{401, "need_auth"},
		{403, "need_login"},
		{429, "restricted"},
		{500, "unreachable"},
	}
	for _, c := range cases {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(c.status)
		}))
		h := newHarness(t)
		writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
			"id": "src1", "kind": "http_json", "enabled": true,
			"series": []string{"market.global.vix"}, "params": map[string]any{"url": srv.URL},
		}})
		h.init()
		res, rpcErr := h.call("sources.probe", map[string]any{"source_id": "src1"})
		srv.Close()
		if rpcErr != nil {
			t.Fatalf("status %d: %+v", c.status, rpcErr)
		}
		if got := res.(map[string]any)["state"]; got != c.want {
			t.Fatalf("status %d → state %v, want %s", c.status, got, c.want)
		}
	}
}

func TestProbeTimeoutValidation(t *testing.T) {
	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
		"id": "s", "kind": "http_json", "enabled": true,
		"series": []string{"market.global.vix"}, "params": map[string]any{"url": "http://x"},
	}})
	h.init()
	_, rpcErr := h.call("sources.probe", map[string]any{"source_id": "s", "timeout_s": 0})
	if rpcErr == nil || rpcErr.Data.Kind != "E_INVALID_PARAMS" {
		t.Fatalf("期望 E_INVALID_PARAMS，实际 %+v", rpcErr)
	}
}

// TestCollectRunAndFallback 主源失败 → 自动切备源，且备源切换可观测。
func TestCollectRunAndFallback(t *testing.T) {
	backup := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"data":{"sh000300":{"day":[["2026-11-01","1","4050.5"]]}}}`))
	}))
	defer backup.Close()

	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{
		{
			"id": "em_csi300", "kind": "http_json", "enabled": true,
			"series": []string{"market.cn_equity.csi300"},
			"params": map[string]any{"url": "http://127.0.0.1:1/unreachable"},
		},
		{
			"id": "tencent_csi300", "kind": "http_json", "enabled": true, "backup_for": "em_csi300",
			"series": []string{"market.cn_equity.csi300"},
			"params": map[string]any{"url": backup.URL, "rows_path": []any{"data", "sh000300", "day"},
				"row_split": ",", "date_field": 0, "value_field": 2, "source": "tencent"},
		},
	})
	h.init()

	res, rpcErr := h.call("collect.run", map[string]any{"source_id": "em_csi300"})
	if rpcErr != nil {
		t.Fatalf("collect.run 应回退备源成功: %+v", rpcErr)
	}
	m := res.(map[string]any)
	if m["status"] != "ok" {
		t.Fatalf("status = %v", m["status"])
	}
	if m["backup_used"] != "tencent_csi300" {
		t.Fatalf("backup_used = %v（备源切换必须可观测）", m["backup_used"])
	}
	files := m["written_files"].([]any)
	if len(files) == 0 {
		t.Fatal("未写中间文件")
	}
	ev := m["evidence"].([]any)[0].(map[string]any)
	if ev["http_status"].(float64) != 200 {
		t.Fatalf("证据缺少 HTTP 状态: %+v", ev)
	}
	if len(ev["response_sha256"].(string)) != 64 {
		t.Fatal("证据缺少响应哈希")
	}
	if m["coverage_start"] != "2026-11-01" || m["coverage_end"] != "2026-11-01" {
		t.Fatalf("覆盖期应来自真实观测行: start=%v end=%v", m["coverage_start"], m["coverage_end"])
	}
	// 中间文件真实存在且内容带 release_time。
	raw, err := os.ReadFile(files[0].(string))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(raw), "release_time") {
		t.Fatalf("NDJSON 缺少 release_time: %s", raw)
	}

	events, _ := h.call("events.poll", map[string]any{})
	evs := events.(map[string]any)["events"].([]any)
	types := map[string]bool{}
	for _, e := range evs {
		types[e.(map[string]any)["type"].(string)] = true
	}
	if !types["fallback"] {
		t.Fatalf("缺少 fallback 事件: %+v", types)
	}
}

// TestCollectDryRun 不落盘。
func TestCollectDryRun(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"data":{"klines":["2026-11-01,1,4000.1"]}}`))
	}))
	defer srv.Close()
	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
		"id": "s", "kind": "http_json", "enabled": true,
		"series": []string{"market.cn_equity.csi300"},
		"params": map[string]any{"url": srv.URL, "rows_path": "data.klines", "row_split": ",",
			"date_field": 0, "value_field": 2},
	}})
	h.init()
	res, rpcErr := h.call("collect.run", map[string]any{"source_id": "s", "dry_run": true})
	if rpcErr != nil {
		t.Fatalf("%+v", rpcErr)
	}
	m := res.(map[string]any)
	if len(m["written_files"].([]any)) != 0 {
		t.Fatal("dry_run 不应写文件")
	}
	if len(m["evidence"].([]any)) != 1 {
		t.Fatal("dry_run 仍应产出证据")
	}
}

// TestCollectRangeFilter 区间过滤。
func TestCollectRangeFilter(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"data":{"klines":["2026-10-01,1,3900","2026-11-01,1,4000","2026-12-01,1,4100"]}}`))
	}))
	defer srv.Close()
	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
		"id": "s", "kind": "http_json", "enabled": true,
		"series": []string{"market.cn_equity.csi300"},
		"params": map[string]any{"url": srv.URL, "rows_path": "data.klines", "row_split": ",",
			"date_field": 0, "value_field": 2},
	}})
	h.init()
	res, rpcErr := h.call("collect.run", map[string]any{
		"source_id": "s",
		"range":     map[string]any{"start": "2026-10-15", "end": "2026-11-15"},
	})
	if rpcErr != nil {
		t.Fatalf("%+v", rpcErr)
	}
	ev := res.(map[string]any)["evidence"].([]any)[0].(map[string]any)
	if ev["rows"].(float64) != 1 {
		t.Fatalf("rows = %v, want 1", ev["rows"])
	}
}

// TestCollectTierBlocked T3/T4 来源必须显式拒绝。
func TestCollectTierBlocked(t *testing.T) {
	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
		"id": "wind", "kind": "http_json", "enabled": true, "tier": "t3Terminal",
		"series": []string{"market.global.vix"}, "params": map[string]any{"url": "http://x"},
	}})
	h.init()
	_, rpcErr := h.call("collect.run", map[string]any{"source_id": "wind"})
	if rpcErr == nil || rpcErr.Data.Kind != "E_NOT_AUTHORIZED" {
		t.Fatalf("期望 E_NOT_AUTHORIZED，实际 %+v", rpcErr)
	}
}

// TestInboxIngestEndToEnd inbox.ingest 经服务层。
func TestInboxIngestEndToEnd(t *testing.T) {
	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
		"id": "s", "kind": "http_json", "enabled": true,
		"series": []string{"market.global.vix"}, "params": map[string]any{"url": "http://x"},
	}})
	h.init()
	inboxPath := filepath.Join(h.dataDir, "workspace", "inbox", "user.csv")
	if err := os.MkdirAll(filepath.Dir(inboxPath), 0o755); err != nil {
		t.Fatal(err)
	}
	csv := "日期,VIX\n2026-11-01,15.2\n2026-11-02,-\n"
	if err := os.WriteFile(inboxPath, []byte(csv), 0o644); err != nil {
		t.Fatal(err)
	}
	res, rpcErr := h.call("inbox.ingest", map[string]any{
		"path": inboxPath, "declared_source": "REG-01",
	})
	if rpcErr != nil {
		t.Fatalf("%+v", rpcErr)
	}
	m := res.(map[string]any)
	accepted := m["accepted"].([]any)
	if len(accepted) != 1 {
		t.Fatalf("accepted = %+v", accepted)
	}
	acc := accepted[0].(map[string]any)
	if acc["series_id"] != "market.global.vix" || acc["rows"].(float64) != 1 {
		t.Fatalf("accepted = %+v", acc)
	}
}

func TestInboxMissingFile(t *testing.T) {
	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
		"id": "s", "kind": "http_json", "enabled": true,
		"series": []string{"market.global.vix"}, "params": map[string]any{"url": "http://x"},
	}})
	h.init()
	_, rpcErr := h.call("inbox.ingest", map[string]any{"path": "/nonexistent/x.csv"})
	if rpcErr == nil || rpcErr.Data.Kind != "E_DATA_MISSING" {
		t.Fatalf("期望 E_DATA_MISSING，实际 %+v", rpcErr)
	}
	if rpcErr.Code != -32004 {
		t.Fatalf("code = %d", rpcErr.Code)
	}
}

func TestShutdown(t *testing.T) {
	h := newHarness(t)
	h.init()
	res, rpcErr := h.call("shutdown", map[string]any{})
	if rpcErr != nil {
		t.Fatalf("%+v", rpcErr)
	}
	if res.(map[string]any)["stopped"] != true {
		t.Fatal("stopped != true")
	}
	select {
	case <-h.svc.StopCh():
	default:
		t.Fatal("shutdown 后 StopCh 应关闭")
	}
}

// TestHealthStale 健康度：从未成功 → stale=true。
func TestHealthStale(t *testing.T) {
	h := newHarness(t)
	writeLedger(t, filepath.Join(h.dataDir, "data-home"), []map[string]any{{
		"id": "s", "kind": "http_json", "enabled": true,
		"series": []string{"market.global.vix"}, "params": map[string]any{"url": "http://x"},
	}})
	h.init()
	res, rpcErr := h.call("sources.health", map[string]any{})
	if rpcErr != nil {
		t.Fatalf("%+v", rpcErr)
	}
	entries := res.(map[string]any)["entries"].([]any)
	if len(entries) != 1 {
		t.Fatalf("entries = %d", len(entries))
	}
	e := entries[0].(map[string]any)
	if e["stale"] != true {
		t.Fatalf("从未成功应 stale=true: %+v", e)
	}
}

// TestLedgerFallsBackToLegacyYAML 配置缺失时回退旧 YAML。
func TestLedgerFallsBackToLegacyYAML(t *testing.T) {
	repo := t.TempDir()
	legacyDir := filepath.Join(repo, "docs", "legacy-configs")
	if err := os.MkdirAll(legacyDir, 0o755); err != nil {
		t.Fatal(err)
	}
	yaml := "sources:\n  - id: em_csi300\n    kind: http_json\n    enabled: true\n    series: [market.cn_equity.csi300]\n    params:\n      url: https://example.com\n      release_lag_days: 0\n      publish_hour: 18\n      tz_offset: \"+08:00\"\n"
	if err := os.WriteFile(filepath.Join(legacyDir, "sources.yaml"), []byte(yaml), 0o644); err != nil {
		t.Fatal(err)
	}
	h := newHarness(t)
	h.svc.repoRoot = repo
	_, rpcErr := h.call("initialize", map[string]any{
		"contract_version": "1.0.0",
		"client_version":   "0.1.0",
		"workspace":        h.dataDir,
		"data_home":        filepath.Join(h.dataDir, "data-home"),
		"resource_home":    filepath.Join(h.dataDir, "resource-home"),
	})
	if rpcErr != nil {
		t.Fatalf("回退 YAML 失败: %+v", rpcErr)
	}
	res, _ := h.call("sources.list", map[string]any{})
	if len(res.(map[string]any)["sources"].([]any)) != 1 {
		t.Fatal("YAML 台账未加载")
	}
}

var _ = fmt.Sprint
