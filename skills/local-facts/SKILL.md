---
name: local-facts
description: 本机环境事实：精确时间、命令输出、路径。用 execute（Get-Date 等），禁止 eval/CodeInterpreter 读环境。
---

# 本机事实

## 工具

- **execute**：PowerShell / shell 命令（Get-Date、curl、where、git status 等）。
- **不要**用 CodeInterpreter / eval 获取系统时间或环境变量。

## 示例

- 日期时间：`Get-Date -Format "yyyy-MM-dd HH:mm:ss"`
- 公网 IP（若允许）：`curl -s ifconfig.me` 或等价命令

## 注意

- 启动 prompt 只有「今天日期+星期」；精确时刻用 execute。
- 不读 `/memories/user-profile.md` 推断用户所在地。
