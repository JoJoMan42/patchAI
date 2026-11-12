"""A scratch copy of the demo shop, so demos never change the tracked vulnerable project."""

from __future__ import annotations

import shutil
from pathlib import Path

from patchai.config import ROOT, path

SOURCE = ROOT / "demo_projects" / "vuln_shop"


def demo_project(reset: bool = False) -> Path:
    """The demo copy (created on first use). `reset=True` throws away every applied fix."""
    target = path("demo_workspace") / "vuln_shop"
    if reset and target.exists():
        shutil.rmtree(target)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(SOURCE, target,
                        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return target
