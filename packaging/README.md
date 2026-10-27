# JARVIS GUI 打包发布（Nuitka onedir + Inno Setup + 代码签名）

工单 13 交付物。流程：构建 → 签名 → 安装包 → 发布自查。所有脚本在 `packaging/`，
在**仓库根目录**用 PowerShell 7 执行。

## 1. 构建（Nuitka onedir）

```powershell
pwsh packaging\build_gui.ps1                 # 默认 python
pwsh packaging\build_gui.ps1 -Python D:\python_env\python.exe
```

- 产物 `dist\jarvis-gui\`（exe + Qt DLL + 模块同目录，LGPL 动态共存形态）；
- 基础 venv **不含 chromadb**（遗留 c：可选依赖降级；需要 RAG 的开发机 `pip install -e ".[rag]"`）；
- 每次构建刷新 `packaging\runtime-info.txt`（体积基线；启动时间人工冒烟后补录）；
- C 扩展编译缓存 `.build\nuitka-cache`（CI 复用后增量构建秒级）。

体积/启动基线（记录于 runtime-info.txt，发布时引用）：

| 版本 | 大小 | 启动（首启向导出现） | 备注 |
| ---- | ---- | ---- | ---- |
| 0.1.0 | 待构建 | 待冒烟 | 首版 |

## 2. 代码签名

```powershell
pwsh packaging\sign_release.ps1 -DistDir dist\jarvis-gui -Pfx certs\ov-code.pfx -PfxPassword $env:JAVIS_SIGN_PFX_PASSWORD
```

- 逐文件 `signtool sign`（exe/dll/pyd）+ 时间戳（digicert）+ 全量 `signtool verify`；
- 输出 `release\sha256-<ver>.txt`（SHA-256 清单，随发布物分发）与 `release\vt-checklist.txt`。

### 杀软误报记录（发布页同步）

| 日期 | 版本 | 签名 | 厂商 | 误报项 | 处置 |
| ---- | ---- | ---- | ---- | ---- | ---- |
| （示例） | 0.1.0 | OV | （记录） | （记录） | 申诉链接 / 用户说明 |

未签名构建默认会被部分杀软误报（PyInstaller/Nuitka bootloader 先例）——**对外分发一律
带签名 + VT 自查零误报（EV）/ 记录误报（OV）**。

## 3. Inno Setup 安装包

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" packaging\setup.iss
# 产物 packaging\output\Jarvis-0.1.0-setup.exe
```

设计约定（`setup.iss` 内注释）：

- 安装目录 `{autopf}\Jarvis`（Program Files，**只读**）——应用全部用户写入走
  `%APPDATA%\Jarvis` 与 `.jarvis`（JARVIS_HOME 可改），**升级/重装不覆盖用户数据**；
- 卸载默认保留用户数据；勾选「删除用户数据」任务才清理 `%APPDATA%\Jarvis` 与
  默认 `.jarvis`（JARVIS_HOME 自定义路径不在清理范围）；
- `CloseApplications=yes` 安装前关闭运行中实例（防文件锁）。

## 4. 干净机冒烟（工单 14 配合项）

1. 安装 `Jarvis-<ver>-setup.exe` → 首启 → 向导 5 步配网关（或 .env）→ 对话一轮；
2. 再装一次同版本（升级路径）→ 验证 `%APPDATA%\Jarvis` 与 `.jarvis` 数据保留；
3. 卸载（勾选清理）→ 确认安装目录移除、用户数据删除；
4. 启动时间实测补录 `packaging\runtime-info.txt`。

## 5. CI（缓存 C 扩展产物）

GitHub Actions 缓存 `.build/nuitka-cache/`（key 按 Python 版本 + Nuitka 版本）：

```yaml
- uses: actions/cache@v4
  with:
    path: .build/nuitka-cache
    key: nuitka-${{ matrix.python }}-${{ hashFiles('requirements.txt') }}
```

Windows runner 需 `msvc` 工具集（`-Install` 或 `mingw` 之外的 MSVC 链接器，
`Visual Studio Build Tools 2022` 默认具备）。

## LGPL 合规（Qt）

onedir 产物 = Qt DLL 与 exe **同目录动态链接**：用户可自行替换 Qt DLL（动态链接
形态不构成 LGPL 的静态链接源提供义务），发布页附「如何替换 Qt DLL」说明与
PySide6 版本号即可。
