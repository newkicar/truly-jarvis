# 13 — 打包与签名（Nuitka onedir + Inno Setup + 代码签名）

**What to build:** 可分发的单机 exe（遗留 c/d 能力完整）：Nuitka **onedir**（单文件不推荐——启动慢）目录 + Inno Setup 安装包；依赖钉 PySide6-Essentials（不带 Addons/WebEngine，原型实证）；代码签名（OV/EV）根治杀软误报（PyInstaller bootloader 误报先例），发布附 SHA-256 + VirusTotal 自查流程；Qt DLL 与 exe 同目录动态共存（LGPL 规避静态链接义务）；CI 缓存 C 扩展编译产物（Nuitka 分钟级编译）；安装目录只读安全（首启全部写入走 %APPDATA% / .jarvis，不碰安装目录）。

**Blocked by:** 02（LLM 自配层）、08（高级模式与撤回）、09（时间旅行与上下文）、10（命令体系与补全）、11（记忆目录对齐）、12（可选依赖降级与自检页）

**Status:** done（2026-10-27 脚本/清单交付；构建机实跑与签名证书 = 工单 14 外部项）

- [x] Nuitka onedir 构建脚本（packaging/build_gui.ps1，--standalone+pyside6 插件+cache-dir，基线写 runtime-info.txt）；产物实跑/启动时间 = 工单 14 构建机冒烟
- [x] Inno 脚本（packaging/setup.iss：{autopf}\Jarvis 只读安装、[Files] 零用户数据写入、opt-in 清理任务、CloseApplications）；ISCC 实跑 = 工单 14
- [x] 签名脚本（packaging/sign_release.ps1：逐文件 signtool sign+verify、SHA-256 清单、VT 自查清单模板）+ README 误报表；证书/VT 实跑 = 工单 14
- [x] 冒烟清单入 packaging/README.md §4（配合工单 14 执行）；另：chromadb 移出基础依赖改 [rag] 可选组（遗留 c 落地）
