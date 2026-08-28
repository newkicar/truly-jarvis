# 01 — git_mapping.sqlite + inbox_snapshots.sqlite 默认放到 checkpoints/

**What to build:**
运行时 SQLite 数据文件（git_mapping.sqlite、inbox_snapshots.sqlite）从项目根移入 checkpoints/ 子目录，与 checkpoints.sqlite 同级，统一管理。路径固定、不可通过 jarvis.json 配置。

**Type:** task
**Status:** ready-for-agent
**Blocked by:** 无

## 背景

- 当前 `src/time_travel.py:16` 和 `src/inbox_snapshots.py:11` 各自硬编码 `DB_NAME = "xxx.sqlite"`，`_db_path(root)` 直接返回 `root / DB_NAME`——文件散落在项目根。
- 上一轮已把 checkpoints.sqlite 移进 `checkpoints/` 子目录（commit `21aefd6`），但 git_mapping.sqlite 和 inbox_snapshots.sqlite 遗漏了。
- 三个运行时 DB 应放同一目录，统一管理。

## 目标

### 1. 引入共享常量消除「checkpoints」魔法字符串

`src/project_paths.py` 新增：

```python
RUNTIME_DATA_DIR = "checkpoints"
```

### 2. config.py 复用常量

`src/config.py` 改为：

```python
from src.project_paths import RUNTIME_DATA_DIR
DEFAULT_CHECKPOINT_DB = f"{RUNTIME_DATA_DIR}/checkpoints.sqlite"
```

`src/project_init.py` 已导入 `DEFAULT_CHECKPOINT_DB`，无需再改。

### 3. time_travel.py — 路径 + 目录创建

```python
from src.project_paths import RUNTIME_DATA_DIR

def _db_path(root: Path) -> Path:
    path = root / RUNTIME_DATA_DIR / DB_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
```

同步更新 `time_travel.py:18` 注释：`checkpoints.sqlite / .env / git_mapping.sqlite` → `checkpoints/ / .env`。

### 4. inbox_snapshots.py — 同理

```python
from src.project_paths import RUNTIME_DATA_DIR

def _db_path(root: Path) -> Path:
    path = Path(root).resolve() / RUNTIME_DATA_DIR / DB_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
```

### 5. .gitignore 清理

删除第 9 行显式 `git_mapping.sqlite`（已被 `checkpoints/` 目录规则覆盖）。

### 6. 更新断言

检查并更新相关测试中对根目录下 `git_mapping.sqlite` / `inbox_snapshots.sqlite` 的引用。

## 验证

- `pytest tests/test_time_travel.py tests/test_inbox_snapshots.py -q` 通过
- `pytest tests/ -q` 全量 395+ 通过
- `git grep -n "git_mapping.sqlite\|inbox_snapshots.sqlite"` 确认无残留的根目录硬编码引用
