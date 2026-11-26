// Package service 实现 collector 的全部 JSON-RPC 方法。
//
// 方法归属（contracts/README.md §3）：sources.list / sources.probe /
// sources.health / collect.run / inbox.ingest / events.poll + initialize /
// shutdown / ping。
package service

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"sort"
	"sync"
	"time"

	"cbr-maw/services/collector/internal/evidence"
	"cbr-maw/services/collector/internal/fetch"
	"cbr-maw/services/collector/internal/inbox"
	"cbr-maw/services/collector/internal/logx"
	"cbr-maw/services/collector/internal/output"
	"cbr-maw/services/collector/internal/parse"
	"cbr-maw/services/collector/internal/pit"
	"cbr-maw/services/collector/internal/rpc"
	"cbr-maw/services/collector/internal/series"
	"cbr-maw/services/collector/internal/sources"
)

// Version 是 collector sidecar 版本（构建期可由 -ldflags 注入）。
var Version = "0.1.0"

// ContractVersion 是实现的契约版本。
const ContractVersion = "1.0.0"

// SchemaVersion 是本实现的 schema 版本。
const SchemaVersion = 3

// 能力清单。
var capabilities = []string{
	"sources.list", "sources.probe", "sources.health",
	"collect.run", "inbox.ingest", "events.poll",
	"initialize", "shutdown", "ping",
}

// Service 是 collector 的运行时状态与业务实现。
type Service struct {
	logger *logx.Logger

	mu       sync.Mutex
	ready    bool
	stopping bool

	workspace    string
	dataHome     string
	resourceHome string
	repoRoot     string

	ledger *sources.Ledger
	client *fetch.Client

	// 运行期健康状态，按 source_id 索引。
	health map[string]*sourceHealth
	// 事件环形缓冲（v1 轮询）。
	events []Event
	// 当前任务进度。
	jobs map[string]*jobState

	stopCh chan struct{}
}

type sourceHealth struct {
	LastSuccessAt *string `json:"last_success_at"`
	CoverageStart *string `json:"coverage_start"`
	CoverageEnd   *string `json:"coverage_end"`
	FailureReason *string `json:"failure_reason"`
	State         string  `json:"state"`
}

type jobState struct {
	ID       string
	SourceID string
	Total    int
	Written  int
}

// Event 是 events.poll 的事件项（契约 CollectEvent）。
type Event struct {
	TS      string         `json:"ts"`
	Type    string         `json:"type"`
	JobID   string         `json:"job_id"`
	Payload map[string]any `json:"payload"`
}

// New 构造 Service。
func New(logger *logx.Logger, repoRoot string) *Service {
	return &Service{
		logger:   logger,
		repoRoot: repoRoot,
		health:   map[string]*sourceHealth{},
		jobs:     map[string]*jobState{},
		stopCh:   make(chan struct{}),
	}
}

// Register 把全部方法注册到 RPC server。
func (s *Service) Register(srv *rpc.Server) {
	srv.Register("initialize", s.handleInitialize)
	srv.Register("shutdown", s.handleShutdown)
	srv.Register("ping", s.handlePing)
	srv.Register("sources.list", s.handleSourcesList)
	srv.Register("sources.probe", s.handleSourcesProbe)
	srv.Register("sources.health", s.handleSourcesHealth)
	srv.Register("collect.run", s.handleCollectRun)
	srv.Register("inbox.ingest", s.handleInboxIngest)
	srv.Register("events.poll", s.handleEventsPoll)
}

// StopCh 供 main 在 shutdown 后退出。
func (s *Service) StopCh() <-chan struct{} { return s.stopCh }

// ---------------------------------------------------------------------------
// 生命周期
// ---------------------------------------------------------------------------

type initializeParams struct {
	ContractVersion string   `json:"contract_version"`
	ClientVersion   string   `json:"client_version"`
	Workspace       string   `json:"workspace"`
	DataHome        string   `json:"data_home"`
	ResourceHome    string   `json:"resource_home"`
	Capabilities    []string `json:"capabilities"`
}

func (s *Service) handleInitialize(_ *string, raw json.RawMessage) (any, *rpc.Error) {
	var p initializeParams
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, rpc.ErrInvalidParams("initialize 参数解析失败", "")
	}
	for name, value := range map[string]string{
		"contract_version": p.ContractVersion,
		"client_version":   p.ClientVersion,
		"workspace":        p.Workspace,
		"data_home":        p.DataHome,
		"resource_home":    p.ResourceHome,
	} {
		if value == "" {
			return nil, rpc.ErrInvalidParams("缺少必填字段 "+name, name)
		}
	}
	if p.ContractVersion != ContractVersion {
		return nil, rpc.NewError(rpc.CodeContractMismatch, "契约版本不匹配", "E_CONTRACT_MISMATCH", false, map[string]any{
			"reason":   fmt.Sprintf("客户端契约版本 %s 与 sidecar %s 不匹配", p.ContractVersion, ContractVersion),
			"expected": ContractVersion,
			"actual":   p.ContractVersion,
		})
	}
	s.mu.Lock()
	s.workspace = p.Workspace
	s.dataHome = p.DataHome
	s.resourceHome = p.ResourceHome
	s.mu.Unlock()

	ledger, err := sources.Load(p.DataHome, p.ResourceHome, s.repoRoot)
	if err != nil {
		return nil, rpc.NewError(rpc.CodeInternal, "来源台账加载失败", "E_INTERNAL", false, map[string]any{
			"reason": err.Error(),
		})
	}
	s.mu.Lock()
	s.ledger = ledger
	s.client = fetch.New(ledger.UserAgent,
		time.Duration(ledger.Defaults.TimeoutSeconds)*time.Second,
		ledger.Defaults.Retries,
		time.Duration(ledger.Defaults.MinIntervalSeconds)*time.Second)
	s.ready = true
	s.mu.Unlock()

	s.loadHealth()
	s.logger.Info("initialize 完成", map[string]any{
		"contract_version": ContractVersion,
		"ledger":           ledger.LoadedFrom,
		"sources":          len(ledger.Sources),
		"warnings":         ledger.Warnings,
	})
	return map[string]any{
		"sidecar":          "collector",
		"version":          Version,
		"contract_version": ContractVersion,
		"schema_version":   SchemaVersion,
		"capabilities":     capabilities,
	}, nil
}

func (s *Service) handleShutdown(_ *string, _ json.RawMessage) (any, *rpc.Error) {
	s.mu.Lock()
	s.stopping = true
	s.mu.Unlock()
	s.persistHealth()
	select {
	case <-s.stopCh:
	default:
		close(s.stopCh)
	}
	s.logger.Info("shutdown 已受理", nil)
	return map[string]any{"stopped": true}, nil
}

func (s *Service) handlePing(_ *string, _ json.RawMessage) (any, *rpc.Error) {
	return map[string]any{
		"pong":        true,
		"server_time": time.Now().Format(time.RFC3339),
	}, nil
}

// requireReady 校验握手状态。
func (s *Service) requireReady() *rpc.Error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if !s.ready {
		return rpc.NewError(rpc.CodeNotInitialized, "未握手", "E_NOT_INITIALIZED", false, map[string]any{
			"reason": "收到业务方法前必须先完成 initialize 握手",
		})
	}
	return nil
}

// ---------------------------------------------------------------------------
// sources.list / sources.probe / sources.health
// ---------------------------------------------------------------------------

type sourcesListParams struct {
	IncludeDisabled *bool `json:"include_disabled"`
}

func (s *Service) handleSourcesList(_ *string, raw json.RawMessage) (any, *rpc.Error) {
	if err := s.requireReady(); err != nil {
		return nil, err
	}
	var p sourcesListParams
	if len(raw) > 0 && string(raw) != "null" {
		if err := json.Unmarshal(raw, &p); err != nil {
			return nil, rpc.ErrInvalidParams("sources.list 参数解析失败", "")
		}
	}
	include := false
	if p.IncludeDisabled != nil {
		include = *p.IncludeDisabled
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	entries := s.ledger.List(include)
	for i := range entries {
		if h, ok := s.health[entries[i].ID]; ok {
			entries[i].Reachability = h.State
			entries[i].LastSuccessAt = h.LastSuccessAt
			entries[i].LastError = h.FailureReason
		} else {
			// 从未探测：如实标为 toVerify，而不是谎报 reachable/unreachable。
			entries[i].Reachability = "toVerify"
		}
	}
	return map[string]any{"sources": entries}, nil
}

type probeParams struct {
	SourceID string `json:"source_id"`
	TimeoutS *int   `json:"timeout_s"`
}

// ProbeResult 是 sources.probe 响应体。
type ProbeResult struct {
	SourceID string `json:"source_id"`
	State    string `json:"state"`
	Detail   struct {
		Reason     string `json:"reason"`
		CheckedAt  string `json:"checked_at"`
		HTTPStatus *int   `json:"http_status"`
		LatencyMS  *int   `json:"latency_ms"`
	} `json:"detail"`
}

func (s *Service) handleSourcesProbe(_ *string, raw json.RawMessage) (any, *rpc.Error) {
	if err := s.requireReady(); err != nil {
		return nil, err
	}
	var p probeParams
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, rpc.ErrInvalidParams("sources.probe 参数解析失败", "")
	}
	if p.SourceID == "" {
		return nil, rpc.ErrInvalidParams("缺少 source_id", "source_id")
	}
	if p.TimeoutS != nil && (*p.TimeoutS < 1 || *p.TimeoutS > 300) {
		return nil, rpc.ErrInvalidParams("timeout_s 必须在 1..300 之间", "timeout_s")
	}
	s.mu.Lock()
	src, ok := s.ledger.Get(p.SourceID)
	client := s.client
	defaults := s.ledger.Defaults
	s.mu.Unlock()
	if !ok {
		return nil, rpc.ErrInvalidParams("未知来源 "+p.SourceID, "source_id")
	}
	timeout := defaults.TimeoutSeconds
	if p.TimeoutS != nil {
		timeout = *p.TimeoutS
	}
	result := s.probe(src, time.Duration(timeout)*time.Second, client)
	s.recordProbe(p.SourceID, result)
	return result, nil
}

// probe 只探测连通性/认证态/反爬/频率限制，不解析也不落盘数据。
func (s *Service) probe(src *sources.Source, timeout time.Duration, client *fetch.Client) ProbeResult {
	checkedAt := time.Now().Format(time.RFC3339)
	result := ProbeResult{SourceID: src.ID, State: string(sources.StateUnreachable)}
	result.Detail.CheckedAt = checkedAt

	if !src.Enabled || src.Tier == "t4NotAllowed" {
		result.State = string(sources.StateRestricted)
		result.Detail.Reason = "来源未启用或属于不可自动抓取档（t4NotAllowed）"
		return result
	}
	rawURL, _ := src.Params["url"].(string)
	if rawURL == "" {
		result.State = string(sources.StateUnreachable)
		result.Detail.Reason = "来源未配置 URL"
		return result
	}
	query := buildQuery(src.Params)
	headers := buildHeaders(src.Params)
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	// 探测用独立短超时客户端，避免复用长超时。
	probeClient := *client
	probeClient.HTTP = &http.Client{Timeout: timeout}
	start := time.Now()
	resp, err := probeClient.Probe(ctx, rawURL, query, headers)
	latency := int(time.Since(start).Milliseconds())
	result.Detail.LatencyMS = &latency
	if err != nil {
		var rate *fetch.ErrRateLimited
		if asRateLimited(err, &rate) {
			result.State = string(sources.StateRestricted)
			result.Detail.Reason = fmt.Sprintf("被限流：建议 %d 秒后重试", rate.RetryAfter)
			return result
		}
		result.State = string(sources.StateUnreachable)
		result.Detail.Reason = "网络不可达：" + truncate(err.Error(), 160)
		return result
	}
	status := resp.StatusCode
	result.Detail.HTTPStatus = &status
	switch {
	case status >= 200 && status < 300:
		result.State = string(sources.StateReachable)
		result.Detail.Reason = "端点可访问"
	case status == 401:
		result.State = string(sources.StateNeedAuth)
		result.Detail.Reason = "端点返回 401，需配置凭证"
	case status == 403:
		result.State = string(sources.StateNeedLogin)
		result.Detail.Reason = "端点返回 403，疑似需要登录态或反爬拦截"
	case status == 429:
		result.State = string(sources.StateRestricted)
		result.Detail.Reason = "端点返回 429，触发频率限制"
	case status == 451:
		result.State = string(sources.StateRestricted)
		result.Detail.Reason = "端点返回 451，内容因政策不可达"
	case status >= 300 && status < 400:
		result.State = string(sources.StateNeedLogin)
		result.Detail.Reason = fmt.Sprintf("端点返回 %d 跳转，疑似跳转登录页", status)
	default:
		result.State = string(sources.StateUnreachable)
		result.Detail.Reason = fmt.Sprintf("端点返回异常状态 %d", status)
	}
	return result
}

func asRateLimited(err error, out **fetch.ErrRateLimited) bool {
	if e, ok := err.(*fetch.ErrRateLimited); ok {
		*out = e
		return true
	}
	return false
}

type healthEntry struct {
	SourceID      string  `json:"source_id"`
	LastSuccessAt *string `json:"last_success_at"`
	Stale         bool    `json:"stale"`
	CoverageStart *string `json:"coverage_start"`
	CoverageEnd   *string `json:"coverage_end"`
	FailureReason *string `json:"failure_reason"`
	State         string  `json:"state"`
	// 数据新鲜度（docs/23 §4.5 强制要求）：按最新可用观测日判定，不是抓取时刻。
	Freshness    string                `json:"freshness"`
	Dependencies []dependencyFreshness `json:"dependencies"`
}

func (s *Service) handleSourcesHealth(_ *string, _ json.RawMessage) (any, *rpc.Error) {
	if err := s.requireReady(); err != nil {
		return nil, err
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	now := time.Now()
	p := scanPanel(intermediateDir(s.dataHome))
	entries := make([]healthEntry, 0, len(s.ledger.Sources))
	for i := range s.ledger.Sources {
		src := &s.ledger.Sources[i]
		h, ok := s.health[src.ID]
		if !ok {
			reason := "尚未探测/抓取"
			h = &sourceHealth{State: string(sources.StateUnreachable), FailureReason: &reason}
		}
		threshold := s.ledger.Defaults.StaleThresholdDays
		if srcIsMonthly(src) {
			threshold = s.ledger.Defaults.MonthlyStaleThresholdDays
		}
		stale := true
		if h.LastSuccessAt != nil {
			if ts, err := time.Parse(time.RFC3339, *h.LastSuccessAt); err == nil {
				stale = now.Sub(ts) > time.Duration(threshold)*24*time.Hour
			}
		}
		deps := dependenciesFor(src, p, now)
		freshness := ""
		for _, dep := range deps {
			if freshness == "" {
				freshness = dep.Freshness
				continue
			}
			freshness = worstFreshness(freshness, dep.Freshness)
		}
		if freshness == "" {
			// 文本类来源（RSS/语料）没有数值依赖序列，新鲜度由 last_success_at 的 stale 表达。
			freshness = freshnessUnknown
		}
		entries = append(entries, healthEntry{
			SourceID:      src.ID,
			LastSuccessAt: h.LastSuccessAt,
			Stale:         stale,
			CoverageStart: h.CoverageStart,
			CoverageEnd:   h.CoverageEnd,
			FailureReason: h.FailureReason,
			State:         h.State,
			Freshness:     freshness,
			Dependencies:  deps,
		})
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].SourceID < entries[j].SourceID })
	return map[string]any{"entries": entries}, nil
}

func srcIsMonthly(src *sources.Source) bool {
	for _, sid := range src.Series {
		if series.IsMonthly(sid) {
			return true
		}
	}
	return false
}

func (s *Service) recordProbe(sourceID string, result ProbeResult) {
	s.mu.Lock()
	defer s.mu.Unlock()
	h, ok := s.health[sourceID]
	if !ok {
		h = &sourceHealth{}
		s.health[sourceID] = h
	}
	h.State = result.State
	if result.State != string(sources.StateReachable) {
		reason := result.Detail.Reason
		h.FailureReason = &reason
	} else {
		h.FailureReason = nil
	}
	s.persistHealthLocked()
}

// ---------------------------------------------------------------------------
// collect.run
// ---------------------------------------------------------------------------

type collectParams struct {
	SourceID string        `json:"source_id"`
	Range    *collectRange `json:"range"`
	DryRun   *bool         `json:"dry_run"`
}

type collectRange struct {
	Start *string `json:"start"`
	End   *string `json:"end"`
}

// CollectResult 是 collect.run 响应体。
type CollectResult struct {
	JobID        string            `json:"job_id"`
	Status       string            `json:"status"`
	WrittenFiles []string          `json:"written_files"`
	Evidence     []collectEvidence `json:"evidence"`
	BackupUsed   *string           `json:"backup_used,omitempty"`
	Reason       *string           `json:"reason,omitempty"`
	// CoverageStart/End 来自本次真实观测行（不是抓取时刻）。
	CoverageStart *string `json:"coverage_start,omitempty"`
	CoverageEnd   *string `json:"coverage_end,omitempty"`
}

type collectEvidence struct {
	EvidenceID      string  `json:"evidence_id"`
	SourceID        string  `json:"source_id"`
	SeriesID        string  `json:"series_id"`
	Rows            int     `json:"rows"`
	ReleaseTimeRule string  `json:"release_time_rule"`
	File            *string `json:"file"`
	HTTPStatus      *int    `json:"http_status,omitempty"`
	ResponseSHA256  string  `json:"response_sha256,omitempty"`
	RequestURL      string  `json:"request_url,omitempty"`
	FetchedAt       string  `json:"fetched_at,omitempty"`
}

func (s *Service) handleCollectRun(_ *string, raw json.RawMessage) (any, *rpc.Error) {
	if err := s.requireReady(); err != nil {
		return nil, err
	}
	var p collectParams
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, rpc.ErrInvalidParams("collect.run 参数解析失败", "")
	}
	if p.SourceID == "" {
		return nil, rpc.ErrInvalidParams("缺少 source_id", "source_id")
	}
	s.mu.Lock()
	src, ok := s.ledger.Get(p.SourceID)
	ledger := s.ledger
	dataHome := s.dataHome
	s.mu.Unlock()
	if !ok {
		return nil, rpc.ErrInvalidParams("未知来源 "+p.SourceID, "source_id")
	}
	if !src.Enabled {
		return nil, rpc.NewError(rpc.CodeSourceUnavailable, "来源不可用", "E_SOURCE_UNAVAILABLE", false, map[string]any{
			"reason": "来源已停用（enabled=false）", "source_id": src.ID,
		})
	}
	if src.Tier == "t4NotAllowed" || src.Tier == "t3Terminal" {
		return nil, rpc.NewError(rpc.CodeNotAuthorized, "来源需授权", "E_NOT_AUTHORIZED", false, map[string]any{
			"reason": "该来源为 " + src.Tier + " 档，需用户先在设置页配置凭证或改用公开源", "source_id": src.ID,
		})
	}

	start, end := parseRange(p.Range)
	dryRun := p.DryRun != nil && *p.DryRun
	jobID := "job_" + time.Now().Format("20060102_150405")

	s.mu.Lock()
	s.jobs[jobID] = &jobState{ID: jobID, SourceID: src.ID}
	s.mu.Unlock()
	s.emit(jobID, "started", map[string]any{"source_id": src.ID, "dry_run": dryRun})

	attempts := append([]*sources.Source{src}, ledger.Backups(src.ID)...)
	var lastErr error
	var lastRPC *rpc.Error
	for i, attempt := range attempts {
		result, err := s.collectOne(attempt, start, end, dryRun, jobID, dataHome)
		if err == nil {
			if i > 0 {
				result.BackupUsed = &attempt.ID
				s.emit(jobID, "fallback", map[string]any{
					"primary": src.ID, "backup": attempt.ID, "reason": truncate(errText(lastErr), 160),
				})
				s.logger.Warn("主源失败已切备源", map[string]any{"primary": src.ID, "backup": attempt.ID})
			}
			s.emit(jobID, "succeeded", map[string]any{
				"rows": totalRows(result.Evidence), "written_files": result.WrittenFiles,
			})
			s.markCollectSuccess(attempt.ID, result)
			return result, nil
		}
		lastErr = err
		lastRPC = toRPCError(err, attempt.ID)
		if i+1 < len(attempts) {
			s.emit(jobID, "progress", map[string]any{
				"source_id": attempt.ID, "status": "failed", "reason": truncate(errText(err), 160),
			})
		}
	}
	s.emit(jobID, "failed", map[string]any{"source_id": src.ID, "reason": truncate(errText(lastErr), 160)})
	s.markCollectFailure(src.ID, lastRPC)
	return nil, lastRPC
}

// collectOne 抓取单个来源并落中间文件。
func (s *Service) collectOne(src *sources.Source, start, end *time.Time, dryRun bool, jobID, dataHome string) (*CollectResult, error) {
	rawURL, _ := src.Params["url"].(string)
	if rawURL == "" {
		return nil, fmt.Errorf("来源 %s 未配置 URL", src.ID)
	}
	query := buildQuery(src.Params)
	headers := buildHeaders(src.Params)
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	resp, err := s.client.Get(ctx, rawURL, query, headers)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode == 401 || resp.StatusCode == 403 {
		return nil, &authError{status: resp.StatusCode, sourceID: src.ID}
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("上游返回 %d", resp.StatusCode)
	}
	cfg := parseConfig(src)
	seriesIDs := canonicalSeriesIDs(src.Series)
	if src.Documents || src.Kind == "rss" {
		return s.writeRSS(src, resp, seriesIDs, dryRun, jobID, dataHome)
	}
	var rows []parse.RawRow
	switch src.Kind {
	case "http_json":
		rows, err = parse.ParseJSONRows(resp.Body, cfg)
	case "http_csv":
		rows, err = parse.ParseCSVRows(resp.Body, cfg)
	default:
		err = fmt.Errorf("来源 %s 的 kind 不受支持: %s", src.ID, src.Kind)
	}
	if err != nil {
		return nil, err
	}
	if len(seriesIDs) == 0 {
		return nil, fmt.Errorf("来源 %s 未声明 series", src.ID)
	}
	evidenceID := evidence.EvidenceID("collect.run", Version, evidence.SHA256String(src.ID+"|"+jobID))
	responseHash := evidence.SHA256Hex(resp.Body)

	result := &CollectResult{JobID: jobID, Status: "ok", WrittenFiles: []string{}, Evidence: []collectEvidence{}}
	for _, sid := range seriesIDs {
		rule := pit.RuleFromParams(sid, src.ReleaseLagDays, src.PublishHour, src.PublishMinute, src.TZOffset)
		obs, dropped := parse.Normalize(rows, sid, series.Unit(sid), sourceNameOf(src), evidenceID, cfg.DateFormat, cfg.ValueScale, rule.ReleaseTime, rule.Describe())
		obs = filterRange(obs, start, end)
		if len(obs) == 0 {
			continue
		}
		var written *string
		if !dryRun {
			path, err := output.WriteNDJSON(intermediateDir(dataHome), sid+".ndjson", toAny(obs))
			if err != nil {
				return nil, err
			}
			written = &path
			result.WrittenFiles = append(result.WrittenFiles, path)
		}
		trackCoverage(obs, &result.CoverageStart, &result.CoverageEnd)
		status := resp.StatusCode
		result.Evidence = append(result.Evidence, collectEvidence{
			EvidenceID:      evidenceID,
			SourceID:        src.ID,
			SeriesID:        sid,
			Rows:            len(obs),
			ReleaseTimeRule: rule.Describe(),
			File:            written,
			HTTPStatus:      &status,
			ResponseSHA256:  responseHash,
			RequestURL:      resp.URL,
			FetchedAt:       resp.FetchedAt.Format(time.RFC3339),
		})
		s.logger.Info("抓取完成", map[string]any{
			"source_id": src.ID, "series_id": sid, "rows": len(obs), "dropped": dropped,
			"http_status": status, "response_sha256": responseHash,
		})
	}
	if len(result.Evidence) == 0 {
		result.Status = "skipped"
		reason := "区间内无可用观测（缺失 ≠ 零值，未做填充）"
		result.Reason = &reason
	}
	return result, nil
}

// trackCoverage 用真实观测日期维护覆盖期（min/max）。
func trackCoverage(obs []parse.Observation, start, end **string) {
	for _, o := range obs {
		if *start == nil || o.ObsDate < **start {
			v := o.ObsDate
			*start = &v
		}
		if *end == nil || o.ObsDate > **end {
			v := o.ObsDate
			*end = &v
		}
	}
}

func (s *Service) writeRSS(src *sources.Source, resp *fetch.Response, seriesIDs []string, dryRun bool, jobID, dataHome string) (*CollectResult, error) {
	cfg := parseConfig(src)
	docs, err := parse.ParseRSS(resp.Body, sourceNameOf(src), cfg.Limit)
	if err != nil {
		return nil, err
	}
	evidenceID := evidence.EvidenceID("collect.run", Version, evidence.SHA256String(src.ID+"|"+jobID))
	for i := range docs {
		docs[i].EvidenceID = evidenceID
	}
	result := &CollectResult{JobID: jobID, Status: "ok", WrittenFiles: []string{}, Evidence: []collectEvidence{}}
	if len(docs) == 0 {
		result.Status = "skipped"
		reason := "RSS 无条目"
		result.Reason = &reason
		return result, nil
	}
	if !dryRun {
		path, err := output.WriteNDJSON(intermediateDir(dataHome), src.ID+".documents.ndjson", toAny(docs))
		if err != nil {
			return nil, err
		}
		result.WrittenFiles = append(result.WrittenFiles, path)
	}
	status := resp.StatusCode
	result.Evidence = append(result.Evidence, collectEvidence{
		EvidenceID:      evidenceID,
		SourceID:        src.ID,
		SeriesID:        "documents." + src.ID,
		Rows:            len(docs),
		ReleaseTimeRule: "publish_time 取自 RSS 条目发布时间",
		File:            firstOrNil(result.WrittenFiles),
		HTTPStatus:      &status,
		ResponseSHA256:  evidence.SHA256Hex(resp.Body),
		RequestURL:      resp.URL,
		FetchedAt:       resp.FetchedAt.Format(time.RFC3339),
	})
	return result, nil
}

type authError struct {
	status   int
	sourceID string
}

func (e *authError) Error() string {
	return fmt.Sprintf("来源 %s 返回 %d，需授权或登录", e.sourceID, e.status)
}

func toRPCError(err error, sourceID string) *rpc.Error {
	if err == nil {
		return nil
	}
	if ae, ok := err.(*authError); ok {
		return rpc.NewError(rpc.CodeNotAuthorized, "来源需授权", "E_NOT_AUTHORIZED", false, map[string]any{
			"reason":    "端点返回 " + fmt.Sprint(ae.status) + "，需在设置页配置凭证或登录后重试",
			"source_id": ae.sourceID,
		})
	}
	if rate, ok := err.(*fetch.ErrRateLimited); ok {
		return rpc.NewError(rpc.CodeRateLimited, "被限流", "E_RATE_LIMITED", true, map[string]any{
			"reason": "上游限流，建议稍后重试", "source_id": sourceID, "retry_after_seconds": rate.RetryAfter,
		})
	}
	var unreachable *fetch.ErrUnreachable
	if ok := asUnreachable(err, &unreachable); ok {
		return rpc.NewError(rpc.CodeSourceUnavailable, "来源不可达", "E_SOURCE_UNAVAILABLE", true, map[string]any{
			"reason": truncate(unreachable.Error(), 200), "source_id": sourceID,
		})
	}
	return rpc.NewError(rpc.CodeSourceUnavailable, "来源不可用", "E_SOURCE_UNAVAILABLE", true, map[string]any{
		"reason": truncate(err.Error(), 200), "source_id": sourceID,
	})
}

func asUnreachable(err error, out **fetch.ErrUnreachable) bool {
	for err != nil {
		if e, ok := err.(*fetch.ErrUnreachable); ok {
			*out = e
			return true
		}
		type unwrapper interface{ Unwrap() error }
		if u, ok := err.(unwrapper); ok {
			err = u.Unwrap()
			continue
		}
		return false
	}
	return false
}

func (s *Service) markCollectSuccess(sourceID string, result *CollectResult) {
	s.mu.Lock()
	defer s.mu.Unlock()
	h, ok := s.health[sourceID]
	if !ok {
		h = &sourceHealth{}
		s.health[sourceID] = h
	}
	now := time.Now().Format(time.RFC3339)
	h.LastSuccessAt = &now
	h.State = string(sources.StateReachable)
	h.FailureReason = nil
	if result != nil {
		start, end := coverageOf(result)
		if start != nil {
			h.CoverageStart = start
		}
		if end != nil {
			h.CoverageEnd = end
		}
	}
	s.persistHealthLocked()
}

func (s *Service) markCollectFailure(sourceID string, rpcErr *rpc.Error) {
	if rpcErr == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	h, ok := s.health[sourceID]
	if !ok {
		h = &sourceHealth{}
		s.health[sourceID] = h
	}
	reason := rpcErr.Message
	if rpcErr.Data != nil {
		if r, ok := rpcErr.Data.Detail["reason"].(string); ok && r != "" {
			reason = r
		}
		h.State = mapKindToState(rpcErr.Data.Kind)
	}
	h.FailureReason = &reason
	s.persistHealthLocked()
}

func mapKindToState(kind string) string {
	switch kind {
	case "E_NOT_AUTHORIZED":
		return string(sources.StateNeedAuth)
	case "E_RATE_LIMITED":
		return string(sources.StateRestricted)
	default:
		return string(sources.StateUnreachable)
	}
}

func coverageOf(result *CollectResult) (*string, *string) {
	if result == nil {
		return nil, nil
	}
	return result.CoverageStart, result.CoverageEnd
}

// ---------------------------------------------------------------------------
// inbox.ingest
// ---------------------------------------------------------------------------

type inboxParams struct {
	Path           string  `json:"path"`
	DeclaredSource *string `json:"declared_source"`
	AsOf           *string `json:"as_of"`
}

func (s *Service) handleInboxIngest(_ *string, raw json.RawMessage) (any, *rpc.Error) {
	if err := s.requireReady(); err != nil {
		return nil, err
	}
	var p inboxParams
	if err := json.Unmarshal(raw, &p); err != nil {
		return nil, rpc.ErrInvalidParams("inbox.ingest 参数解析失败", "")
	}
	if p.Path == "" {
		return nil, rpc.ErrInvalidParams("缺少 path", "path")
	}
	if p.AsOf != nil && *p.AsOf != "" {
		if _, err := time.Parse(time.RFC3339, *p.AsOf); err != nil {
			if _, err := time.Parse("2006-01-02", *p.AsOf); err != nil {
				return nil, rpc.ErrInvalidParams("as_of 必须是 ISO 8601 或 YYYY-MM-DD", "as_of")
			}
		}
	}
	s.mu.Lock()
	dataHome := s.dataHome
	workspace := s.workspace
	s.mu.Unlock()

	declared := ""
	if p.DeclaredSource != nil {
		declared = *p.DeclaredSource
	}
	opts := inbox.Options{
		DeclaredSource:  declared,
		IntermediateDir: intermediateDir(dataHome),
		RejectedDir:     filepath.Join(inboxDir(workspace, dataHome), "rejected"),
		Now:             time.Now(),
	}
	if p.AsOf != nil {
		opts.AsOf = *p.AsOf
	}
	result, err := inbox.Ingest(p.Path, opts)
	if err != nil {
		if missing, ok := err.(*inbox.MissingError); ok {
			return nil, rpc.NewError(rpc.CodeDataMissing, "必需数据缺失", "E_DATA_MISSING", false, map[string]any{
				"reason": missing.Error(),
			})
		}
		return nil, rpc.NewError(rpc.CodeInternal, "投喂箱处理失败", "E_INTERNAL", false, map[string]any{
			"reason": err.Error(),
		})
	}
	s.logger.Info("投喂箱处理完成", map[string]any{
		"batch_id": result.BatchID, "accepted": len(result.Accepted), "rejected": len(result.Rejected),
	})
	return result, nil
}

// ---------------------------------------------------------------------------
// events.poll
// ---------------------------------------------------------------------------

type eventsParams struct {
	JobID *string `json:"job_id"`
}

func (s *Service) handleEventsPoll(_ *string, raw json.RawMessage) (any, *rpc.Error) {
	if err := s.requireReady(); err != nil {
		return nil, err
	}
	var p eventsParams
	if len(raw) > 0 && string(raw) != "null" {
		if err := json.Unmarshal(raw, &p); err != nil {
			return nil, rpc.ErrInvalidParams("events.poll 参数解析失败", "")
		}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	out := make([]Event, 0, len(s.events))
	for _, ev := range s.events {
		if p.JobID != nil && *p.JobID != "" && ev.JobID != *p.JobID {
			continue
		}
		out = append(out, ev)
	}
	return map[string]any{"events": out}, nil
}

func (s *Service) emit(jobID, eventType string, payload map[string]any) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.events = append(s.events, Event{
		TS:      time.Now().Format(time.RFC3339),
		Type:    eventType,
		JobID:   jobID,
		Payload: payload,
	})
	if len(s.events) > 500 {
		s.events = s.events[len(s.events)-500:]
	}
	if job, ok := s.jobs[jobID]; ok && eventType == "succeeded" {
		if rows, ok := payload["rows"].(int); ok {
			job.Written = rows
		}
	}
}

// ---------------------------------------------------------------------------
// 健康状态持久化
// ---------------------------------------------------------------------------

func (s *Service) healthPath() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.healthPathLocked()
}

func (s *Service) healthPathLocked() string {
	if s.dataHome == "" {
		return ""
	}
	return filepath.Join(s.dataHome, "state", "collector_health.json")
}

func (s *Service) loadHealth() {
	path := s.healthPath()
	if path == "" {
		return
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		return
	}
	var stored map[string]*sourceHealth
	if err := json.Unmarshal(raw, &stored); err != nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	for k, v := range stored {
		s.health[k] = v
	}
}

func (s *Service) persistHealth() {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.persistHealthLocked()
}

func (s *Service) persistHealthLocked() {
	path := s.healthPathLocked()
	if path == "" {
		return
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return
	}
	raw, err := json.MarshalIndent(s.health, "", "  ")
	if err != nil {
		return
	}
	_ = os.WriteFile(path, raw, 0o644)
}

// ---------------------------------------------------------------------------
// 辅助
// ---------------------------------------------------------------------------

func parseRange(r *collectRange) (*time.Time, *time.Time) {
	if r == nil {
		return nil, nil
	}
	var start, end *time.Time
	if r.Start != nil && *r.Start != "" {
		if t, err := time.Parse("2006-01-02", *r.Start); err == nil {
			start = &t
		}
	}
	if r.End != nil && *r.End != "" {
		if t, err := time.Parse("2006-01-02", *r.End); err == nil {
			end = &t
		}
	}
	return start, end
}

func filterRange(obs []parse.Observation, start, end *time.Time) []parse.Observation {
	if start == nil && end == nil {
		return obs
	}
	out := make([]parse.Observation, 0, len(obs))
	for _, o := range obs {
		t, err := time.Parse("2006-01-02", o.ObsDate)
		if err != nil {
			continue
		}
		if start != nil && t.Before(*start) {
			continue
		}
		if end != nil && t.After(*end) {
			continue
		}
		out = append(out, o)
	}
	return out
}

func buildQuery(params map[string]any) url.Values {
	values := url.Values{}
	raw, ok := params["query"].(map[string]any)
	if !ok {
		return values
	}
	for k, v := range raw {
		values.Set(k, fmt.Sprint(v))
	}
	return values
}

func buildHeaders(params map[string]any) map[string]string {
	out := map[string]string{}
	raw, ok := params["headers"].(map[string]any)
	if !ok {
		return out
	}
	for k, v := range raw {
		out[k] = fmt.Sprint(v)
	}
	return out
}

func parseConfig(src *sources.Source) parse.Config {
	p := src.Params
	cfg := parse.Config{
		RowsPath:    p["rows_path"],
		RowSplit:    stringParam(p, "row_split"),
		DateField:   p["date_field"],
		ValueField:  p["value_field"],
		DateColumn:  stringParam(p, "date_column"),
		ValueColumn: stringParam(p, "value_column"),
		DateFormat:  stringParam(p, "date_format"),
		Sep:         stringParam(p, "sep"),
		SkipRows:    intParam(p, "skiprows"),
		Limit:       intParam(p, "limit"),
		Encoding:    stringParam(p, "encoding"),
		SourceName:  sourceNameOf(src),
	}
	if scale, ok := p["value_scale"].(float64); ok {
		cfg.ValueScale = scale
	}
	return cfg
}

func stringParam(p map[string]any, key string) string {
	if v, ok := p[key].(string); ok {
		return v
	}
	return ""
}

func intParam(p map[string]any, key string) int {
	switch v := p[key].(type) {
	case float64:
		return int(v)
	case int:
		return v
	}
	return 0
}

func sourceNameOf(src *sources.Source) string {
	if name, ok := src.Params["source"].(string); ok && name != "" {
		return name
	}
	return src.ID
}

func canonicalSeriesIDs(ids []string) []string {
	out := make([]string, 0, len(ids))
	for _, id := range ids {
		out = append(out, series.Canonical(id))
	}
	return out
}

func toAny[T any](items []T) []any {
	out := make([]any, len(items))
	for i, item := range items {
		out[i] = item
	}
	return out
}

func firstOrNil(paths []string) *string {
	if len(paths) == 0 {
		return nil
	}
	return &paths[0]
}

func totalRows(evs []collectEvidence) int {
	total := 0
	for _, ev := range evs {
		total += ev.Rows
	}
	return total
}

func errText(err error) string {
	if err == nil {
		return ""
	}
	return err.Error()
}

func truncate(s string, n int) string {
	runes := []rune(s)
	if len(runes) <= n {
		return s
	}
	return string(runes[:n]) + "…"
}

// intermediateDir 返回规范化中间文件目录（data_home/intermediate）。
func intermediateDir(dataHome string) string {
	return filepath.Join(dataHome, "intermediate")
}

// inboxDir 返回投喂箱目录（workspace/inbox，回落到 data_home/inbox）。
func inboxDir(workspace, dataHome string) string {
	if workspace != "" {
		return filepath.Join(workspace, "inbox")
	}
	return filepath.Join(dataHome, "inbox")
}

// HTTPStatusOf 便于测试断言。
func HTTPStatusOf(r *ProbeResult) int {
	if r.Detail.HTTPStatus == nil {
		return 0
	}
	return *r.Detail.HTTPStatus
}
