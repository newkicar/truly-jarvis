<#
jarvis-gui Nuitka onedir 便携包构建（GUI-only；入口 src\gui_main.py，--windows-console-mode=disable）

布局约定（扁平）：
  dist\jarvis-gui\ = gui_main.dist\ 全部内容平铺同级（jarvis-gui.exe + DLL + skills\ + ...）
  skills 随包置于 exe 同级；frozen 形态 install_root() = exe 所在目录（src\project_paths.py）

用法：
  powershell -NoProfile -File packaging\build_gui.ps1 [-Version 0.1.7] [-SkipZip] [-SkipVerify]

前置：.build\venv-base（Py 3.14 + Nuitka 4.3.4 + PySide6 + 项目依赖），本机 MSVC。
#>
param(
    [string]$Version = "0.1.7",
    [switch]$SkipZip,
    [switch]$SkipVerify
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Fail($msg) { Write-Host "[FAIL] $msg" -ForegroundColor Red; exit 1 }

if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { Fail "Version must be x.y.z (e.g. 0.1.7), got: $Version" }
Write-Host "build version: $Version" -ForegroundColor DarkGray

# ---------- [1/8] 前置检查 ----------
Write-Host '[1/8] 前置检查' -ForegroundColor Cyan
foreach ($f in 'src\gui_main.py', 'skills\__init__.py', 'LICENSE.txt', 'packaging\README-portable.md') {
    if (-not (Test-Path $f)) { Fail "缺少 $f —— 请确认本地工作区完整（skills/ 不入库，需本地构建环境）" }
}
$py = '.build\venv-base\Scripts\python.exe'
if (-not (Test-Path $py)) { Fail "缺少 $py —— 请先创建 .build\venv-base（见 packaging\README.md）" }

# ---------- [2/8] venv 依赖 ----------
Write-Host '[2/8] 检查 venv 依赖' -ForegroundColor Cyan
& $py -m nuitka --version 2>&1 | Select-Object -First 1 | Out-Host
if ($LASTEXITCODE -ne 0) { & $py -m pip install 'nuitka==4.3.4' }
& $py -m pip install -e . 2>&1 | Select-Object -Last 2 | Out-Host
# 移除 Google GenAI 传递链（deepagents 惰性可选依赖，规避 MSVC C1002 崩溃；须在所有 pip install 之后）
& $py -m pip uninstall -y langchain-google-genai google-genai 2>&1 | Select-Object -Last 2 | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host '[WARN] uninstall 未全部成功 —— 请人工确认 venv 无 Google GenAI 残留' -ForegroundColor Yellow }

# ---------- [3/8] Nuitka 编译 ----------
Write-Host '[3/8] Nuitka 编译（暖缓存 30-90 分钟；日志 build\nuitka.out.log / .err.log）' -ForegroundColor Cyan
# Nuitka 缓存隔离（环境变量名经 Nuitka 4.3.4 nuitka\utils\AppDirs.py 源码核实，2026-11-22）：
#   全局缓存基目录读 $env:NUITKA_CACHE_DIR。旧脚本的 $env:__NUITKA_CACHE_DIR__ 拼写不是 Nuitka 读取的变量，一直无效，
#   全局 C 对象缓存实际仍在 AppData Local，与其他项目共享（锁争用来源）。
#   SCons MSVC 配置缓存：Nuitka SconsInterface.py 无条件设置 SCONS_CACHE_MSVC_CONFIG 指向按型缓存目录；
#   按型变量名 = NUIKTA_CACHE_DIR_ 前缀 + 基名「-」换「_」并大写，即 $env:NUITKA_CACHE_DIR_SCONS_MSVC_CONFIG。
#   SCons 4.10.1 的 FileLock 是 lockfile 方案（os.open 以 O_CREAT|O_EXCL 创建 <file>.lock，非 msvcrt 字节锁）；
#   全局共享 AppData 缓存 + AV 高扫描区下，锁文件创建失败或残留即 5 秒等待超时 -> FATAL: SConsLockFailure（2026-11-22 事故，构建两次中断）。
#   两级缓存均隔离到项目内 .build\；首次运行 vcvars 重新探测一次，略增时。勿对本项目并发跑 Nuitka 构建。
$env:NUITKA_CACHE_DIR = (Join-Path $repo ".build\nuitka-cache")
New-Item -ItemType Directory -Force -Path $env:NUITKA_CACHE_DIR | Out-Null
$env:NUITKA_CACHE_DIR_SCONS_MSVC_CONFIG = (Join-Path $repo ".build\scons-msvc-config")
New-Item -ItemType Directory -Force -Path $env:NUITKA_CACHE_DIR_SCONS_MSVC_CONFIG | Out-Null
$env:VSLANG = '1033'  # MSVC cl/link 英文输出，避免本地化噪声触发 Nuitka 英文模式过滤器误判（纯降噪，非根因）
New-Item -ItemType Directory -Force -Path 'build\nuitka-out' | Out-Null
Remove-Item 'build\nuitka.out.log', 'build\nuitka.err.log' -ErrorAction SilentlyContinue
# skills 随包：用 --include-raw-dir（不套默认后缀/目录过滤）。
# 历史 --include-data-dir 会被 Nuitka default_ignored_suffixes 静默滤掉 .py / __pycache__，
# 导致 skill-outlook-controller 等技能 scripts\*.py 缺失进包（2026-11-22 修复）。
# raw-dir 不做任何过滤，先清理运行时生成的 __pycache__，防止生成物进包。
Get-ChildItem 'skills' -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
$nuArgs = '-m nuitka --standalone --enable-plugin=pyside6 --windows-console-mode=disable --include-raw-dir=skills=skills --include-data-file=skills\__init__.py=skills\__init__.py --output-dir=build\nuitka-out --output-filename=jarvis-gui --jobs=4 --assume-yes-for-downloads --nofollow-import-to=langchain_quickjs --nofollow-import-to=quickjs_rs --nofollow-import-to=wasmtime --include-package=langchain_core --include-package=langchain --include-package=langchain_openai --include-package=openai --include-package=anthropic --include-package=langchain_anthropic --include-package=langchain_mcp_adapters --include-package=langgraph --include-package=langgraph_sdk --include-package=deepagents --include-package=mcp --include-package=pydantic --include-package=pydantic_core --include-package=pydantic_settings --include-package=httpx --include-package=keyring --include-package=apscheduler --include-package=aiosqlite --nofollow-import-to=chromadb --nofollow-import-to=langchain_quickjs --nofollow-import-to=quickjs_rs --nofollow-import-to=wasmtime src\gui_main.py'
$proc = Start-Process -FilePath $py -ArgumentList $nuArgs -WorkingDirectory $repo `
    -RedirectStandardOutput 'build\nuitka.out.log' -RedirectStandardError 'build\nuitka.err.log' -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    Write-Host "[FAIL] Nuitka 退出码 $($proc.ExitCode) —— build\nuitka.err.log 末 40 行：" -ForegroundColor Red
    Get-Content 'build\nuitka.err.log' -Tail 40
    exit 1
}

# ---------- [4/8] 扁平 staging ----------
Write-Host '[4/8] 扁平 staging 到 dist\jarvis-gui' -ForegroundColor Cyan
$distSrc = 'build\nuitka-out\gui_main.dist'
if (-not (Test-Path (Join-Path $distSrc 'jarvis-gui.exe'))) { Fail "$distSrc\jarvis-gui.exe 缺失" }
$stage = 'dist\jarvis-gui'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
robocopy $distSrc $stage /E /NFL /NDL /NJH /NJS /NP /MT:8 | Out-Null
if ($LASTEXITCODE -ge 8) { Fail ('robocopy failed rc=' + $LASTEXITCODE) }
Copy-Item (Join-Path $repo 'skills\__init__.py') (Join-Path $stage 'skills\__init__.py') -Force
$fileCount = (Get-ChildItem $stage -Recurse -File).Count
$totalMb = [math]::Round(((Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
$exeMb = [math]::Round(((Get-Item (Join-Path $stage 'jarvis-gui.exe')).Length / 1MB), 1)
Write-Host "staging: $totalMb MB / $fileCount 文件（exe $exeMb MB）"
# ---------- [5/8] runtime-info.txt ----------
Write-Host '[5/8] 生成 packaging\runtime-info.txt' -ForegroundColor Cyan
$ver = (& $py --version 2>&1 | Out-String).Trim()
$runtimeInfo = @(
    "version: $Version",
    ('build-time: ' + (Get-Date -Format 'yyyy-MM-dd HH:mm')),
    "python: $ver",
    'nuitka: 4.3.4',
    'pyside6-essentials: 6.12.0',
    ('size: {0} MB（{1} 个文件，其中 exe {2} MB）' -f $totalMb, $fileCount, $exeMb),
    'startup-time: 待冒烟'
)
Set-Content 'packaging\runtime-info.txt' $runtimeInfo -Encoding utf8

# ---------- [6/8] zip + SHA-256 ----------
$zipName = "jarvis-gui-$Version-win-x64-portable.zip"
if (-not $SkipZip) {
    Write-Host '[6/8] zip + SHA-256 (release\)' -ForegroundColor Cyan
    $zipStage = 'build\zip-staging'
    $zipInner = Join-Path $zipStage 'jarvis-gui'
    if (Test-Path $zipStage) { Remove-Item $zipStage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $zipInner | Out-Null
    Copy-Item (Join-Path $stage '*') $zipInner -Recurse
    Copy-Item 'packaging\README-portable.md' (Join-Path $zipInner '使用说明.md')
    Copy-Item 'LICENSE.txt' (Join-Path $zipInner 'LICENSE.txt')
    New-Item -ItemType Directory -Force -Path 'release' | Out-Null
    $zipPath = Join-Path 'release' $zipName
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path (Join-Path $zipStage '*') -DestinationPath $zipPath
    if (-not (Test-Path $zipPath)) { Fail 'Compress-Archive 未产出 zip' }
    $sha = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
    $shaName = 'sha256-' + ($zipName -replace '\.zip$', '')
    Set-Content (Join-Path 'release' $shaName) ("{0}  {1}" -f $sha, $zipName) -Encoding ascii
    Remove-Item $zipStage -Recurse -Force
    Write-Host ("zip: release\" + $zipName + "  sha256: " + $sha)
} else {
    Write-Host '[6/8] 跳过 zip (-SkipZip)' -ForegroundColor Yellow
}

# ---------- [7/8] 验证扁平布局 ----------
if (-not $SkipVerify) {
    Write-Host '[7/8] 验证扁平布局' -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $stage 'skills\__init__.py'))) { Fail 'skills\__init__.py 不在 exe 同级' }
    $skillDirs = (Get-ChildItem (Join-Path $stage 'skills') -Directory).Count
    if ($skillDirs -lt 1) { Fail 'skills 下无子目录' }
    # .py 过滤回归断言（raw-dir 应原样携带全部 .py；防止参数误改回 --include-data-dir 后再次静默缺失）
    $srcPy = (Get-ChildItem 'skills' -Recurse -File -Filter '*.py').Count
    $dstPy = (Get-ChildItem (Join-Path $stage 'skills') -Recurse -File -Filter '*.py').Count
    if ($srcPy -ne $dstPy) { Fail ("skills .py 数量不一致（源 $srcPy / 包内 $dstPy）——检查 --include-raw-dir=skills=skills 是否被误改回 --include-data-dir") }
    $pccache = (Get-ChildItem (Join-Path $stage 'skills') -Recurse -Directory -Filter '__pycache__').Count
    if ($pccache -gt 0) { Fail ("skills 包内残留 __pycache__（$pccache 处）") }
    foreach ($bad in 'textual', 'google_genai', 'langchain_google_genai', 'src') {
        if (Test-Path (Join-Path $stage $bad)) { Fail ("dist\jarvis-gui\" + $bad + ' 残留（不应存在）') }
    }
    if (Get-ChildItem $stage -Recurse -File -Filter '*google_genai*') { Fail '*google_genai* 文件残留' }
    Write-Host ("验证通过（skills 子目录 " + $skillDirs + "，无 textual/google_genai/src 残留）")
} else {
    Write-Host '[7/8] 跳过验证 (-SkipVerify)' -ForegroundColor Yellow
}

# ---------- [8/8] 汇总 ----------
Write-Host '[8/8] 汇总' -ForegroundColor Green
Write-Host ("  staging: dist\jarvis-gui（" + $totalMb + " MB / " + $fileCount + " 文件，exe " + $exeMb + " MB）")
if (-not $SkipZip) { Write-Host ("  release: release\" + $zipName + " + release\" + $shaName) }
Write-Host '  下一步: 1) packaging\smoke_gui.ps1 冒烟  2) packaging\README.md 基线行填数  3) GitHub Release 上传（web UI）'
