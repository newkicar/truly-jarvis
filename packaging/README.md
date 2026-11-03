# JARVIS GUI 打包发布（Nuitka onedir 便携包；Inno 安装包/签名 = 后续工单）

流程：构建便携包 → （可选）签名 → 发布。所有脚本在 `packaging/`，在**仓库根目录**用
PowerShell 7 执行。当前发布形态 = **便携 zip**（免安装）；`setup.iss`（工单 13，仍指向旧
`gui_main.exe` 单文件命名）暂缓，随签名流程一并更新。

## 1. 构建（Nuitka onedir，扁平布局，GUI-only）

```powershell
pwsh packaging\build_gui.ps1                      # 默认 python
pwsh packaging\build_gui.ps1 -Python D:\python_env\python.exe
```

- **扁平布局（拍平）**：`dist\jarvis-gui\` = `jarvis-gui.exe` + DLL + `skills\` 等同级内容
  （脚本 [4/8] 将 Nuitka onedir 的 `gui_main.dist\` 整体平铺进 staging，目录内无嵌套 dist 层；frozen 形态 `install_root()` = exe 所在目录，见 `src\project_paths.py`）；
- **GUI-only**：`src\gui_main.py` 为入口，trace 可达图不含 TUI/CLI（`src.main` / `src.tui` /
  `src.smoke_test` / `jarvis` 包不入包）；`src.tui_log` 因引用 textual 保留（纯 Python，可接受）；
- **skills 随包**：`--include-data-dir=skills=skills` → Nuitka onedir `gui_main.dist\skills`，[4/8] 拍平后 `skills\` 与 exe 同级（首启 seed 到 `~\.jarvis\skills`）。注意 `skills/` 被 `.gitignore` 排除 → 干净克隆/CI 构建无内置 skill（脚本前置检查会 throw；CI 需另行决策把内置 skill 纳入版本控制）；
- 基础 venv `.build\venv-base` **不含 chromadb**（可选依赖降级；RAG 缺失自动回落 grep/wiki）；
- 每次构建刷新 `packaging\runtime-info.txt`（体积基线；启动时间人工冒烟后补录）；
- C 扩展编译缓存 `.build\nuitka-cache`（CI 复用后增量构建秒级）。

### 便携 zip + SHA-256（GitHub release 附件）

构建完成后自动产出（`-SkipZip` 可跳过）：

- `release\jarvis-gui-<ver>-win-x64-portable.zip`
  内容 = `jarvis-gui` 单夹（`jarvis-gui.exe` + DLL/数据同级平铺 + `使用说明.md`（源自 `packaging\README-portable.md`）+ `LICENSE.txt`）；
- `release\sha256-jarvis-gui-<ver>-win-x64-portable.txt`（`<hash>  <zip>` 单行，随 release 分发）。

### 体积/启动基线

| 版本 | 大小 | 启动（首启向导出现） | 备注 |
| ---- | ---- | ---- | ---- |
| 0.1.0 | 465 MB（zip 158.9 MiB） | ≈17s | GUI-only 便携首版（平铺单夹） |

### 0.1.0 构建修复记录（v0.1.0 首版落定）

- (a) `src\gui_main.py`：PySide6 shiboken lazy re-export shim（frozen 形态下 shiboken 的延迟 re-export 缺失导致 import 失败）；
- (b) `src\agent.py`：`langchain_quickjs` stub 的 `except ImportError` 防护（quickjs/wasmtime 已 `--nofollow-import-to` 剔除出包）；
- (c) Nuitka 参数补 `--include-package=openai --include-package=anthropic`：PEP 562 惰性子模块不被 import 扫描发现，不显式 include 则运行时 ModuleNotFoundError；
- (d) `src\gui_main.py`：`overrides = None` 无条件绑定修复（原条件分支在 frozen 路径下未执行）；
- (e) `build_gui.ps1`：SHA 文件名正则 `-replace '\.zip$'` 后直接拼 `sha256-` 前缀（此前误留 `.zip.txt` 双后缀，与 release 规范名 `sha256-<ver>-win-x64-portable.txt` 不符）。

## 2. 代码签名（后续工单，暂缓）

```powershell
pwsh packaging\sign_release.ps1 -DistDir dist\jarvis-gui -Pfx certs\ov-code.pfx -PfxPassword $env:JAVIS_SIGN_PFX_PASSWORD
```

逐文件 `signtool sign` + 时间戳 + 全量 verify；未签名构建默认会被部分杀软误报
（Nuitka/PyInstaller bootloader 先例）——**对外分发最终态 = 带签名 + VT 自查**。

### 杀软误报记录（发布页同步）

| 日期 | 版本 | 签名 | 厂商 | 误报项 | 处置 |
| ---- | ---- | ---- | ---- | ---- | ---- |
| （示例） | 0.1.0 | 无 | （记录） | （记录） | SHA-256 校验 + 用户说明 |

## 3. 干净机冒烟（配合项）

1. 解压 zip → 双击 `jarvis-gui.exe` → 首启 5 步向导配网关（或项目 `.env`）→ 对话一轮；
2. 整夹移动到新目录再启动（便携性验证：`jarvis-gui` 单夹自包含，内部路径不依赖绝对位置）；
3. 确认 `%APPDATA%\Jarvis`、`~\.jarvis` 生成且应用目录零写入；
4. 启动时间实测补录 `packaging\runtime-info.txt`。

## 4. CI（缓存 C 扩展产物）

GitHub Actions 缓存 `.build/nuitka-cache/`（key 按 Python 版本 + Nuitka 版本）；Windows runner
需 MSVC 工具集（VS Build Tools 2022 默认具备）。CI 注意：`skills/` 未入仓库 → 内置 skill 缺失
（见 §1）。

## LGPL 合规（Qt）

扁平 onedir 产物 = Qt DLL 与 exe 同目录**动态链接**：用户可自行替换 Qt DLL（动态形态不
构成 LGPL 静态链接源提供义务），release 附「如何替换 Qt DLL」说明与 PySide6 版本号即可。
