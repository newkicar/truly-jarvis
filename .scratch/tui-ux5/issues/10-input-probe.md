# 10 — 输入通道探测（input_probe + /doctor 诊断行）

**What to build:** 新 `src/input_probe.py`：`python -m src.input_probe [out.txt]` —— 原始模式读取并 dump 每条 INPUT_RECORD 全字段（记录类型 KEY/UNICODE/IME + 事件 flag + uChar + extendedKey/modifiers），启动/结束打印 GetConsoleCP/osfhandle（是否 ConPTY）；只读无副作用，Esc 或超时退出。/doctor 增加「输入通道」诊断行（CP + 通道形态提示）。**用户需在 git bash 跑一次并把输出回传**，11 的最终形态依记录形态定稿。

**Type:** task
**Status:** open
**Blocked by:** 无

## 验收
- [ ] git bash 下 `python -m src.input_probe` 可跑通，输出含逐条记录 dump + 控制台 CP
- [ ] 输出可重定向 [out.txt]
- [ ] /doctor 出现输入通道诊断行
- [ ] 非 Windows 平台优雅降级（提示不支持）

## Comments