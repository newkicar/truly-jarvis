---
id: T-003
title: 桌面用户自配 LLM 端点/密钥先例
labels: [wayfinder:research]
status: done
assignee: uida0712
blocked_by: []
---

# T-003 · 桌面用户自配 LLM 端点/密钥先例 [wayfinder:research]

## Question
桌面 app "用户自配 LLM" 的最佳实践：
- 配置位置惯例：%APPDATA% vs .env vs 随包 json（单机多用户、升级不覆盖用户配置）
- 密钥存储：Windows DPAPI / Credential Manager / 系统钥匙串 vs 明文
- OpenAI 兼容端点探测：/models 探测、连通性测试的 UX
- 多 provider 切换、默认模型选择
- 首次启动向导（first-run wizard）

## 须调研先例
LM Studio / Chatbox / Jan / AnythingLLM / Continue

## 红线
- 先搜 GitHub 找先例，严禁闭门造车。

## 输出
- 最佳实践总结 + 推荐配置 schema（对照本仓 .env / jarvis.json 现状）→ .scratch/research/T-003-llm-config.md
- 完成后：本票 status → done，同步 map.md
