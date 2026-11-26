package main

import (
	"os"
	"path/filepath"
	"testing"
)

// TestSplitInstaller 位置参数可出现在标志之前（--selfupdate <installer> ...）。
func TestSplitInstaller(t *testing.T) {
	installer, rest := splitInstaller([]string{"/tmp/a.exe", "--expected-sha256", "abc"})
	if installer != "/tmp/a.exe" {
		t.Fatalf("installer = %q", installer)
	}
	if len(rest) != 2 || rest[0] != "--expected-sha256" {
		t.Fatalf("rest = %v", rest)
	}
	if installer, _ := splitInstaller([]string{"--expected-sha256", "abc"}); installer != "" {
		t.Fatalf("无位置参数时 installer 应为空，实际 %q", installer)
	}
}

// TestSelfUpdateRejectsBadHash 哈希不匹配时不得执行安装器。
func TestSelfUpdateRejectsBadHash(t *testing.T) {
	dir := t.TempDir()
	installer := filepath.Join(dir, "fake-installer")
	if err := os.WriteFile(installer, []byte("hello"), 0o755); err != nil {
		t.Fatal(err)
	}
	code := runSelfUpdate([]string{installer, "--expected-sha256", "deadbeef"})
	if code != 1 {
		t.Fatalf("exit = %d, want 1（哈希不符必须中止）", code)
	}
}

// TestSelfUpdateRequiresHash 缺哈希时拒绝执行。
func TestSelfUpdateRequiresHash(t *testing.T) {
	dir := t.TempDir()
	installer := filepath.Join(dir, "fake-installer")
	if err := os.WriteFile(installer, []byte("hello"), 0o755); err != nil {
		t.Fatal(err)
	}
	if code := runSelfUpdate([]string{installer}); code != 2 {
		t.Fatalf("exit = %d, want 2", code)
	}
}

// TestFileSHA256 sha256 计算与 sha256sum 口径一致。
func TestFileSHA256(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "abc")
	if err := os.WriteFile(path, []byte("abc"), 0o644); err != nil {
		t.Fatal(err)
	}
	got, err := fileSHA256(path)
	if err != nil {
		t.Fatal(err)
	}
	want := "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
	if got != want {
		t.Fatalf("sha256 = %s", got)
	}
}
