# JARVIS 通用一键 push + GitHub Release（v0.1.5 之后所有版本）
#
# 用法（仓库根目录，PowerShell 7）：
#   pwsh packaging\release.ps1 -Version 0.1.6
#   pwsh packaging\release.ps1 -Version 0.1.6 -SkipPush -SkipAssets
#
# 步骤：① 本地 tag 幂等创建 → ② push main → ③ push tag → ④ 创建/补齐 GitHub Release
# （notes 取 docs/releases/v<version>.md）→ ⑤ 上传便携包资产。
#
# 资产上传纪律（v0.1.5 实证）：fine-grained token 下 base64 POST asset 端点 404，
# 必须走 PUT https://uploads.github.com/repos/<owner>/<repo>/releases/<id>/assets?name=<name>
# 二进制流（Content-Type: application/octet-stream）。只上传两个预期资产：
#   jarvis-gui-<version>-win-x64-portable.zip
#   sha256-jarvis-gui-<version>-win-x64-portable
# 已存在的资产按名跳过（幂等）。
#
# token 来源（优先级）：-Token 参数 > GITHUB_TOKEN > GH_TOKEN >
# build\gh_cred.txt 中 `password = <token>` 行（不回显 token）。
param(
    [Parameter(Mandatory = $true)][string]$Version,
    [string]$Token = "",
    [string]$CredFile = "build\gh_cred.txt",
    [string]$TagMessage = "",
    [string]$AssetsDir = "release",
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [switch]$SkipPush,
    [switch]$SkipAssets
)
$ErrorActionPreference = "Stop"
Push-Location $Repo
try {
    $ownerRepo = "newkicar/truly-jarvis"
    $tag = "v$Version"
    $notesFile = Join-Path $Repo "docs/releases/$tag.md"
    $api = "https://api.github.com/repos/$ownerRepo"

    if (-not $Token) { $Token = $env:GITHUB_TOKEN }
    if (-not $Token) { $Token = $env:GH_TOKEN }
    if (-not $Token -and (Test-Path $CredFile)) {
        $cred = Get-Content $CredFile
        $pwdLine = @($cred | Where-Object { $_ -match '^\s*password\s*=' })[0]
        $Token = ($pwdLine -replace '^.*password\s*=\s*', '').Trim()
    }
    if (-not $Token) {
        Write-Host "[WARN] 无可用 token：走无 API 路径（仅 tag push；release 入口需网页操作）" -ForegroundColor Yellow
    }

    # ① tag 幂等
    git rev-parse --verify --quiet $tag *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[1/4] tag $tag 已存在"
    }
    else {
        if (-not $TagMessage) {
            $TagMessage = "$tag：packaging 参数化（build_gui.ps1 -Version / release.ps1 PUT 上传）+ 公开发现面路径归一化 + 测试可移植性"
        }
        Write-Host "[1/4] 创建 tag $tag …"
        git tag -a $tag -m $TagMessage
    }

    # ②③ push
    if (-not $SkipPush) {
        Write-Host "[2/4] git push origin main …"
        git push origin main
        Write-Host "[3/4] git push origin $tag …"
        git push origin $tag
    }
    else { Write-Host "[2/4][3/4] 跳过 push (-SkipPush)" }

    # ④⑤ Release + 资产
    $url = "https://github.com/$ownerRepo/releases/tag/$tag"
    if (-not $Token) {
        Write-Host "[4/4] tag 已推送，release 入口见 $url"
        Write-Host "      如需自动填 notes/传资产：设 GITHUB_TOKEN 或 -Token 后重跑（幂等）"
        return
    }
    $h = @{ Authorization = "Bearer $Token"; Accept = "application/vnd.github+json" }
    Write-Host "[4/4] 创建/补齐 GitHub Release …"
    $rel = $null
    try { $rel = Invoke-RestMethod -Uri "$api/releases/tags/$tag" -Headers $h -Method Get } catch { }
    if (-not $rel) {
        $body = if (Test-Path $notesFile) { Get-Content $notesFile -Raw } else { $tag }
        $rel = Invoke-RestMethod -Uri "$api/releases" -Headers $h -Method Post -Body ([pscustomobject]@{
            tag_name = $tag; name = $tag; body = $body; draft = $false; prerelease = $false
        } | ConvertTo-Json -Depth 4)
        Write-Host "      release 已创建：$($rel.html_url)"
    }
    else { Write-Host "      release 已存在，跳过创建：$($rel.html_url)" }

    if (-not $SkipAssets) {
        $expected = @(
            "jarvis-gui-$Version-win-x64-portable.zip",
            "sha256-jarvis-gui-$Version-win-x64-portable"
        )
        foreach ($name in $expected) {
            $path = Join-Path $AssetsDir $name
            if (-not (Test-Path $path)) {
                Write-Warning "缺失资产 $name（AssetsDir=$AssetsDir）—— 先跑 packaging\build_gui.ps1 -Version $Version"
                continue
            }
            $exists = @($rel.assets | Where-Object { $_.name -eq $name })
            if ($exists.Count -gt 0) { Write-Host "      资产 $name 已存在，跳过"; continue }
            Write-Host "      上传 $name （PUT uploads.github.com，二进制流）…"
            $bytes = [System.IO.File]::ReadAllBytes($path)
            $up = Invoke-WebRequest -Uri ("https://uploads.github.com/repos/$ownerRepo/releases/$($rel.id)/assets?name=" + [Uri]::EscapeDataString($name)) `
                    -Method Put -Headers @{ Authorization = "Bearer $Token" } `
                    -Body $bytes -ContentType "application/octet-stream" -UseBasicParsing
            if ($up.StatusCode -ge 300) { throw "上传 $name 失败：HTTP $($up.StatusCode)" }
            Write-Host "      -> $name 上传完成（$([math]::Round($bytes.Length / 1MB, 1)) MB）"
        }
        $rel = Invoke-RestMethod -Uri "$api/releases/tags/$tag" -Headers $h -Method Get
        Write-Host "      release 当前资产清单："
        foreach ($a in $rel.assets) { Write-Host ("        " + $a.name + "  (" + $a.size + " bytes)") }
    }
    else { Write-Host "[5/5] 跳过资产上传 (-SkipAssets)" }
    Write-Host "完成。Release：$url"
}
finally { Pop-Location }
