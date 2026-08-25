---
name: skill-apply-missing-punch
title: 操作鼠标和键盘申请补卡
description: 本指南用于指导代理操作鼠标和键盘申请补卡时，读取指定的文件、路径及参数
when_to_use: |
  当需要：
  - （模拟）操作键盘鼠标申请补卡时
priority: high
instructions: |
  当用户请求操作键盘鼠标申请补卡时，按以下步骤处理：
  1. 从用户输入中提取动态参数
  2. 如果用户未提供某个参数，使用该参数的默认值
  3. 将 skill_name 固定为 "skill-apply-missing-punch"
  4. 调用 execute_workflow 工具，传入 workflow_filename、skill_name 和 dynamic_params
---


## 提示词与文件名映射关系
**下表体现了用户的提示词对应的操作流程文件名称，你需要根据用户提供的信息，判断用户需要使用的流程文件，读取其名称，并在调用tool的时候将名称（带后缀）发送给tool**
| 提示词中关键词 | 操作流程文件名称 | skill文件路径 |
| -------------- | ---------------- | ------------- |
| 操作键盘鼠标，申请补卡 | 操作键盘鼠标申请补卡.xlsx | skill-apply-missing-punch |



## 动态参数定义

**重要说明**：
- 所有参数名使用花括号括起来，如 `{parameter_name}`
- 如果用户未提供参数值，**必须使用默认值**
- `skill_name` 是固定值，不需要从用户输入提取

### 参数表

| 参数名 | 类型 | 默认值 | 说明 | 提取规则 |
|--------|------|--------|------|----------|
| `skill_name` | 固定值 | `skill-apply-missing-punch` | 技能目录名称 | 固定值，直接填入 |
| `{user_id}` | 字符串 | `110430` | 工号 | 用户提到"工号XXXXXX"时提取；未提供时使用默认值 |
| `{punch_date}` | 字符串 | `2026-05-18` | 忘打卡日期 | 用户提到"日期是：xxxxx"时提取；未提供时使用默认值 |
| `{punch_time}` | 字符串 | `08:25` | 忘打卡时间 | 用户提到"时间是xxxx"时提取；未提供时使用默认值 |
| `{reason}` | 字符串 | `上班忘记打卡，感谢领导批准。` | 原因说明 | 用户提到"原因是xxxxx"时提取；未提供时使用默认值 |




## 调用示例

### 示例 1：用户提供所有参数

**用户输入**：请帮我New Skill，参数都已提供

**参数提取结果**：
```json
{
  "workflow_filename": "操作键盘鼠标申请补卡.xlsx",
  "skill_name": "skill-apply-missing-punch",
  "dynamic_params": {
    "skill_name": "skill-apply-missing-punch",
  }
}
```

### 示例 2：使用默认参数

**用户输入**：请帮我操作键盘鼠标申请补卡

**参数提取结果**：
```json
{
  "workflow_filename": "操作键盘鼠标申请补卡.xlsx",
  "skill_name": "skill-apply-missing-punch",
  "dynamic_params": {
    "skill_name": "skill-apply-missing-punch",
  }
}
```
