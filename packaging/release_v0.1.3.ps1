# JARVIS v0.1.3 一键 push + GitHub Release
#
# 用法（仓库根目录，PowerShell 7）：
#   pwsh packaging\release_v0.1.3.ps1
#   pwsh packaging\release_v0.1.3.ps1 -Token <PAT> -AssetsDir release
#
# 步骤：① 确保本地 tag 存在 → ② push main → ③ push tag → ④ 创建 GitHub Release
# （有 token 走 API 建 release + 传资产；无 token 时 tag push 后 GitHub 自动生成
#  release 入口，notes 可后续在网页粘贴 docs/releases/v0.1.3.md）
param(
    [string]$Tag = "v0.1.3",
    [string]$Token = "",
    [string]$AssetsDir = "",
    [string]$Repo = (Split-Path -Parent $PSScriptRoot)
)
$ErrorActionPreference = "Stop"
Push-Location $Repo
try {
    $ownerRepo = "newkicar/truly-jarvis"
    $notesFile = Join-Path $Repo "docs/releases/$Tag.md"
    $token = $Token
    if (-not $token) { $token = $env:GITHUB_TOKEN }
    if (-not $token) { $token = $env:GH_TOKEN }

    # ① tag 幂等
    git rev-parse --verify --quiet $Tag *> $null
    if ($LASTEXITCODE -eq 0) { Write-Host "[1/4] tag $Tag 已存在" }
    else {
        Write-Host "[1/4] 创建 tag $Tag …"
        git tag -a $Tag -m "${Tag}：/use skill 补全任意位置锚定（tui-ux24，TUI+GUI 共享内核）+ GUI skill 单字符无匹配弹层显示（gui-ux25）"
    }

    # ② push main
    Write-Host "[2/4] git push origin main …"
    git push origin main

    # ③ push tag
    Write-Host "[3/4] git push origin $Tag …"
    git push origin $Tag

    # ④ GitHub Release
    $url = "https://github.com/$ownerRepo/releases/tag/$Tag"
    if (-not $token) {
        Write-Host "[4/4] 未提供 token（-Token 或 GITHUB_TOKEN）：tag 已推送，release 入口见 $url"
        Write-Host "      如需自动填 notes/传资产：$env:GH_TOKEN 或 -Token 带 PAT 重跑（幂等）"
    }
    else {
        $api = "https://api.github.com/repos/$ownerRepo"
        $h = @{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json" }
        Write-Host "[4/4] 创建/补齐 GitHub Release …"
        $rel = $null
        try { $rel = Invoke-RestMethod -Uri "$api/releases/tags/$Tag" -Headers $h -Method Get } catch { }
        if (-not $rel) {
            $body = if (Test-Path $notesFile) { Get-Content $notesFile -Raw } else { $Tag }
            $rel = Invoke-RestMethod -Uri "$api/releases" -Headers $h -Method Post -Body ([pscustomobject]@{
                tag_name = $Tag; name = $Tag; body = $body; draft = $false; prerelease = $false
            } | ConvertTo-Json -Depth 4)
            Write-Host "      release 已创建：$($rel.html_url)"
        }
        else { Write-Host "      release 已存在，跳过创建：$($rel.html_url)" }

        if ($AssetsDir -and (Test-Path $AssetsDir)) {
            # 便携版资产：exe/zip + sha256 清单
            $files = Get-ChildItem $AssetsDir -Recurse -File -Include *.exe,*.zip,*.txt,*.json,*.py
            foreach ($f in $files) {
                $name = $f.Name
                $exists = @($rel.assets | Where-Object { $_.name -eq $name })
                if ($exists) { Write-Host "      资产 $name 已存在，跳过"; continue }
                Write-Host "      上传 $($f.FullName) …"
                $bytes = [System.IO.File]::ReadAllBytes($f.FullName)
                $b64 = [Convert]::ToBase64String($bytes)
                $up = Invoke-RestMethod -Uri "$api/releases/$($rel.id)/assets?name=$([Uri]::EscapeDataString($name))" `
                        -Headers (@{ Authorization = "Bearer $token"; Accept = "application/vnd.github+json" }) `
                        -Method Post -Body ([pscustomobject]@{ data = $b64 } | ConvertTo-Json)
                Write-Host "      → $($up.browser_download_url)"
            }
        }
        elseif ($AssetsDir) { Write-Warning "AssetsDir 不存在：$AssetsDir（先跑 packaging\build_gui.ps1）" }
        else { Write-Host "      未传 -AssetsDir：便携包资产留后补（build_gui.ps1 构建后再传）" }
    }
    Write-Host "完成。Release：$url"
}
finally { Pop-Location }
