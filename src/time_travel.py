"""Time travel。

会话回退：checkpointer（thread_id + checkpoint_id）→ /history /replay /fork /sessions。
文件回退：git 快照（每 turn 一 commit）+ 映射表 {thread_id, checkpoint_id, commit_hash}。
"""
