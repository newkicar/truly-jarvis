# Outlook Controller Skill

## 概述

这是一个 DeepAgents Skill，提供对本地 Outlook 应用程序的自动化操作支持。

## 目录结构

```
skill-outlook-controller/
├── SKILL.md                    # Skill 定义文档（Agent 读取）
├── README.md                   # 本文件（人类阅读）
└── scripts/
    ├── outlook_cli.py          # 命令行接口（Agent 通过 execute 调用）
    ├── outlook_service.py      # Outlook COM 接口封装
    ├── schemas.py              # Pydantic 数据模型（可选，供参考）
    └── tools.py                # LangChain @tool 定义（可选，供参考）
```

## 工作原理

1. **Agent 读取 SKILL.md**：了解可用的操作和命令格式
2. **Agent 构建命令**：根据用户需求构造 Python 命令和 JSON 参数
3. **Agent 执行命令**：通过 `execute` 工具运行 `python outlook_cli.py <action> <json>`
4. **解析结果**：CLI 返回 JSON 格式的结果，Agent 解析后展示给用户

## 可用操作

| 操作 | 命令示例 | 说明 |
|------|---------|------|
| read_inbox | `python "d:/.../outlook_cli.py" read_inbox '{"if_unread": true}'` | 读取收件箱邮件 |
| read_sent | `python "d:/.../outlook_cli.py" read_sent '{}'` | 读取已发送邮件 |
| send_email | `python "d:/.../outlook_cli.py" send_email '{"to": [...], "subject": "..."}'` | 发送邮件 |
| reply_email | `python "d:/.../outlook_cli.py" reply_email '{"entry_id": "...", "body": "..."}'` | 回复邮件（需先读取获取 entry_id） |
| read_meetings | `python "d:/.../outlook_cli.py" read_meetings '{}'` | 读取会议 |
| send_meeting | `python "d:/.../outlook_cli.py" send_meeting '{"participants": [...], ...}'` | 发送会议邀请 |

**注意**：确保 Python 已添加到系统 PATH 环境变量中。

## 环境要求

- Windows 操作系统
- Microsoft Outlook 客户端
- Python 3.8+
- pywin32: `pip install pywin32`

## 开发说明

### 添加新功能

1. 在 `outlook_service.py` 中实现业务逻辑
2. 在 `outlook_cli.py` 中添加对应的处理函数
3. 在 `actions` 字典中注册新操作
4. 更新 `SKILL.md` 文档

### 测试 CLI

```bash
# 查看帮助
python "d:/Python Project/Langchain练手/3_项目3_Javis_3.0/src/skills_base/skill-outlook-controller/scripts/outlook_cli.py"

# 测试读取未读邮件
python "d:/Python Project/Langchain练手/3_项目3_Javis_3.0/src/skills_base/skill-outlook-controller/scripts/outlook_cli.py" read_inbox "{\"if_unread\": true}"
```

**注意**：使用 `python` 命令而非 `conda run`，执行速度更快。

## 注意事项

- 所有路径都相对于项目根目录
- JSON 参数中的引号需要正确转义
- 每次执行都需要用户批准（安全机制）
- COM 资源会自动管理，无需手动清理

## 故障排除

### 问题：ModuleNotFoundError: No module named 'win32com'

**解决**：安装 pywin32
```bash
pip install pywin32
```

### 问题：Outlook 未启动

**解决**：确保 Outlook 客户端正在运行

### 问题：权限错误

**解决**：以管理员身份运行终端
