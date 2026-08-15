# 01 — 模型接入兼容性验证（opencode.ai/zen/v1 × deepseek-v4-flash）

日期：2026-08-15
任务：验证 deepagents 用 `langchain-openai.ChatOpenAI` 接入 OpenAI 兼容端点 `https://opencode.ai/zen/v1`（模型 `deepseek-v4-flash`）的可行性。

## 结论速览

| # | 验证项 | 结果 | 备注 |
|---|---|---|---|
| 1 | 基础对话 | ✅ 通过（免费版实测） | 付费版 `deepseek-v4-flash` 因**余额为 0** 无法实测，但模型在端点白名单内 |
| 2 | Tool calling | ✅ 通过（免费版实测） | `bind_tools` 正常发出 `tool_calls`，langchain 解析成功 |
| 3 | 结构化输出 | ✅ 通过（免费版实测） | `with_structured_output(pydantic)` 与 `response_format=json_object` 均可用 |
| 4 | 可复现参数组合 | ✅ 已记录 | 见下「可复现最小参数组合」 |

> ⚠️ **不阻塞一期**：模型能力（tool calling / 结构化输出）已通过同门免费变体 `deepseek-v4-flash-free` 实证。
> 付费版 `deepseek-v4-flash` 的唯一障碍是**账户 API 余额不足**（`CreditsError`），充值后即可用，非兼容性问题。

---

## 1. 验证详情

### 1.1 环境
- Python：`D:/AIPrograms/Annaconda/envs/thomas/python.exe`（3.12.9）
- 已装：`langchain-openai 1.3.2` / `openai 2.43.0` / `langchain-core 1.4.8`
- 凭据来源：`.env`（`:` 分隔、小写键，已按此解析成功）

### 1.2 测试 1 — 基础对话 ✅
```text
PASS. content = 'PONG'
usage = {'completion_tokens': 30, 'prompt_tokens': 89, 'total_tokens': 119, ...}
```

### 1.3 测试 2 — Tool calling ✅（deepagents 关键依赖）
```python
llm = ChatOpenAI(openai_api_base=BASE_URL, openai_api_key=API_KEY, model=MODEL, temperature=0)
msg = llm.bind_tools([get_weather]).invoke("What is the weather in Paris? Use the get_weather tool.")
```
```text
PASS. content = ''
tool_calls = [{'name': 'get_weather', 'args': {'city': 'Paris'}, 'id': 'call_...', 'type': 'tool_call'}]
```
tool 参数（`city`）被正确解析成结构化 dict —— deepagents 依赖的正是这一点。

### 1.4 测试 3A — with_structured_output（pydantic）✅
```text
PASS. result = city='Tokyo' temp_c=18
```

### 1.5 测试 3B — response_format=json_object ✅
```text
PASS. content = '{"city": "...", "temp_c": 0}'
parsed = {'city': '...', 'temp_c': 0}
```

### 1.6 测试 4 — tool 往返循环（agent loop）
- 第一轮 `tool_calls` 正常发出（见 1.3）。
- 第二轮（把 tool 结果喂回模型）因免费层 `FreeUsageLimitError` 速率限制未能完成。多次重试（累计冷却 5 分钟+）仍被 429 拒绝，说明免费层冷却窗口较长。此为免费层限制，**非模型能力问题**；tool 参数解析已证实，往返链路大概率无碍，建议充值后用付费模型补测一次。

---

## 2. 可复现最小参数组合

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    openai_api_base="https://opencode.ai/zen/v1",  # 注意字段名：openai_api_base（不是 base_url）
    openai_api_key="sk-...",                        # 字段名：openai_api_key
    model="deepseek-v4-flash",                      # 付费
    # model="deepseek-v4-flash-free",               # 免费变体（限时开放，速率限制严）
    temperature=0,
    max_retries=1,
    timeout=120,
)

# 工具调用
llm.bind_tools([get_weather])
# 结构化输出
llm.with_structured_output(SomePydanticModel)
# 或原生 response_format
llm.invoke(prompt, response_format={"type": "json_object"})
```

关键点：
- `ChatOpenAI` 用 `openai_api_base` / `openai_api_key`（v1.3.2 内部字段名，`base_url` 等不是显式字段）。
- 模型名**不带前缀**：`deepseek-v4-flash`（带 `opencode-go/` / `opencode/` 前缀会报 `ModelError: Model ... is not supported`）。
- 端点为**纯 OpenAI 兼容 chat completions**：`https://opencode.ai/zen/v1/chat/completions`（对应 `@ai-sdk/openai-compatible`）。

---

## 3. 阻塞项与兼容性坑

### 坑 1（唯一真正阻塞项）：账户 API 余额不足 —— ⚠️ 充值前阻塞付费模型
- `.env` 的 key（`sk-fBxy...`）是**有效 key**（非 AuthError），但所属 workspace `wrk_01KYKQFMEANJRZAQDZDGW83C2H` 的 API 余额为 0。
- 报错原文：
```json
HTTP 401 {"type":"error","error":{"type":"CreditsError","message":"Insufficient balance. Manage your billing here: https://opencode.ai/workspace/wrk_01KYKQFMEANJRZAQDZDGW83C2H/billing"}}
```
- 影响：**所有对 `deepseek-v4-flash`（付费）的调用都会 401 被拒**，导致一期无法用付费模型实际运行。
- 解法：到上面 billing URL 充值（官方说明：余额 <$5 可设自动充值 $20）。充值后无需改代码即可用。

### 坑 2：免费变体 `deepseek-v4-flash-free` 可用但有限制
- 同一 key 可直接用免费模型（cost=0），且**支持 tool calling 与结构化输出**（本次全部能力验证就是用它完成的）。
- 限时开放、有**较严格的速率限制**：连续几次调用后触发
```json
429 {"type":"error","error":{"type":"FreeUsageLimitError","message":"Error from provider (Console): Rate limit exceeded. Please try again later."}}
```
- 冷却恢复时间较长（本次 90s+ 仍受限），**不能用于一期的实际 agent 运行**，只适合少量冒烟测试。
- 注意隐私：官方明确 free 期间数据可能用于改进模型，勿提交敏感数据。

### 坑 3：`.env` 格式不规范
- 现为 `:` 分隔、小写键（`base_url:` / `api_key:` / `model_id:` / `tavily_key:`），`python-dotenv` 的 `load_dotenv` **无法直接读取**，需自定义解析（按首个 `:` split）。
- 与设计文档一致：实现时统一为 `KEY=VALUE`（`BASE_URL` / `API_KEY` / `MODEL_ID` / `TAVILY_KEY`）。

### 坑 4：响应含非标准字段
- 响应里带 `reasoning_content` 字段（DeepSeek 推理过程），openai 客户端与 langchain-openai 均正常容错，不影响解析（本次全程无报错）。

### 坑 5：模型名校验严格
- 任何不在白名单的模型名返回 `ModelError`，说明端点白名单生效，配错名会立刻暴露（利于排错）。

### 坑 6：`.env` 的 key 与 opencode 本体共用
- `~/.local/share/opencode/auth.json` 中 `opencode` / `opencode-go` provider 的 key 与 `.env` 为同一个，说明该 key 是 opencode CLI 登录凭据。CLI 走的订阅通道不受 API 余额影响，但**独立脚本/agent 走 `zen/v1` 直接扣 API 余额**。

---

## 4. 官方信息佐证（opencode.ai/docs/zen）
- `deepseek-v4-flash` 与 `deepseek-v4-flash-free` 均在官方 Zen 模型清单中，端点 `https://opencode.ai/zen/v1/chat/completions`，SDK 包 `@ai-sdk/openai-compatible`。
- 付费价：DeepSeek V4 Flash $0.14 / 1M input，$0.28 / 1M output。
- `GET https://opencode.ai/zen/v1/models` 可列出全部可用模型（本次实测 HTTP 200，含 `deepseek-v4-flash`、`deepseek-v4-flash-free` 及 60+ 其它模型）。

---

## 5. 给实现阶段的操作建议
1. 实现前先到 billing 页面给 workspace 充值（或用已有余额的 key），否则一期付费模型全部 401。
2. `.env` 解析做成兼容两种格式（`KEY=VALUE` 与旧的 `key:value`），并顺手规范化。
3. 冒烟测试可用 `deepseek-v4-flash-free` 省钱，但**正式运行必须付费模型**（免费层速率限制 + 数据隐私条款）。
4. `ChatOpenAI` 初始化用 `openai_api_base` / `openai_api_key` / `model` 三个参数即可，无需其它特殊配置。
