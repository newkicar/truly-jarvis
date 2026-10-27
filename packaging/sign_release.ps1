# JARVIS GUI 发布签名 + SHA-256 清单 + VirusTotal 自查清单
#
# 用法（在仓库根目录，PowerShell 7；需要已导入的签名证书）：
#   # ① 导入 PFX 证书（一次性，或 CI 用 Base64 机密 + certutil）
#   Import-PfxCertificate -FilePath .\certs\ov-code.pfx -CertStoreLocation Cert:\CurrentUser\My -Password (ConvertTo-SecureString "pfx-password")
#   pwsh packaging\sign_release.ps1 -DistDir dist\jarvis-gui -Thumbprint <PFX 导入后的指纹>
#   pwsh packaging\sign_release.ps1 -DistDir dist\jarvis-gui -Pfx certs\ov-code.pfx -PfxPassword <env:JAVIS_SIGN_PFX_PASSWORD>
#
# 约定（spec 打包章节）：
# - 代码签名（OV/EV）根治杀软对 Nuitka bootloader 的误报；未签名发布须在发布页
#   附误报记录（packaging\README.md 表格）；
# - SHA-256 清单随发布物分发（release\sha256-{ver}.txt）；
# - VT 自查 = 上传 setup.exe + gui_main.exe（未签名/已签名各一次）并记录结果。
param(
    [Parameter(Mandatory)][string]$DistDir,
    [string]$Thumbprint = "",
    [string]$Pfx = "",
    [string]$PfxPassword = "",
    [string]$Version = "0.1.0",
    [string]$OutDir = "release"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Push-Location $repo
try {
    if (-not $Thumbprint -and $Pfx) {
        $pwd = if ($PfxPassword) { ConvertTo-SecureString $PfxPassword -AsPlainText -Force }
               else { Read-Host "PFX 密码" }
        $cert = Import-PfxCertificate -FilePath $Pfx -CertStoreLocation Cert:\CurrentUser\My -Password $pwd
        $Thumbprint = $cert.Thumbprint
    }
    if (-not $Thumbprint) { throw "需要 -Thumbprint 或 -Pfx（签名证书）" }

    # ① 逐文件签名（exe/dll/pyd；资源文件免签）
    $files = Get-ChildItem $DistDir -Recurse -File -Include *.exe, *.dll, *.pyd
    $i = 0
    foreach ($f in $files) {
        $i++
        Write-Host ("[{0}/{1}] 签名 {2}" -f $i, $files.Count, $f.FullName)
        & signtool sign /fd SHA256 /sha1 $Thumbprint /t http://timestamp.digicert.com $f.FullName
        if ($LASTEXITCODE -ne 0) { throw "签名失败：$($f.FullName)" }
    }
    Write-Host "验证全部签名…"
    foreach ($f in $files) {
        & signtool verify /pa /v $f.FullName | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "验签失败：$($f.FullName)" }
    }

    # ② SHA-256 清单
    New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    $manifest = Join-Path $OutDir "sha256-$Version.txt"
    Get-ChildItem $DistDir -Recurse -File | ForEach-Object {
        $h = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
        $rel = $_.FullName.Substring((Resolve-Path $DistDir).Path.Length + 1)
        "{0}  {1}" -f $h, $rel
    } | Sort-Object | Out-File $manifest -Encoding ascii
    Write-Host "SHA-256 清单 → $manifest"

    # ③ VirusTotal 自查清单（人工步骤，结果记录进 packaging\README.md 误报表）
    @"

=== VT 自查清单（发版前人工执行）===
1. 上传 $OutDir\sha256-$Version.txt 对应的 setup.exe（签名后）到
   https://www.virustotal.com 并截图留存（误报厂商名单进 README 误报表）；
2. gui_main.exe 同样上传一次（bootloader 误报高发项）；
3. 若 OV 签名仍被误报：记录厂商 + 日期 + 处置（申诉 / 用户说明页），
   EV 签名发版前必须 VT 零误报。
"@ | Out-File (Join-Path $OutDir "vt-checklist.txt") -Encoding utf8
    Write-Host "完成。误报记录模板见 packaging\README.md"
}
finally {
    Pop-Location
}
