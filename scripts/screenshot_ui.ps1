# 截图验收脚本（Edge headless）
# 用法：先启动 API（uvicorn cbr.api.main:app --port 8000），再执行本脚本：
#   pwsh -File scripts/screenshot_ui.ps1
# 产物：artifacts/ui/*.png（light / dark / chat）
param(
  [string]$BaseUrl = "http://127.0.0.1:8000",
  [string]$OutDir = "artifacts/ui"
)

$ErrorActionPreference = "Stop"
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edge)) { throw "未找到 Edge: $edge" }
$OutDir = if ([System.IO.Path]::IsPathRooted($OutDir)) { $OutDir } else { Join-Path (Get-Location).Path $OutDir }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$profile = Join-Path $env:TEMP "edge-cbr-ui-profile"

function Capture([string]$url, [string]$file, [int]$height = 1000) {
  $absolute = [System.IO.Path]::GetFullPath((Join-Path $OutDir $file))
  $args = @(
    "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
    "--disable-extensions", "--force-device-scale-factor=1",
    "--user-data-dir=$profile",
    "--window-size=1440,$height", "--virtual-time-budget=25000",
    "--screenshot=$absolute", $url
  )
  & $edge @args 2>$null | Out-Null
  Write-Host "[OK] $absolute"
}

Capture "$BaseUrl/ui/?theme=light" "dashboard_light.png" 1200
Capture "$BaseUrl/ui/?theme=dark" "dashboard_dark.png" 1200
Capture "$BaseUrl/ui/?theme=light#/chat" "chat_light.png" 1000
Write-Host "截图完成：$OutDir"
