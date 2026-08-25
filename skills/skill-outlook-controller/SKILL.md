---
name: skill-outlook-controller
description: 该 Skill 提供了对本地 Outlook 应用程序的自动化操作支持，包括读取邮件、发送邮件、处理会议邀请及回复邮件。当用户提到邮件管理、Outlook、发送邮件、读取邮件、安排会议、回复邮件等任务时，都应该使用此 Skill。即使只是简单地说"帮我查一下今天的邮件"或"给某人发个邮件"，也应该触发此 Skill。
---

## ️ 重要：路径格式（Windows 系统必读）

**路径规则**：
- ✅ 正确：`resources/skills_base/...` （无前导斜杠，相对路径）
- ❌ 错误：`/resources/skills_base/...` （前导斜杠在 Windows 下会被解析为 D:\resources\...）

**为什么？**
- Windows 系统中，前导 `/` 表示当前盘符的根目录（如 `D:\`）
- 正确格式是直接使用相对路径，Agent 的工作目录已自动设置为项目根目录

**示例对比**：
```bash
# ✅ 正确
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" send_email '{...}'

# ❌ 错误（会导致 D:\resources\... 路径不存在）
%PYTHON_PATH% "/resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" send_email '{...}'
```

---

## ⚠️ 重要：环境变量

本 Skill 使用 `%PYTHON_PATH%` 环境变量来执行 Python 脚本。

**配置方法**：
1. 在项目根目录的 `.env` 文件中配置 `PYTHON_PATH`
2. 示例：`PYTHON_PATH=D:\Anaconda\envs\thomas\python.exe`
3. Agent 启动时会自动加载 `.env` 并将 `PYTHON_PATH` 注入到执行环境中

**为什么使用环境变量？**
- ✅ 路径可配置，不硬编码
- ✅ 不同用户可以使用不同的 Python 环境
- ✅ 发布后用户可以通过修改 `.env` 自定义配置
- ✅ 避免代码中暴露个人路径信息

---

## ⚠️ 重要：超时时间配置

**所有读取操作（read_inbox / read_sent / read_meetings）执行时，Agent 会自动设置 timeout=300**

**为什么需要 300 秒超时？**
- 邮件内容较多时，COM 操作可能耗时较长
- 300 秒（5分钟）可避免正常操作因超时而失败

**发送操作**（send_email / send_meeting / reply_email）使用默认超时时间（120秒）足够。

---

## ⚠️ 重要：JSON 参数格式（必读）

```bash
# ✅ 正确格式（单引号包裹，内部引号用转义的双引号）
%PYTHON_PATH% "路径/outlook_cli.py" read_inbox '{"if_unread": true}'

# ❌ 错误格式（外层双引号 + 内部转义，反斜杠容易被 Markdown 渲染器丢失）
%PYTHON_PATH% "路径/outlook_cli.py" read_inbox "\{"if_unread": true}"
```

**为什么必须使用单引号包裹？**
- 在 Shell 中，单引号 `'...'` 内的内容会被原样传递，不会进行转义处理
- 外层双引号 `"..."` 内部的 `\"` 转义符容易被 Markdown 渲染器解析丢失
- 使用单引号包裹可以确保 `\"if_unread\"` 完整传递给 Python
- 脚本已内置参数合并逻辑，能自动修复被拆分的参数，但使用正确格式更可靠

## 可用操作

本 Skill 通过执行 Python 脚本提供以下功能。**所有操作都需要通过 `execute` 工具调用**。

### 1. 读取收件箱邮件

```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" read_inbox '{"if_unread": true}'
```

**必需参数**：
- 无（所有参数均为可选）

**可选参数**：
- `if_unread`: boolean - 是否只读未读邮件（默认 false）
- `from_email`: string - 发件人邮箱
- `to`: array - 收件人列表
- `cc`: array - 抄送列表
- `bcc`: array - 密送列表
- `subject`: string - 主题关键词
- `body`: string - 正文关键词
- `attachment`: string - 附件关键词
- `start_time`: string - 开始时间 YYYY-MM-DD HH:MM
- `end_time`: string - 结束时间 YYYY-MM-DD HH:MM

**返回**：
```json
{
  "success": true,
  "count": 5,
  "emails": [...]
}
```

### 2. 读取已发送邮件

```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" read_sent '{"start_time": "2024-01-01 08:00"}'
```

**必需参数**：
- 无（所有参数均为可选）

**可选参数**：
- `start_time`: string - 开始时间 YYYY-MM-DD HH:MM
- `end_time`: string - 结束时间 YYYY-MM-DD HH:MM
- `to`: array - 收件人列表
- `cc`: array - 抄送列表
- `bcc`: array - 密送列表
- `subject`: string - 主题关键词
- `body`: string - 正文关键词
- `attachment`: string - 附件关键词

**返回**：
```json
{
  "success": true,
  "count": 5,
  "emails": [...]
}
```

### 3. 发送邮件

```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" send_email '{"to": ["user@example.com"], "subject": "主题", "body": "内容"}'
```

**必需参数**：
- `to`: array - 收件人列表

**可选参数**：
- `subject`: string - 邮件主题
- `body`: string - 邮件正文
- `cc`: array - 抄送列表
- `bcc`: array - 密送列表
- `attachment`: string - 附件路径

### 4. 回复邮件

💡 **重要：必须先读取邮件获取 entry_id**

回复邮件时，必须使用邮件的 `entry_id`（全局唯一标识符）。`entry_id` 在读取邮件时会自动返回。

**标准流程**：
1. 先调用 `read_inbox` 或 `read_sent` 读取邮件
2. 从返回结果中获取目标邮件的 `entry_id`
   - 返回格式示例：`{"success": true, "count": 5, "emails": {"0": {"entry_id": "AQMkAAA...", "index": 1, "主题": "会议通知"}, "1": {...}}}`
   - 用户说"回复第 3 封" → 找到 `index=3` 的邮件 → 提取其 `entry_id`
3. 使用 `entry_id` 调用 `reply_email`

**完整示例**：

用户："回复第 3 封邮件，说'收到，谢谢'"

**步骤 1：先读取邮件**
```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" read_inbox '{"if_unread": false}'
```

返回：
```json
{
  "success": true,
  "count": 5,
  "emails": {
    "0": {"entry_id": "AQMkAAA...", "index": 1, "主题": "会议通知", "发件人": {...}},
    "1": {"entry_id": "AQMkBBB...", "index": 2, "主题": "工作报告", "发件人": {...}},
    "2": {"entry_id": "AQMkCCC...", "index": 3, "主题": "项目进度", "发件人": {...}},  ← 这是第 3 封
    "3": {"entry_id": "AQMkDDD...", "index": 4, "主题": "放假通知", "发件人": {...}},
    "4": {"entry_id": "AQMkEEE...", "index": 5, "主题": "培训安排", "发件人": {...}}
  }
}
```

**步骤 2：提取第 3 封邮件的 entry_id = `"AQMkCCC..."`**

**步骤 3：回复邮件**
```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" reply_email '{"entry_id": "AQMkCCC...", "body": "收到，谢谢"}'
```

⚠️ **常见错误**：
- ❌ 直接说"回复第 3 封"而不提供 entry_id
- ❌ 每次都要重新读取邮件（应该从之前的返回结果中获取 entry_id）
- ✅ 正确做法：记住之前读取的邮件列表，从中提取对应的 entry_id

**方式 1：直接传递参数（推荐）**
```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" reply_email '{"entry_id": "AQMkADYAA...", "body": "收到"}'
```

**必需参数**：
- `entry_id`: string - 邮件 EntryID（从读取邮件的返回结果中获取）
- `body`: string - 回复内容

**可选参数**：
- `reply_all`: boolean - 是否回复所有人（默认 false）
- `cc`: array - 额外抄送列表
- `bcc`: array - 额外密送列表
- `attachment`: string - 附件路径

**返回**：
```json
{
  "success": true,
  "message": "邮件回复成功"
}
```

### 5. 读取会议

```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" read_meetings '{"start_time": "2024-01-15 09:00"}'
```

**必需参数**：
- 无（所有参数均为可选，如果不提供则返回所有会议）

**可选参数**：
- `start_time`: string - 开始时间 YYYY-MM-DD HH:MM（或 YYYY-MM-DD）
- `end_time`: string - 结束时间 YYYY-MM-DD HH:MM（或 YYYY-MM-DD）
- `from_email`: string - 组织者邮箱
- `to`: array - 收件人列表
- `participants`: array - 参与者列表
- `meeting_room`: string - 会议室名称
- `subject`: string - 会议主题关键词
- `body`: string - 议程关键词
- `attachment`: string - 附件关键词

**返回**：
```json
{
  "success": true,
  "count": 3,
  "meetings": [...]
}
```

### 6. 发送会议邀请

```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" send_meeting '{"participants": ["user1@example.com"], "subject": "会议", "start_time": "2024-01-15 14:00", "end_time": "2024-01-15 15:00"}'
```

**必需参数**：
- `participants`: array - 参与者邮箱列表
- `start_time`: string - 开始时间 YYYY-MM-DD HH:MM
- `end_time`: string - 结束时间 YYYY-MM-DD HH:MM

**可选参数**：
- `subject`: string - 会议主题
- `body`: string - 会议议程
- `meeting_room`: string - 会议室名称/资源邮箱
- `attachment`: string - 附件路径

## 使用流程

当用户请求 Outlook 相关操作时：

1. **确定要执行的操作**（读取邮件/发送邮件/读取会议等）
2. **构建 JSON 参数字符串**
3. **执行对应的 Python 命令**
4. **解析返回的 JSON 结果**
5. **向用户展示结果**

## 示例场景

### 场景 1：读取所有未读邮件

用户说："读取所有未读邮件"

执行：
```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" read_inbox '{"if_unread": true}'
```

### 场景 2：发送邮件

用户说："给 li.shun@example.com 发送邮件，主题是你好，内容是你好啊"

执行：
```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" send_email '{"to": ["li.shun@example.com"], "subject": "你好", "body": "你好啊"}'
```

### 场景 3：回复第一封邮件

用户说："回复第一封邮件，说收到了"

**步骤 1：先读取邮件，获取 entry_id**
```bash
%PYTHON_PATH% "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" read_inbox '{"if_unread": true}'
```

返回结果示例：
```json
{
  "success": true,
  "emails": [
    {
      "entry_id": "AQMkADYAA...",
      "index": 1,
      "主题": "会议邀请",
      "发件人": {"姓名": "张三", "邮箱": "zhangsan@example.com"},
      ...
    }
  ]
}
```

**步骤 2：使用 entry_id 回复邮件**
```bash
python "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" reply_email '{"entry_id": "AQMkADYAA...", "body": "收到"}'
```

## 环境要求

- ✅ Windows 系统 + Outlook 客户端
- ✅ **Conda 环境**：必须激活 `thomas` 环境（`conda activate thomas`）
- ✅ 已安装 `pywin32`：`pip install pywin32`（在 thomas 环境中）
- ✅ 所有命令都会自动管理 COM 资源，无需手动清理

## ️ 依赖缺失处理指南

如果执行脚本时遇到 `ModuleNotFoundError`，说明当前 Python 环境缺少必需的第三方库。请按以下步骤处理：

### 步骤 1：识别缺失的库

从错误信息中提取缺失的模块名，例如：
- `ModuleNotFoundError: No module named 'pandas'` → 需要安装 `pandas`
- `ModuleNotFoundError: No module named 'win32com'` → 需要安装 `pywin32`
- `ModuleNotFoundError: No module named 'cv2'` → 需要安装 `opencv-python`

### 步骤 2：指导用户安装

**告知用户执行以下命令安装缺失的库**（确保在正确的 Python 环境中）：

```bash
# Outlook Skill 所需依赖
pip install pywin32

# GUI 自动化 Skill 所需依赖
pip install pandas opencv-python pyautogui pillow openpyxl

# 通用依赖
pip install numpy python-dotenv
```

### 步骤 3：验证安装

安装完成后，请用户验证：
```bash
%PYTHON_PATH% -c "import pandas; import cv2; import pyautogui; print('依赖检查通过')"
```

### 一键安装（推荐）

如果不确定需要哪些库，可以使用项目的 requirements.txt 批量安装：
```bash
pip install -r requirements.txt
```

##  邮件签名配置

**邮件签名文件位置**：项目根目录下的 `email_signiture.txt`

- Agent 在发送邮件时会自动读取此文件内容作为邮件签名
- 其他用户可以直接编辑此文件自定义签名内容
- 如果文件不存在或为空，发送邮件时不附加签名

## ⚠️ Python 依赖库安装指南

如果执行 Skill 脚本时遇到 `ModuleNotFoundError`，说明当前 Python 环境中缺少必需的第三方库。

**自动安装方法**：

当遇到依赖缺失时，请执行以下命令安装所需库：

```bash
# Outlook Skill 所需依赖
pip install pywin32

# GUI 自动化 Skill 所需依赖
pip install pandas opencv-python pyautogui pillow

# 通用依赖（如尚未安装）
pip install numpy python-dotenv
```

**批量安装（推荐）**：

如果不确定需要哪些库，可以使用项目的 `requirements.txt` 一键安装所有依赖：

```bash
pip install -r requirements.txt
```

**验证安装**：

```bash
python -c "import pandas; import cv2; import win32com.client; print('所有依赖已安装')"
```

**注意事项**：
- 确保在正确的 Python 环境中安装（即 `PYTHON_PATH` 指向的环境）
- 如果使用 Conda，也可以使用 `conda install` 安装部分库
- 安装完成后重新执行 Skill 操作

## Python 路径说明

**重要**：执行命令时必须使用完整的 Python 绝对路径，**JSON 参数优先使用单引号包裹**：

```bash
# 标准格式（推荐）
python "resources/skills_base/skill-outlook-controller/scripts/outlook_cli.py" <action> '{\"参数名\": 值}'
```

**不要使用**：
- ❌ `conda run -n thomas` （在 execute 工具中会非常慢，可能卡住）
- ❌ `conda activate` （在 execute 工具中不起作用）
- ❌ `where python` 查找路径
- ❌ 相对路径

**始终使用** `python`（确保 Python 已添加到系统 PATH 环境变量中）。

## 执行性能

✅ **使用 python 环境变量**：执行速度快（几秒钟），灵活可配置  
❌ **使用 conda run**：执行速度慢（可能卡住几分钟）

## ⚠️ 重要：JSON 参数格式（必读）

**推荐方式 1：直接传递 JSON 参数（单引号包裹 + 内部转义双引号）**

### 读取操作（必须设置 timeout=300）
- `read_inbox` - 读取收件箱邮件
- `read_sent` - 读取已发送邮件
- `read_meetings` - 读取会议邀请

**原因**：邮件内容较多时，COM 操作耗时较长，默认 300 秒

### 发送操作（无需特别设置）
- `send_email` - 发送邮件
- `send_meeting` - 发送会议邀请
- `reply_email` - 回复邮件

**原因**：发送操作简单快速，默认 120 秒足够

## 注意事项

1. **路径格式**：使用相对于项目根目录的路径
2. **JSON 转义**：在命令中传递 JSON 时注意引号转义
3. **日期格式**：日期用 `YYYY-MM-DD`，时间用 `YYYY-MM-DD HH:MM`
4. **审批机制**：由于使用 `execute` 工具，每次执行都需要用户批准（这是安全机制）
5. **超时设置**：读取操作自动使用 300 秒超时，发送操作使用默认 120 秒

## 故障排除

### 问题：JSON 解析失败

**错误信息**：
```
JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

**原因**：Shell 参数拆分或 JSON 格式不正确

**解决方法（2 种方案）**：

**方案 1：使用单引号包裹 + 内部转义双引号（推荐）**
```bash
# ✅ 正确（单引号包裹 + 内部转义双引号）
python "路径/outlook_cli.py" read_inbox '{\"if_unread\": true}'

# ❌ 错误（外层双引号 + 内部转义，反斜杠容易被 Markdown 或 Shell 丢失）
python "路径/outlook_cli.py" read_inbox "{\"if_unread\": true}"
```

**方案 2：查看 DEBUG 信息诊断问题**
- 脚本会输出详细的 DEBUG 信息到 stderr
- 查看 `DEBUG: received X args` 确认参数数量
- 查看 `DEBUG: merged args` 确认参数合并结果
- 查看 `DEBUG: extracted JSON` 确认提取的 JSON 字符串
- 根据 DEBUG 信息调整命令格式

**注意**：脚本已内置智能检测和自动修复逻辑，会按顺序尝试：
1. 检测是否为 JSON 文件路径
2. 暴力合并所有参数
3. 清理 Windows 转义字符
4. 提取 JSON 对象
5. 尝试修复格式问题

### 问题：无限循环执行相同命令

**症状**：Agent 反复执行相同的命令，每次都需要审批

**原因**：命令格式错误导致持续失败，Agent 不断重试

**解决方法**：
1. 检查命令格式是否正确（使用单引号包裹 JSON 参数）
2. 查看 stderr 中的 DEBUG 信息，确认参数是否正确传递
3. 如果已经连续失败 3 次以上，手动停止 Agent 并检查命令格式
4. 不要尝试修改脚本代码（代码已经包含完整的容错逻辑）

### 问题：COM 缓存权限错误

**错误信息**：
```
PermissionError: [WinError 5] 拒绝访问: 'C:\\Windows\\gen_py'
```

**原因**：pywin32 尝试在系统目录创建缓存

**解决方法**：脚本已自动处理此问题，无需手动干预。不要尝试执行 `mkdir C:\Windows\gen_py` 命令。