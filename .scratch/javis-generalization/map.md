# JARVIS 泛化 — 决策摘要

`Status: done`（2026-08-20 收尾）

## 背景

用户提出三个关联问题：

1. **OpenCode 式项目根**：在哪运行，哪就是 `/workspace/`。  
2. **脱 Obsidian 化**：agent 是通用助手，`@` 不应默认全是 vault。  
3. **TUI 输入辅助**：`@` 弹建议但不挡输入；`/` 给命令建议。

## 决策（so far）

- 三问题共用一条线：**先正确解析 project_root，再改补全与交互**。  
- vault 保留为 `/vault/` 可选后端，不删 RAG/wiki/knowledge_keeper。  
- 补全：**Tab 接受，Enter 发送**（对标 IDE，非模态列表）。  
- 命令：`slash_completion.SLASH_COMMANDS` 注册表，与 `dispatch_command` 对齐。

## 票序与依赖

```
01 项目根发现 ✅
 └─► 02 配置路径分层 ✅
      └─► 03 workspace 全链路接入 ✅
           └─► 04 @ 补全泛化 ✅
                └─► 06 非阻塞交互 ✅
05 / 命令建议 ✅ ──► 06 非阻塞交互 ✅
03 + 06 ──► 07 文档 ADR ✅
```

## 交付

- ADR：[`docs/adr/0004-project-root-and-general-agent.md`](../../docs/adr/0004-project-root-and-general-agent.md)
- 单测：**202** 绿
- 关键模块：`project_paths.py`、`path_completion.py`、`slash_completion.py`、`tui_completion.py`
