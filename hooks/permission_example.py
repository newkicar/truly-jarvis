"""示例 permission hook：按 execute 命令前缀返回 allow/deny/ask。

stdin: {"tool","args","path","thread_id","project_root"}
stdout: {"decision":"allow"|"deny"|"ask","message":"..."}
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    data = json.load(sys.stdin)
    path = str(data.get("path") or "")
    if path.startswith("git push"):
        print(json.dumps({"decision": "deny", "message": "git push 被项目 hook 拒绝"}))
        return 0
    if path.startswith("git status"):
        print(json.dumps({"decision": "allow"}))
        return 0
    print(json.dumps({"decision": "ask"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
