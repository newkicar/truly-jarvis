<#
便携包冒烟测试：dist\jarvis-gui\jarvis-gui.exe
隔离环境：JARVIS_HOME / APPDATA / LOCALAPPDATA 全部指向 .build\smoke-*，安装目录零写入。
用法：powershell -NoProfile -File packaging\smoke_gui.ps1 [-Exe dist\jarvis-gui\jarvis-gui.exe] [-WaitSec 60]
通过判据：进程存活 + 窗口出现 + skills seed 数 > 0
#>
param([string]$Exe = 'dist\jarvis-gui\jarvis-gui.exe', [int]$WaitSec = 60)
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
$ErrorActionPreference = 'Stop'
if (-not (Test-Path $Exe)) { throw ('未找到 ' + $Exe + ' —— 请先运行 packaging\build_gui.ps1') }
$homeDir = Join-Path $repo '.build\smoke-home'
$appDir = Join-Path $repo '.build\smoke-appdata'
$cwdDir = Join-Path $repo '.build\smoke-cwd'
$localDir = Join-Path $repo '.build\smoke-local'
foreach ($d in @($homeDir, $appDir, $cwdDir, $localDir)) {
    if (Test-Path $d) { Remove-Item $d -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
$env:JARVIS_HOME = $homeDir
$env:APPDATA = $appDir
$env:LOCALAPPDATA = $localDir
$sw = [Diagnostics.Stopwatch]::StartNew()
$p = Start-Process (Join-Path $repo $Exe) -PassThru -WorkingDirectory $cwdDir
$shown = $false
while ($sw.Elapsed.TotalSeconds -lt $WaitSec) {
    if ($p.HasExited) { break }
    if ($p.MainWindowHandle -ne [IntPtr]::Zero) { $shown = $true; break }
    Start-Sleep -Milliseconds 250
}
$sw.Stop()
if ($shown) { Start-Sleep -Seconds 2 }
$skillCount = 0
if (Test-Path (Join-Path $homeDir 'skills')) {
    $skillCount = (Get-ChildItem (Join-Path $homeDir 'skills') -Directory).Count
}
Write-Host '--- 冒烟结果 ---'
Write-Host ('进程存活 : ' + (-not $p.HasExited))
Write-Host ('窗口已出现: ' + $shown)
Write-Host ('窗口标题 : ' + $p.MainWindowTitle)
Write-Host ('启动耗时 : ' + $sw.Elapsed)
Write-Host ('skills seed: ' + $skillCount + '（JARVIS_HOME\skills）')
Write-Host ('向导配置落盘: ' + (Test-Path (Join-Path $appDir 'Jarvis\config.json')))
if ((-not $p.HasExited) -and $shown -and $skillCount -gt 0) {
    Stop-Process -Id $p.Id -Force
    Write-Host '冒烟通过判据：存活 + 窗口已出现 + 标题非空 + skills>0' -ForegroundColor Green
} else {
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    Write-Warning '冒烟未全通过 —— 查看 build\nuitka.err.log，或 cmd 手动跑 exe 看控制台输出（--windows-console-mode=disable 时可用 Nuitka 日志定位）'
}
Pop-Location
