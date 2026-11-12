"""The safe demo copy of the vulnerable shop, and scanning inside git-ignored folders."""

import hashlib
import shutil
import subprocess

import pytest

from patchai import demo
from patchai.scan import scan, semgrep_available

ALL_CWES = {"CWE-89", "CWE-78", "CWE-22", "CWE-79", "CWE-798", "CWE-327", "CWE-502"}


def shop_fingerprint() -> str:
    """One hash over every tracked demo-shop file, to prove nothing touched it."""
    digest = hashlib.sha256()
    for file in sorted(demo.SOURCE.rglob("*")):
        if file.is_file() and "__pycache__" not in file.parts:
            digest.update(str(file.relative_to(demo.SOURCE)).encode())
            digest.update(file.read_bytes())
    return digest.hexdigest()


def test_demo_copy_is_created_and_reset_restores_it():
    before = shop_fingerprint()

    copy = demo.demo_project(reset=True)
    assert copy.exists() and (copy / "shop" / "db.py").exists()
    assert copy != demo.SOURCE and demo.SOURCE not in copy.parents

    # An applied "fix" survives a plain call...
    (copy / "shop" / "db.py").write_text("# fixed\n", encoding="utf-8")
    assert demo.demo_project() == copy
    assert (copy / "shop" / "db.py").read_text(encoding="utf-8") == "# fixed\n"

    # ...and a reset throws it away.
    demo.demo_project(reset=True)
    assert "# fixed" not in (copy / "shop" / "db.py").read_text(encoding="utf-8")

    # The tracked shop never changed.
    assert shop_fingerprint() == before


@pytest.mark.skipif(not semgrep_available() or shutil.which("git") is None,
                    reason="needs semgrep and git")
def test_scan_finds_everything_inside_a_git_ignored_folder(tmp_path):
    """Semgrep must scan what is on disk, even files that git ignores (A2)."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / ".gitignore").write_text("shop_copy/\n", encoding="utf-8")
    shutil.copytree(demo.SOURCE, tmp_path / "shop_copy",
                    ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    found = {f.cwe for f in scan(tmp_path / "shop_copy")}
    assert found == ALL_CWES
