# 13 — 打包与签名（Nuitka onedir + Inno Setup + 代码签名）

**What to build:** 可分发的单机 exe（遗留 c/d 能力完整）：Nuitka **onedir**（单文件不推荐——启动慢）目录 + Inno Setup 安装包；依赖钉 PySide6-Essentials（不带 Addons/WebEngine，原型实证）；代码签名（OV/EV）根治杀软误报（PyInstaller bootloader 误报先例），发布附 SHA-256 + VirusTotal 自查流程；Qt DLL 与 exe 同目录动态共存（LGPL 规避静态链接义务）；CI 缓存 C 扩展编译产物（Nuitka 分钟级编译）；安装目录只读安全（首启全部写入走 %APPDATA% / .jarvis，不碰安装目录）。

**Blocked by:** 02（LLM 自配层）、08（高级模式与撤回）、09（时间旅行与上下文）、10（命令体系与补全）、11（记忆目录对齐）、12（可选依赖降级与自检页）

**Status:** ready-for-agent

- [ ] Nuitka onedir 产物可运行，体积/启动时间基线记录
- [ ] Inno Setup 安装包安装/卸载/升级（升级不覆盖 %APPDATA% 与 .jarvis 用户数据）
- [ ] 代码签名 + SHA-256 清单 + VT 自查通过（误报记录）
- [ ] 干净机安装→首启→配网关→对话 冒烟（配合 14）
