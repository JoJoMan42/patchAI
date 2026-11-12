"""Shared test setup. Tests never need Ollama, a GPU or the internet."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

# Use the offline hashing embedder, no reranker, and temporary folders for indexes and logs.
_TMP = Path(tempfile.mkdtemp(prefix="patchai_tests_"))
os.environ["PATCHAI_EMBEDDER"] = "hash"
os.environ["PATCHAI_RERANKER"] = "off"
os.environ["PATCHAI_INDEX"] = str(_TMP / "index")
os.environ["PATCHAI_DECISIONS"] = str(_TMP / "decisions.jsonl")
os.environ["PATCHAI_DEMO_WORKSPACE"] = str(_TMP / "demo_workspace")

ROOT = Path(__file__).resolve().parent.parent
SHOP = ROOT / "demo_projects" / "vuln_shop"


@pytest.fixture
def shop(tmp_path) -> Path:
    """A fresh copy of the vulnerable demo shop that a test may modify."""
    copy = tmp_path / "vuln_shop"
    shutil.copytree(SHOP, copy, ignore=shutil.ignore_patterns("__pycache__"))
    return copy


@pytest.fixture(scope="session")
def shop_findings():
    """The scanner results for the demo shop (scanned once, since scanning takes a few seconds)."""
    from patchai.scan import scan

    return scan(SHOP)
