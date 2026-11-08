"""Step 4b: prove a fix works by running it, always on a temporary copy of the project.

Three checks:
  tests          the project's own tests still pass (no test that passed before may fail)
  security_test  the project's security test for this vulnerability type passes
  rescan         the scanner no longer reports the vulnerability, and reports nothing new

Security tests live in `security_tests/test_cwe<number>*.py` inside the project. They
fail while the vulnerability exists and pass once it is really fixed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from patchai.config import get_config
from patchai.models import CheckResult, Finding
from patchai.patching import PatchedFile, write_text
from patchai.scan import SEMGREP_CWES, SKIP_DIRS, scan

COPY_IGNORE = shutil.ignore_patterns(".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules")


@contextmanager
def patched_copy(project_dir: str | Path, file_path: str, new_text: str) -> Iterator[Path]:
    """A temporary copy of the project with one file replaced. Deleted afterwards."""
    tmp = Path(tempfile.mkdtemp(prefix="patchai_"))
    copy = tmp / "project"
    try:
        shutil.copytree(project_dir, copy, ignore=COPY_IGNORE)
        write_text(copy / file_path, new_text)
        yield copy
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def failing_tests(project_dir: str | Path) -> tuple[set[str], str]:
    """Run the project's normal tests. Returns (ids of failing tests, short summary).

    The summary includes the first error lines (e.g. "KeyError: 'API_TOKEN'"), so a failed
    attempt tells the model exactly what went wrong."""
    project_dir = Path(project_dir)
    target = ["tests"] if (project_dir / "tests").is_dir() else ["."]
    ignore = [f"--ignore={d}" for d in SKIP_DIRS if d != "tests" and (project_dir / d).exists()]
    code, failed, summary = _pytest(project_dir, target + ignore)
    if code == 5:  # pytest: no tests collected
        return set(), "no tests found"
    if code not in (0, 1):
        return {"<the tests could not even start>"}, summary
    return failed, summary


def run_tests(copy_dir: Path, baseline_failures: set[str]) -> CheckResult:
    """Pass if no test fails that was passing before the fix."""
    failed, summary = failing_tests(copy_dir)
    if summary == "no tests found":
        return CheckResult(name="tests", passed=True, skipped=True, details="The project has no tests.")
    new_failures = sorted(failed - baseline_failures)
    if new_failures:
        return CheckResult(name="tests", passed=False,
                           details=f"Tests that now fail: {', '.join(new_failures[:5])}. {summary}")
    return CheckResult(name="tests", passed=True, details=f"All tests still pass. {summary}")


def security_test_files(project_dir: Path, finding: Finding) -> list[Path]:
    """The security tests that belong to this finding's vulnerability type."""
    folder = project_dir / "security_tests"
    if not finding.cwe or not folder.is_dir():
        return []
    number = finding.cwe.split("-")[1]
    # test_cwe79.py or test_cwe79_anything.py (but not test_cwe798_... for CWE-79)
    return sorted(set(folder.glob(f"test_cwe{number}.py")) | set(folder.glob(f"test_cwe{number}_*.py")))


def run_security_test(copy_dir: Path, finding: Finding) -> CheckResult:
    """Pass if the security tests for this vulnerability type pass on the fixed code."""
    files = security_test_files(copy_dir, finding)
    if not files:
        return CheckResult(name="security_test", passed=True, skipped=True,
                           details="No security test exists for this vulnerability type.")
    code, failed, summary = _pytest(copy_dir, [str(f.relative_to(copy_dir)) for f in files])
    if code == 0:
        return CheckResult(name="security_test", passed=True, details=f"The attack no longer works. {summary}")
    names = ", ".join(sorted(name.split("::")[-1] for name in failed)[:3])
    return CheckResult(name="security_test", passed=False,
                       details=f"The vulnerability can still be exploited ({names or 'security test failed'}). {summary}")


def rescan(copy_dir: Path, finding: Finding, patched: PatchedFile, findings_before: list[Finding]) -> CheckResult:
    """Pass if the scanner no longer flags the fixed region and reports nothing new in the file."""
    after = scan(copy_dir, only_file=finding.file_path, scanners=rescan_scanners(finding))

    def in_region(f: Finding) -> bool:
        return f.start_line <= patched.end_line and f.end_line >= patched.start_line

    still_there = [f for f in after if f.cwe == finding.cwe and in_region(f)]
    if still_there:
        return CheckResult(name="rescan", passed=False,
                           details=f"The scanner still reports {finding.cwe} here: {still_there[0].message}")
    before = Counter(f.rule_id for f in findings_before if f.id != finding.id)
    now = Counter(f.rule_id for f in after)
    new = now - before
    if new:
        return CheckResult(name="rescan", passed=False,
                           details=f"The fix introduced new scanner findings: {', '.join(new)}.")
    return CheckResult(name="rescan", passed=True, details="The scanner no longer reports this vulnerability.")


def rescan_scanners(finding: Finding) -> list[str]:
    """Scanners to re-run after a fix. Semgrep takes a few seconds to start, so it only runs
    for the vulnerability types its rules cover; Bandit always runs."""
    return ["bandit", "semgrep"] if finding.cwe in SEMGREP_CWES else ["bandit"]


def _pytest(project_dir: Path, args: list[str]) -> tuple[int, set[str], str]:
    """Run pytest in a folder. Returns (exit code, failing test ids, one-line summary)."""
    timeout = get_config()["checks"]["test_timeout_s"]
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.xml"
        command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   f"--junitxml={report}", *args]
        env = {**os.environ, "PYTHONPATH": str(project_dir), "PYTHONDONTWRITEBYTECODE": "1"}
        try:
            proc = subprocess.run(command, cwd=project_dir, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return 2, {"<timeout>"}, f"The tests took longer than {timeout}s."
        failed = _failed_from_junit(report) if report.exists() else set()
        lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
        summary = lines[-1].strip("= ") if lines else ""
        if proc.returncode != 0:
            error = error_lines(proc.stdout)
            summary = f"{summary}. Error: {error}" if error else summary
        return proc.returncode, failed, summary


def error_lines(pytest_output: str, limit: int = 2) -> str:
    """The first distinct error lines pytest printed, e.g. "KeyError: 'API_TOKEN'" or
    "AssertionError: assert '<script>' not in page"."""
    found: list[str] = []
    for line in pytest_output.splitlines():
        if line.startswith("E   "):
            text = line[4:].strip()
            if text and not text.startswith(("+", "-", "?", "where ", "and ")) and text not in found:
                found.append(text[:200])
        if len(found) >= limit:
            break
    return " | ".join(found)


def _failed_from_junit(report: Path) -> set[str]:
    """Ids of failed or errored tests from a pytest JUnit XML report."""
    failed = set()
    for case in ET.parse(report).getroot().iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            failed.add(f"{case.get('classname', '')}::{case.get('name', '')}")
    return failed
