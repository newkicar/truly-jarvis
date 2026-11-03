JARVIS GUI 便携版 · 使用说明

版本 0.1.0 · Windows x64 · 免安装（解压即运行）

一、系统要求
- Windows 10 / 11（64 位）
- 无需安装 Python，无需额外运行库（.NET 4.7.2+ 系统自带；
  Qt 以 DLL 动态链接形态随包分发，与 exe 同文件夹）
- 需要可访问 LLM 网关的网络环境（首次启动时配置）

二、快速开始（首次使用约 5 分钟）
1. 解压 zip 到任意目录（路径可含中文/空格，不建议放 U 盘根目录）；
   解压后得到一个 jarvis-gui\ 文件夹（平铺布局，全部同级）：
       jarvis-gui\
           jarvis-gui.exe     主程序
           skills\            内置 skills（首启播种用）
           *.dll              Qt 等运行库
           使用说明.md
           LICENSE.txt
   请保持该文件夹内部结构完整，不要增删/移动其中文件。
2. 双击 jarvis-gui\jarvis-gui.exe。首启会出现 5 步「配置 LLM 端点」向导：
       ① 欢迎与安全承诺（可跳过）
       ② 选择 provider（OpenAI 兼容 / 本地推理等；本地推理 Key 填 sk-no-key 占位）
       ③ 填写 网关地址（BASE_URL）与 API Key
       ④ 测试连接（向导发起一次真实探测）
       ⑤ 选择默认模型（如 mimo-v2.5）
   完成后进入主界面，发起一轮对话即验证成功。
3. 跳过向导也可以：把 .env 放到项目目录后重启（开发机姿势；便携用户一般直接用向导）。

三、便携使用规则（务必遵守）
- jarvis-gui.exe 与 skills\、各 DLL 必须保持同级，不要单独移动/重命名/拆分；
- 不要向 jarvis-gui\ 文件夹内添加、修改、删除文件（内置 skills 在 skills\，
  首启时会复制到用户目录）；
- 整夹可随意移动/拷贝/放移动硬盘——程序对位置不敏感（安装目录零写入）。

四、数据在哪里（应用目录零写入）
- 用户配置与密钥：%APPDATA%\Jarvis\（config.json + secrets\）
- 用户全局目录：~\.jarvis\（jarvis.json、全局 skills（首启自动从随包内置 skills 播种）、
  记忆 memory\、AGENTS.md 全局指令（legacy JARVIS.md 回落））
- 首次在新目录运行会自举创建项目骨架（jarvis.json 等）
- 可用环境变量 JARVIS_HOME 覆盖用户全局目录位置（调试/多实例）

五、能力说明
- 对话 / 工具调用 / 子代理 / 权限审批（HITL）：开箱即用；
- 内置 skills（docx / pdf / pptx / xlsx / web-research / vault-nav 等）随包播种到
  ~\.jarvis\skills。其中 Office 文档类 skills 依赖本机 Python 与第三方库
  （python-docx / python-pptx / openpyxl / pypdf / pdfplumber），
  本机没装这些库时相应 skill 会温和降级提示，其余功能不受影响；
- 语义检索（RAG）：本便携包不含 chromadb（可选依赖），
  语义搜索自动回落 grep/wiki 导航式检索，不影响使用；
- 构建环境已移除 Google GenAI 传递依赖链（deepagents 惰性可选依赖，规避 MSVC C1002）：
  便携版网关若配置 Google 系模型不可用（OpenAI 兼容 / 本地推理不受影响）；
- JS 代码解释器（langchain_quickjs / wasmtime）已剥离：便携版不含该工具；
  源码形态（CLI/TUI 开发环境）仍可用。
- 定时任务：GUI 默认不启动 scheduler（需要时用 CLI/TUI 源码形态）。

六、TUI / CLI 不在便携包内
- 便携包只含 GUI（Nuitka 入口 src\gui_main.py 的可达图）；
  终端形态请用 git 源码：git clone → 建 venv → pip install -e . →
  python -m src.main（默认 TUI，加 --cli 为纯 CLI）。

七、安全与分发注意
- 本包未做代码签名：
  · 首次运行可能触发 Windows SmartScreen「未知发布者」→ 点「更多信息 → 仍要运行」；
  · 部分杀软对 Nuitka onedir 的 bootloader 有已知误报先例；
    下载后请用 SHA-256 校验（release 随包附 sha256-*.txt）：
      certutil -hashfile jarvis-gui-0.1.0-win-x64-portable.zip SHA256
    与 txt 中哈希一致即可信；
- Qt LGPL 说明：Qt DLL 与 exe 同目录为动态链接形态；如需替换 Qt DLL，
  在与 exe 同级目录下替换同名 DLL 即可（随包 PySide6 版本号以
  packaging\runtime-info 记录为准），源码可从 PySide6 wheel 获取。

八、排查
- 双击无反应/黑窗不出现：本包按 --windows-console-mode=disable 构建，
  日志不显示。手动开 cmd 运行 jarvis-gui\jarvis-gui.exe 查看输出；
- 向导后无法对话：确认 ④ 测试连接通过、模型名精确（不加厂商前缀）；
- 配置丢失：%APPDATA%\Jarvis\ 被清理会回到首启向导（重新走一遍即可）。
