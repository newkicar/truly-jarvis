# 04 jarvis 命令不可用 = PATH/终端陈旧（非代码 bug）

排查结论（2026-10-24，HEAD b0728a2 实证）：
- pyproject.toml [project.scripts] jarvis = "src.main:main" 存在；
  setuptools 已生成 Scripts\jarvis.exe（simple_launcher shim，内嵌 shebang 正确指向解释器）。
- where.exe jarvis 命中 Scripts\jarvis.exe，该目录在 PATH；python -m jarvis 可拉起 TUI。
- 用户现象 = 终端在 pip install 前打开 / 未激活 venv / 系统 PATH 陈旧。

处置（报告 + 文档，零代码）：
- [x] README 快速启动区补故障排查说明：
  jarvis 命令找不到 → 开新终端（PATH 未刷新）/ 激活 venv / 仍不行用 python -m jarvis。
