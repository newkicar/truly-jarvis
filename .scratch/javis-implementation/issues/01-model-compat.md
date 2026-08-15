# 01-模型接入验证

`Type: research`  `Status: resolved`  `Blocked by:`

## Question

验证 `langchain-openai` 的 `ChatOpenAI` 能否通过 OpenAI 兼容端点 `opencode.ai/zen/v1`（模型 `deepseek-v4-flash`）驱动 deepagents 0.7.x，包括：
1. 基本对话调用成功
2. **tool calling** 可用（deepagents 依赖工具调用；模型不支持则整个方案不成立）
3. deepseek-v4-flash 是否支持结构化输出（`response_format`，供动态子代理 `responseSchema` 用）
4. 记录实测的 base_url / model / 温度等参数组合

预期产出：一段可复现的最小验证脚本的结论 + 任何兼容性坑。若 tool calling 不可用，立即在票内报告并标记「阻塞一期」。

## Resolution

由 `/research` 子代理实测完成（findings：`../research/01-model-compat-findings.md`）。

- **基础对话** ✅
- **Tool calling** ✅（`bind_tools` 正常发出 tool_calls，参数解析正确）——不阻塞一期
- **结构化输出** ✅（`with_structured_output(pydantic)` 与 `response_format=json_object` 均通过）
- **可用参数组合**：`ChatOpenAI(openai_api_base="https://opencode.ai/zen/v1", api_key=..., model="deepseek-v4-flash")`，模型名不加前缀
- ⚠️ **关键阻塞**：该 workspace API **余额为 0**（`401 CreditsError: Insufficient balance`）。充值前付费 `deepseek-v4-flash` 跑不起来。
- **兜底**：同一 key 可用 `deepseek-v4-flash-free`（tool calling + 结构化输出都支持），但速率限制极严（几次即 429，冷却 5 分钟+），仅适合冒烟测试。
- **坑**：`.env` 的 `:` 分隔格式 `python-dotenv` 读不了，需自定义解析；响应带非标准 `reasoning_content` 字段但 openai 客户端正常容错。
