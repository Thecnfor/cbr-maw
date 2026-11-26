// Command collector 是 CBR-MAW 的 Go 采集 sidecar。
//
// 用法：
//
//	collector [--workspace <p>] [--data-home <p>] [--resource-home <p>] [--log-level <lvl>]
//	collector --selfupdate <installer> --expected-sha256 <hash> [--wait-pid <pid>] [--restart <exe>]
//
// 传输：stdin/stdout NDJSON JSON-RPC 2.0；日志写 stderr JSONL。
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"cbr-maw/services/collector/internal/logx"
	"cbr-maw/services/collector/internal/rpc"
	"cbr-maw/services/collector/internal/service"
)

func main() {
	// 自更新子命令必须在 sidecar 主流程之前分流。
	if len(os.Args) > 1 && os.Args[1] == "--selfupdate" {
		os.Exit(runSelfUpdate(os.Args[2:]))
	}

	fs := flag.NewFlagSet("collector", flag.ExitOnError)
	workspace := fs.String("workspace", "", "工作区绝对路径")
	dataHome := fs.String("data-home", "", "可写根绝对路径")
	resourceHome := fs.String("resource-home", "", "只读资源根绝对路径")
	logLevel := fs.String("log-level", "info", "日志级别 debug/info/warn/error")
	repoRoot := fs.String("repo-root", "", "开发期仓库根（用于定位 configs 与 legacy-configs）")
	if err := fs.Parse(os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if *repoRoot == "" {
		*repoRoot = detectRepoRoot()
	}

	logger := logx.New("collector", *logLevel)
	logger.Info("collector 启动", map[string]any{
		"version": service.Version, "contract_version": service.ContractVersion,
		"workspace": *workspace, "data_home": *dataHome, "resource_home": *resourceHome, "repo_root": *repoRoot,
	})

	svc := service.New(logger, *repoRoot)
	srv := rpc.NewServer(os.Stdin, os.Stdout)
	svc.Register(srv)

	done := make(chan struct{})
	go func() {
		<-svc.StopCh()
		// shutdown 后给在途响应 2s 落地时间，然后强退（契约 §1 生命周期）。
		time.Sleep(2 * time.Second)
		close(done)
		os.Exit(0)
	}()

	if err := srv.Serve(); err != nil {
		logger.Error("消息循环异常退出", map[string]any{"error": err.Error()})
		os.Exit(1)
	}
	select {
	case <-done:
	default:
	}
}

// detectRepoRoot 从可执行文件位置向上找包含 contracts/ 的目录（开发期便利）。
func detectRepoRoot() string {
	exe, err := os.Executable()
	if err != nil {
		return ""
	}
	dir := filepath.Dir(exe)
	for i := 0; i < 6; i++ {
		if _, err := os.Stat(filepath.Join(dir, "contracts", "VERSION")); err == nil {
			return dir
		}
		dir = filepath.Dir(dir)
	}
	if cwd, err := os.Getwd(); err == nil {
		for i := 0; i < 6; i++ {
			if _, err := os.Stat(filepath.Join(cwd, "contracts", "VERSION")); err == nil {
				return cwd
			}
			cwd = filepath.Dir(cwd)
		}
	}
	return ""
}
