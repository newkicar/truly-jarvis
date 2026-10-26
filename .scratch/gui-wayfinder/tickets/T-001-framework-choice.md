---
id: T-001
title: 原生 GUI 框架选型（Python/Windows）
labels: [wayfinder:research]
status: open
assignee: uida0712
blocked_by: []
---

# T-001 · 原生 GUI 框架选型（Python/Windows）[wayfinder:research]

## Question
Windows + Python 3.12 + deepagents 全家桶（替换 Textual TUI 的呈现层为原生 GUI），选哪个 UI 框架：
PySide6/Qt、Tkinter、Kivy、DearPyGui；
外加 C#/Rust 宿主 + Python 边界形态的可行性（py4j / 内嵌解释器 / 进程外 IPC）。

## 评估维度（须全覆盖）
1. 中文 IME 组合窗口支持（输入中文不丢字）
2. Markdown 流式渲染能力（增量追加，非全量重绘）
3. 鼠标拖选/复制、右键菜单
4. 单 exe 打包：体积、启动耗时、杀软误报风险（Nuitka / PyInstaller / cx_Freeze）
5. 社区成熟度、维护活跃度、Windows 平台质量
6. 与现有测试栈的契合（pytest-qt 等）

## 须调研先例（必覆盖）
LM Studio、Chatbox、Jan、AnythingLLM —— 它们的 GUI 技术栈选型与单文件打包方式。

## 红线
- 先搜 GitHub 找先例（AGENTS.md），严禁闭门造车；对库的最新能力拿不准时先查官方文档。

## 输出
- 对比表 + 推荐（含理由）
- 写入 .scratch/research/T-001-framework-choice.md
- 完成后：本票 status → done，结论写入 map.md 的 Decisions so far
