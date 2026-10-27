"""工单 13：打包资产静态校验（不真跑 Nuitka/Inno——需要 C 编译工具链与长构建，
本机只校验交付脚本的不变式：安装目录只读、用户数据零写入、基础 venv 不捆 RAG）。"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    p = REPO / rel
    assert p.is_file(), f"打包资产缺失：{rel}"
    return p.read_text(encoding="utf-8")


def test_packaging_assets_present():
    for rel in (
        "packaging/build_gui.ps1",
        "packaging/setup.iss",
        "packaging/sign_release.ps1",
        "packaging/README.md",
    ):
        assert (REPO / rel).is_file(), f"缺失 {rel}"


def test_base_venv_excludes_rag():
    """遗留 c：基础构建 venv 不装 RAG 可选依赖（缺 chromadb 自动降级）。"""
    ps1 = _read("packaging/build_gui.ps1")
    assert "pip install -e ." in ps1
    assert "[rag]" not in ps1, "基础 venv 不应拉 [rag] 可选组"
    assert "--onefile" not in ps1, "约定 onedir 不用 onefile（启动慢）"
    assert "--standalone" in ps1


def test_installer_writes_no_user_data():
    """Inno [Files] 仅写 {app}（Program Files 只读）；用户数据只可经 opt-in 清理任务删除。"""
    iss = _read("packaging/setup.iss")
    files_block = iss[iss.index("[Files]"): iss.index("[Icons]")]
    for src in [l for l in files_block.splitlines() if l.startswith("Source:")]:
        assert "DestDir: \"{app}\"" in src, f"[Files] 写入越界 {app}：{src}"
    assert "userappdata" not in files_block and "userprofile" not in files_block, (
        "安装阶段不得写 %APPDATA%/.jarvis（用户数据与安装目录分离）"
    )
    # 用户数据仅出现在卸载 opt-in 清理任务（[Delete]），且默认 unchecked
    delete_block = iss[iss.index("[Delete]"):]
    assert "userappdata" in delete_block and "cleandata" in delete_block
    assert "Flags: unchecked" in iss[iss.index("[Tasks]"): iss.index("[Delete]")]


def test_signing_and_release_checklist():
    ps1 = _read("packaging/sign_release.ps1")
    assert "signtool sign" in ps1 and "signtool verify" in ps1
    assert "SHA256" in ps1 and "Get-FileHash" in ps1
    assert "digicert" in ps1.lower() or "timestamp" in ps1.lower()
    readme = _read("packaging/README.md")
    assert "误报记录" in readme and "LGPL" in readme
