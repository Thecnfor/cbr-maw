// selfupdate 实现 `collector --selfupdate <installer> --expected-sha256 <hash>`。
//
// 流程（docs/11-实施设计.md §7.4）：
//  1. 校验安装包 sha256（不匹配 → 失败退出，不执行任何东西）
//  2. 等待主进程退出（--wait-pid）
//  3. 静默运行安装器（Windows: /VERYSILENT；其它平台只打印提示）
//  4. 重启应用（--restart）
//
// 这是唯一会触发外部动作的子命令；它不参与 JSON-RPC。
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

func runSelfUpdate(args []string) int {
	// 用法是 `--selfupdate <installer> --expected-sha256 <hash>`：位置参数在
	// 标志之前，Go 的 flag 包遇首个非标志即停止解析，因此先把 installer 摘出来。
	installer, rest := splitInstaller(args)
	if installer == "" {
		fmt.Fprintln(os.Stderr, "用法: collector --selfupdate <installer> --expected-sha256 <hash> [--wait-pid <pid>] [--restart <exe>]")
		return 2
	}
	fs := flag.NewFlagSet("selfupdate", flag.ContinueOnError)
	expected := fs.String("expected-sha256", "", "安装包 sha256（必填）")
	waitPID := fs.Int("wait-pid", 0, "等待退出的主进程 PID（0 表示不等待）")
	restart := fs.String("restart", "", "更新后重启的可执行文件路径")
	timeout := fs.Duration("wait-timeout", 60*time.Second, "等待主进程退出的最长时间")
	if err := fs.Parse(rest); err != nil {
		return 2
	}
	if *expected == "" {
		fmt.Fprintln(os.Stderr, "selfupdate: 缺少 --expected-sha256，拒绝执行未校验的安装包")
		return 2
	}
	actual, err := fileSHA256(installer)
	if err != nil {
		fmt.Fprintf(os.Stderr, "selfupdate: 读取安装包失败: %v\n", err)
		return 1
	}
	if !strings.EqualFold(actual, *expected) {
		fmt.Fprintf(os.Stderr, "selfupdate: sha256 校验失败（期望 %s，实际 %s），已中止\n", *expected, actual)
		return 1
	}
	if *waitPID > 0 {
		if err := waitProcessExit(*waitPID, *timeout); err != nil {
			fmt.Fprintf(os.Stderr, "selfupdate: 等待主进程退出失败: %v\n", err)
			return 1
		}
	}
	if err := runInstaller(installer); err != nil {
		fmt.Fprintf(os.Stderr, "selfupdate: 运行安装器失败: %v\n", err)
		return 1
	}
	if *restart != "" {
		if err := exec.Command(*restart).Start(); err != nil {
			fmt.Fprintf(os.Stderr, "selfupdate: 重启应用失败: %v\n", err)
			return 1
		}
	}
	fmt.Println("selfupdate: 完成")
	return 0
}

// splitInstaller 从参数里取出安装器路径，其余交给 flag 解析。
//
// 需要跳过标志的取值（如 `--expected-sha256 abc` 里的 abc），否则会被误当安装器。
func splitInstaller(args []string) (string, []string) {
	for i := 0; i < len(args); i++ {
		a := args[i]
		if strings.HasPrefix(a, "-") {
			if !strings.Contains(a, "=") {
				i++ // 跳过该标志的取值
			}
			continue
		}
		rest := append(append([]string{}, args[:i]...), args[i+1:]...)
		return a, rest
	}
	return "", args
}

func fileSHA256(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer f.Close()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

func runInstaller(installer string) error {
	if runtime.GOOS == "windows" {
		cmd := exec.Command(installer, "/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES")
		return cmd.Run()
	}
	// 非 Windows 平台：仅执行可执行位安装器；不静默（避免误删用户文件）。
	return exec.Command(installer).Run()
}

func waitProcessExit(pid int, timeout time.Duration) error {
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		if !processAlive(pid) {
			return nil
		}
		time.Sleep(200 * time.Millisecond)
	}
	return fmt.Errorf("主进程 %d 在 %s 内未退出", pid, timeout)
}

func processAlive(pid int) bool {
	if runtime.GOOS == "windows" {
		out, err := exec.Command("tasklist", "/FI", "PID eq "+strconv.Itoa(pid)).Output()
		return err == nil && strings.Contains(string(out), strconv.Itoa(pid))
	}
	return syscall.Kill(pid, syscall.Signal(0)) == nil
}
