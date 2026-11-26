package fetch

import (
	"bytes"
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

// TestRetryOn5xx 上游 5xx 时按 retries 重试。
func TestRetryOn5xx(t *testing.T) {
	var calls int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if atomic.AddInt32(&calls, 1) < 3 {
			w.WriteHeader(http.StatusInternalServerError)
			return
		}
		_, _ = w.Write([]byte("ok"))
	}))
	defer srv.Close()
	c := New("test-ua", 5*time.Second, 2, 0)
	resp, err := c.Get(context.Background(), srv.URL, nil, nil)
	if err != nil {
		t.Fatalf("应重试成功: %v", err)
	}
	if string(resp.Body) != "ok" || resp.StatusCode != 200 {
		t.Fatalf("响应错误: %+v", resp)
	}
	if atomic.LoadInt32(&calls) != 3 {
		t.Fatalf("calls = %d, want 3", calls)
	}
}

// TestRetryAfterRespected 429 带 Retry-After 时返回可观测错误。
func TestRetryAfterRespected(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Retry-After", "42")
		w.WriteHeader(http.StatusTooManyRequests)
	}))
	defer srv.Close()
	c := New("test-ua", 5*time.Second, 0, 0)
	_, err := c.Get(context.Background(), srv.URL, nil, nil)
	rate, ok := err.(*ErrRateLimited)
	if !ok {
		t.Fatalf("err = %T, want *ErrRateLimited", err)
	}
	if rate.RetryAfter != 42 {
		t.Fatalf("retry_after = %d, want 42", rate.RetryAfter)
	}
}

// TestUserAgentSent 统一 User-Agent。
func TestUserAgentSent(t *testing.T) {
	var got string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r.Header.Get("User-Agent")
		_, _ = w.Write([]byte("ok"))
	}))
	defer srv.Close()
	c := New("cbr-test/1.0", 5*time.Second, 0, 0)
	if _, err := c.Get(context.Background(), srv.URL, nil, nil); err != nil {
		t.Fatal(err)
	}
	if got != "cbr-test/1.0" {
		t.Fatalf("UA = %q", got)
	}
}

// TestUnreachable 不可达返回 ErrUnreachable。
func TestUnreachable(t *testing.T) {
	c := New("test-ua", 300*time.Millisecond, 0, 0)
	_, err := c.Get(context.Background(), "http://127.0.0.1:1/nope", nil, nil)
	if _, ok := err.(*ErrUnreachable); !ok {
		t.Fatalf("err = %T, want *ErrUnreachable", err)
	}
}

// TestMinInterval 两次请求间隔不短于 MinInterval。
func TestMinInterval(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("ok"))
	}))
	defer srv.Close()
	c := New("test-ua", 5*time.Second, 0, 120*time.Millisecond)
	start := time.Now()
	for i := 0; i < 2; i++ {
		if _, err := c.Get(context.Background(), srv.URL, nil, nil); err != nil {
			t.Fatal(err)
		}
	}
	if elapsed := time.Since(start); elapsed < 120*time.Millisecond {
		t.Fatalf("间隔不足: %v", elapsed)
	}
}

// TestProbeReadsOnlyPrefix sources.probe 只读前 4KB，不下载整份数据。
func TestProbeReadsOnlyPrefix(t *testing.T) {
	big := bytes.Repeat([]byte("x"), 1<<20)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write(big)
	}))
	defer srv.Close()
	c := New("test-ua", 5*time.Second, 0, 0)
	resp, err := c.Probe(context.Background(), srv.URL, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(resp.Body) != 4096 {
		t.Fatalf("probe body = %d bytes, want 4096", len(resp.Body))
	}
}
