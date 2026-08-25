"""#10 路径放开：deepagents middleware 层的 Windows 盘符路径定点适配。"""
import pytest

from deepagents.middleware import filesystem as _fs_middleware

from src import path_policy


@pytest.fixture(autouse=True)
def _applied_and_restored():
    saved = _fs_middleware.validate_path
    path_policy.apply_unrestricted_paths()
    yield
    _fs_middleware.validate_path = saved


def test_drive_letter_paths_pass_through():
    assert path_policy.validate_path(r"D:\some\other\project\f.py") == r"D:\some\other\project\f.py"
    assert path_policy.validate_path("C:/Users/x/note.md") == "C:/Users/x/note.md"


def test_posix_style_still_normalized():
    assert path_policy.validate_path("/a/b.txt") == "/a/b.txt"
    assert path_policy.validate_path("rel/file.txt") == "/rel/file.txt"


def test_traversal_still_rejected():
    with pytest.raises(ValueError):
        path_policy.validate_path("../etc/passwd")
    with pytest.raises(ValueError):
        path_policy.validate_path("~/secrets")


def test_patch_is_idempotent():
    first = path_policy.validate_path
    path_policy.apply_unrestricted_paths()
    assert path_policy.validate_path is first
