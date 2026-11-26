// Package fetch 实现 HTTP 取数：统一 User-Agent、串行低频、重试退避、
// 遵守 Retry-After，并把响应归一化为观测行 / 文档行。
//
// 所有抓取都返回来源证据（HTTP 状态 / 响应哈希 / 请求 URL / 抓取时间），
// 无证据的数值不进入下游（契约 §3、§5）。
package fetch

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

// ErrRateLimited 表示被限流；RetryAfter 是服务端建议等待秒数。
type ErrRateLimited struct {
	RetryAfter int
	URL        string
}

func (e *ErrRateLimited) Error() string {
	return fmt.Sprintf("被限流（Retry-After=%ds）：%s", e.RetryAfter, e.URL)
}

// ErrUnreachable 表示网络层不可达。
type ErrUnreachable struct {
	URL string
	Err error
}

func (e *ErrUnreachable) Error() string { return fmt.Sprintf("不可达 %s: %v", e.URL, e.Err) }
func (e *ErrUnreachable) Unwrap() error { return e.Err }

// Response 是一次成功 HTTP 取数的结果。
type Response struct {
	URL        string
	StatusCode int
	Body       []byte
	FetchedAt  time.Time
	LatencyMS  int
	Header     http.Header
}

// Client 是带节流的 HTTP 取数器。
//
// 节流在 Client 级别串行：同一 Client 同一时刻只发一个请求，
// 且两次请求间隔不短于 MinInterval。
type Client struct {
	HTTP        *http.Client
	UserAgent   string
	Retries     int
	MinInterval time.Duration

	last time.Time
}

// New 构造取数器。
func New(userAgent string, timeout time.Duration, retries int, minInterval time.Duration) *Client {
	return &Client{
		HTTP:        &http.Client{Timeout: timeout},
		UserAgent:   userAgent,
		Retries:     retries,
		MinInterval: minInterval,
	}
}

// Probe 只探测连通性/认证态/频率限制：发 GET 但**只读前 4KB 即关闭**，
// 不下载整份数据（sources.probe 契约要求「不抓数据」）。
func (c *Client) Probe(ctx context.Context, rawURL string, query url.Values, headers map[string]string) (*Response, error) {
	return c.doGet(ctx, rawURL, query, headers, 4096)
}

// Get 发起一次 GET，自动重试网络错误与 5xx，并遵守 Retry-After。
func (c *Client) Get(ctx context.Context, rawURL string, query url.Values, headers map[string]string) (*Response, error) {
	return c.doGet(ctx, rawURL, query, headers, 0)
}

// doGet 是 Get/Probe 的共同实现；maxBytes>0 时只读前 maxBytes 字节。
func (c *Client) doGet(ctx context.Context, rawURL string, query url.Values, headers map[string]string, maxBytes int64) (*Response, error) {
	full := rawURL
	if len(query) > 0 {
		full = rawURL + "?" + query.Encode()
	}
	var lastErr error
	for attempt := 0; attempt <= c.Retries; attempt++ {
		c.throttle()
		start := time.Now()
		resp, err := c.do(ctx, full, headers)
		if err != nil {
			lastErr = &ErrUnreachable{URL: full, Err: err}
			if ctx.Err() != nil {
				return nil, lastErr
			}
			sleepBackoff(ctx, attempt)
			continue
		}
		var reader io.Reader = resp.Body
		if maxBytes > 0 {
			reader = io.LimitReader(resp.Body, maxBytes)
		}
		body, readErr := io.ReadAll(reader)
		resp.Body.Close()
		latency := int(time.Since(start).Milliseconds())
		if readErr != nil {
			lastErr = &ErrUnreachable{URL: full, Err: readErr}
			sleepBackoff(ctx, attempt)
			continue
		}
		if resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode == http.StatusServiceUnavailable {
			retryAfter := parseRetryAfter(resp.Header.Get("Retry-After"))
			if retryAfter <= 0 {
				retryAfter = int(time.Second.Seconds()) * (attempt + 1)
			}
			return nil, &ErrRateLimited{RetryAfter: retryAfter, URL: full}
		}
		if resp.StatusCode >= 500 {
			lastErr = fmt.Errorf("上游 %d：%s", resp.StatusCode, full)
			sleepBackoff(ctx, attempt)
			continue
		}
		return &Response{
			URL:        full,
			StatusCode: resp.StatusCode,
			Body:       body,
			FetchedAt:  time.Now(),
			LatencyMS:  latency,
			Header:     resp.Header,
		}, nil
	}
	if lastErr == nil {
		lastErr = errors.New("未知网络错误")
	}
	return nil, lastErr
}

func (c *Client) do(ctx context.Context, full string, headers map[string]string) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, full, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("User-Agent", c.UserAgent)
	req.Header.Set("Accept", "*/*")
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	return c.HTTP.Do(req)
}

func (c *Client) throttle() {
	if c.MinInterval <= 0 {
		return
	}
	if !c.last.IsZero() {
		if wait := c.MinInterval - time.Since(c.last); wait > 0 {
			time.Sleep(wait)
		}
	}
	c.last = time.Now()
}

func sleepBackoff(ctx context.Context, attempt int) {
	delay := time.Duration(attempt+1) * time.Second
	select {
	case <-time.After(delay):
	case <-ctx.Done():
	}
}

func parseRetryAfter(raw string) int {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return 0
	}
	if secs, err := strconv.Atoi(raw); err == nil {
		return secs
	}
	if ts, err := http.ParseTime(raw); err == nil {
		if d := time.Until(ts); d > 0 {
			return int(d.Seconds())
		}
	}
	return 0
}
