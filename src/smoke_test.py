"""真实模型端到端冒烟脚本（手动运行，不进 CI，消耗额度）。

用法: python -m src.smoke_test <调研问题>
验证: 路由 → researcher 委派 → 本地 WIKI 检索 + Tavily 搜索 → 带来源结构化总结。

依赖真实 go 套餐模型（.env），非确定性、耗时、耗额度，仅手动触发。
"""
import sys

from langgraph.checkpoint.sqlite import SqliteSaver

from src.agent import build_agent
from src.config import ensure_utf8_stdout, load_config

ensure_utf8_stdout()


def main() -> int:
    if len(sys.argv) < 2:
        question = "调研大模型行业最新动态，重点关注开源模型进展"
    else:
        question = sys.argv[1]

    config = load_config()
    with SqliteSaver.from_conn_string(str(config.checkpoint_db)) as checkpointer:
        agent = build_agent(config, checkpointer=checkpointer)
        print(f"\n=== 提问: {question} ===\n")
        result = agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config={"configurable": {"thread_id": "smoke"}, "recursion_limit": 30},
        )
        for msg in result["messages"]:
            if msg.type == "ai":
                print(msg.content)
        print("\n=== 冒烟完成 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())