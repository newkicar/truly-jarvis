"""共享测试工具。

Seam: 把 Config 构造抽到一处，避免 test_agent / test_scheduler 各维护一份
`_fake_config`（加字段要改两处，shotgun 症状）。
"""
from src.config import Config


def make_fake_config(tmp_path) -> Config:
    """构造指向 tmp_path 的假 Config（不触网、不碰真 vault）。"""
    return Config(
        base_url="https://fake/v1",
        api_key="sk",
        model_id="m",
        tavily_key="tvly",
        vault_path=tmp_path / "vault",
        memory_dir=tmp_path / "memory",
        checkpoint_db=tmp_path / "cp.sqlite",
        schedules_dir=tmp_path / "schedules",
        skills=(),
        mcps=(),
        permissions={},
    )