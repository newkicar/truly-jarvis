# JARVIS GUI 打包构建（Nuitka onedir）
#
# 用法（在仓库根目录，PowerShell 7）：
#   pwsh packaging\build_gui.ps1
#   pwsh packaging\build_gui.ps1 -Python D:\python_env\python.exe
#
# 产物：
#   dist\jarvis-gui\            Nuitka onedir 目录（gui_main.exe + Qt DLL + 模块，同目录动态共存）
#   packaging\runtime-info.txt  体积 / 构建基线（每次构建刷新；启动时间 = 人工冒烟后补录）
#
# 约定（spec 打包章节）：
# - onedir 不用 onefile（单文件启动慢）；
# - 基础 venv 不装 chromadb（遗留 c：可选依赖降级，RAG 缺失自动回落 grep/wiki）；
# - PySide6-Essentials（不带 Addons/WebEngine）；
# - 安装目录只读：全部用户写入走 %APPDATA%\Jarvis 与 .jarvis（安装目录零写入）；
# - Qt DLL 与 exe 同目录 = LGPL 动态链接形态（无需静态链接源提供义务）。
param(
    [string]$Python = "python",
    [string]$VenvDir = ".build\venv-base",
    [string]$NuiKake = "",
    [string]$OutDir = "dist\jarvis-gui"
)

$ErrorActionPreference = "Stop"
$repo = (Split-Path -Parent $PSScriptRoot)
Push-Location $repo
try {
    # ① 干净基础 venv（无 chromadb / onnxruntime → RAG 自动降级）
    if (-not (Test-Path "$VenvDir\Scripts\python.exe")) {
        & $Python -m venv $VenvDir
        & "$VenvDir\Scripts\python.exe" -m pip install --upgrade pip wheel nuitka
    }
    & "$VenvDir\Scripts\python.exe" -m pip install -e .   # 基础依赖（不含 RAG 可选组）
    $py = "$VenvDir\Scripts\python.exe"

    # ② Nuitka onedir 构建（C 扩展产物缓存在 .build\nuitka-cache，CI 可复用，增量秒级）
    $extra = @()
    if ($NuiKake) { $extra = $NuiKake -split ' ' }
    & $py -m nuitka `
        --standalone `
        --enable-plugin=pyside6 `
        --windows-console-mode=disable `
        --include-package=src `
        --include-package=jarvis `
        --output-dir=build\nuitka-out `
        --output-filename=gui_main `
        --cache-dir=.build\nuitka-cache `
        @extra `
        src\gui_main.py

    # ③ 收拢产物：exe + .dist 目录内容 → 同目录（LGPL 动态共存布局）
    $exe   = "build\nuitka-out\gui_main.exe"
    $dist  = "build\nuitka-out\gui_main.dist"
    if (-not (Test-Path $exe) -or -not (Test-Path $dist)) {
        throw "Nuitka 产物缺失（$exe / $dist）——先查 Nuitka 编译日志"
    }
    Remove-Item $OutDir -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Path $OutDir | Out-Null
    Copy-Item $exe $OutDir
    Copy-Item "$dist\*" $OutDir -Recurse
    Write-Host "构建完成 → $OutDir"

    # ④ 基线记录（体积 + 构建耗时；启动时间为人工冒烟项，见 packaging/README.md）
    $sizeMb = [math]::Round(((Get-ChildItem $OutDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
    $nFiles = (Get-ChildItem $OutDir -Recurse -File).Count
    "构建时间        : $(Get-Date -Format 'yyyy-MM-dd HH:mm')" | Out-File "packaging\runtime-info.txt" -Encoding utf8
    "产物            : $OutDir（${nFiles} 个文件 / ${sizeMb} MB）" | Out-File "packaging\runtime-info.txt" -Append -Encoding utf8
    "启动时间        : 待人工冒烟后补录（首启向导页出现耗时）" | Out-File "packaging\runtime-info.txt" -Append -Encoding utf8
    Write-Host "基线已刷新：${sizeMb} MB / ${nFiles} 文件"
}
finally {
    Pop-Location
}
