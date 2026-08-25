---
name: skill-sap-employee-roster-download
title: 操作鼠标和键盘下载SAP花名册
description: 本指南用于指导代理操作鼠标和键盘下载SAP花名册时，读取指定的文件、路径及参数
when_to_use: |
  当需要：
  - （模拟）操作键盘鼠标下载SAP花名册时
priority: high
instructions: |
  当用户请求下载 SAP 花名册时，按以下步骤处理：
  1. 从用户输入中提取动态参数（username、password、search_keyword）
  2. 这些参数都是必填的，如果用户未提供，需要向用户询问
  3. 将 skill_name 固定为 "skill-sap-employee-roster-download"
  4. 调用 execute_workflow 工具，传入 workflow_filename、skill_name 和 dynamic_params
---


## 提示词与文件名映射关系
**下表体现了用户的提示词对应的操作流程文件名称，你需要根据用户提供的信息，判断用户需要使用的流程文件，读取其名称，并在调用tool的时候将名称（带后缀）发送给tool**
| 提示词中关键词 | 操作流程文件名称         | skill文件路径                      |
| ------------ -| ---------------------- | ---------------------------------- |
| SAP, 花名册   | download_SAP_roster_workflow.xlsx | skill-sap-employee-roster-download |



## 动态参数定义

**重要说明**：
- 所有参数名使用花括号括起来，如 `{username}`
- 以下参数都是**必填参数**，用户必须提供，否则需要向用户询问
- `skill_name` 是固定值，不需要从用户输入提取

### 参数表

| 参数名 | 类型 | 默认值 | 说明 | 提取规则 |
|--------|------|--------|------|----------|
| `skill_name` | 固定值 | `skill-sap-employee-roster-download` | 技能目录名称 | 固定值，直接填入 |
| `{username}` | 字符串 | `uida0712` | SAP 登录用户名 | 未提及则使用默认值，用户提到"用户名是XXX"、"账号XXX"时提取 |
| `{password}` | 字符串 | `Ss@111222333` | SAP 登录密码 | 未提及则使用默认值，用户提到"密码是XXX"时提取 |



## 调用示例

### 示例 1：用户提供所有参数

**用户输入**：