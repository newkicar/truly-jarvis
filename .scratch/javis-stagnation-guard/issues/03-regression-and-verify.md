# 03: 长春天气回归用例 + 批量验证 + 提交

**What to build:**
- 追加 tests/test_resilience.py 长春天气回归用例：用报告里的逐词膨胀 quick_search 序列（>=7 条），
  断言第 4 次总调用含软引导、第 7 次总调用被硬熔断（handler 不执行）。
- 批量验证：& D:\python_env\python.exe -m pytest tests/test_resilience.py -q 全绿（只跑本文件批）。
- 若 import 面被触碰，快速 sanity 跑 tests/test_permissions.py tests/test_tui.py。
- 提交（中文 conventional）：feat(resilience): 停滞防御 StagnationGuardMiddleware——
  近似成功循环两级处置（3 软引导 / 6 硬熔断）+ thread 级隔离 + 主代理/researcher 接桩 + harness 搜索停滞铁律

**Blocked by:** 01, 02。

**Status:** done

- [ ] 长春天气回归用例通过（软/硬阈值落点与算法一致）
- [ ] test_resilience.py 批量全绿，无新增失败
- [ ] 已提交
