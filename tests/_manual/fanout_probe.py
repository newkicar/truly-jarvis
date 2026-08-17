"""批3-F 实测：deepseek-v4-flash 能否写 JS 做 fan-out。

最小 deep agent（真实模型 + researcher 子代理 + CodeInterpreterMiddleware），
提示模型"用 JS 规划并并行派发 2 个 researcher"；若模型产出可执行 JS 并触发
task() fan-out，说明具备动态子代理能力。

用法：python tests/_manual/fanout_probe.py
（需真实网络 + go 套餐模型，非单测，手动运行。）
"""
import json
import sys
import time

from langchain_quickjs import CodeInterpreterMiddleware

from src.agent import _make_model, _make_backend
from src.config import load_config
from src.subagents import build_researcher
from src.tools import make_deep_search_tool, make_quick_search_tool, make_search_tool

from deepagents import create_deep_agent


def main() -> int:
    config = load_config()
    model = _make_model(config)
    backend = _make_backend(config)
    search_tools = [
        make_quick_search_tool(config.tavily_key),
        make_search_tool(config.tavily_key),
        make_deep_search_tool(config.tavily_key),
    ]
    researcher = build_researcher(search_tools=search_tools)

    agent = create_deep_agent(
        model=model,
        backend=backend,
        subagents=[researcher],  # type: ignore[list-item]
        middleware=[CodeInterpreterMiddleware(subagents=True)],
        name="javis-probe",
        system_prompt=(
            "你是 fan-out 能力探针。对用户的研究请求：用 JS 编写一个小脚本，"
            "用内置 task() 全局并行派发 2 个 researcher 子代理研究两个不同角度，"
            "再把结果合并成一段总结返回。先写脚本并执行，不要直接串行回答。"
        ),
    )

    prompt = "用两个角度并行研究：2026 年国产 AI 大模型的两个动向（各自独立成角度）。"
    print(">> 提示:", prompt)
    t0 = time.time()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": prompt}]},
            config={"recursion_limit": 40},
        )
    except Exception as e:  # noqa: BLE001
        print("!! 调用异常:", type(e).__name__, str(e)[:500])
        return 2
    dt = time.time() - t0
    print(f">> 耗时 {dt:.1f}s")

    msgs = result["messages"]
    types = [getattr(m, "type", "?") for m in msgs]
    print(">> 消息类型序列:", types[:15])
    tool_calls = sum(1 for m in msgs if getattr(m, "type", "") == "tool")
    ai_texts = [m.content for m in msgs if getattr(m, "type", "") == "ai" and m.content]
    final = ai_texts[-1] if ai_texts else "(无文本)"
    print(">> 最终回答片段:", str(final)[:400].replace("\n", " "))

    # 判定：是否产出可执行 JS（tool 消息存在）且触发子代理
    print("\n== 判定 ==")
    print(f"  tool 调用数: {tool_calls}")
    js_ran = any(
        getattr(m, "type", "") == "tool"
        and getattr(m, "name", "") == "execute"
        and "js" in str(getattr(m, "content", "")).lower()
        for m in msgs
    )
    print(f"  是否有 execute JS 记录: {js_ran}")
    return 0 if (tool_calls > 0) else 1


if __name__ == "__main__":
    sys.exit(main())