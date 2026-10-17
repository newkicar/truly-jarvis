# 01 — checkpoint_ns 全链路修复（undo 第二次起 KeyError）

**What to build:** `src/commands.py` 的 `thread_config()`（L23，configurable 字面量唯一出处）补 `"checkpoint_ns": ""`。langgraph 1.2.11 的 put 类 API（`update_state`→`bulk_update_state`→`checkpointer.put`）强制读 `config["configurable"]["checkpoint_ns"]`，缺键即 `KeyError`；get 类 API 容忍缺键，所以「第一次 undo 前一切正常、undo 本身第一次调 update_state 就炸」。覆盖 undo L929/L943、_rollback L480、fork、prepare_replay、finalize_turn 全链路。

**Type:** bug
**Status:** done (2026-10-18, commit c40d6a9)
**Blocked by:** 无

## 验收
- [x] `scratch_repro_undo.py` 由 KeyError 转绿（3 轮对话 + undo×3 撤到空白）
- [x] 回归测试（`tests/test_undo.py` 新增，SqliteSaver + `tempfile.gettempdir()` 自建目录，禁 tmp_path）：三轮对话 → 循环 undo 至空白 → 空白后再 undo 返回「没有可撤回的消息」而非异常
- [x] 全量 pytest 无新增失败
实施记录（2026-10-18，commit c40d6a9）：thread_config 补 checkpoint_ns；undo 重写为 live head 外科式删除（RemoveMessage+as_node="model"）。回归：test_undo+test_commands+test_streaming+test_tui 106 绿；全量（--ignore=test_rag）545 过 / 3 挂——test_config×3 经 stash 对照确认为预存环境失败；含 test_rag 的跑法在 chromadb rust upsert access violation，与 pytest_baseline.txt 基线同款（预存原生崩溃，非本票引入）。

## Comments
diagnosing-bugs 六阶段痕迹：
- Phase 1 假设：undo 内部 checkpoint 坐标丢失 / history 结构变化。
- Phase 2 红灯：`scratch_repro_undo.py` —— `undo #1: 异常！KeyError: 'checkpoint_ns'`（traceback：`bulk_update_state`→`perform_superstep`→`SqliteSaver.put` 读 `config["configurable"]["checkpoint_ns"]`）。
- Phase 3 根因：`thread_config` L23-28 只放 thread_id(+checkpoint_id)；langgraph 1.2.11 put 路径必需 checkpoint_ns（get 路径默认 ""，调用方省略）。
- Phase 4 绿灯：补 `"checkpoint_ns": ""` 后 repro 全绿（待本票实施执行）。
- Phase 5 回归：循环 undo 测试 + 全量。
