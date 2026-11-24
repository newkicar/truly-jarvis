# 07 — ADR + AGENTS.md + 收尾回归

**What to build:** 文档收尾：新 ADR（当前最大号 +1）、AGENTS.md 关键决策一笔 goal 段、.scratch 关票、全量回归基线。

**Blocked by:** 06

**Status:** done

## 背景

- 核心行为变更须 ADR + AGENTS.md 记录（项目纪律）。

## 范围

- [x] `docs/adr/00NN-goal-persistence-and-auto-continuation.md`（以当前 ADR 最大号 +1 定号，暂按 0013 占位）：决策 = goals.json 单进程存储（否 sqlite / 每线程一文件）/ 续跑走回合门 FIFO / 模型仅 3 工具 / 预算 MVP = 回合数 / cancel = 断链非暂停 / 正交性清单 + 已知项（单进程并发限制与 YOLO 共享 state 同源）
- [x] AGENTS.md「关键技术决策」+1 笔：goal（存储 / 触发条件 / 3 工具 / 防转圈 / 正交性）
- [x] `.scratch/javis-goal/spec.md` 状态更新 + 01–07 全部关票
- [x] 全量 pytest 收尾回归（排除预存 test_config×3 红），零新增失败

## 非目标

- 不改代码行为（纯收尾）
