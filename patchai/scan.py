"""Step 1: run the vulnerability scanners (Bandit and Semgrep) and return Findings."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from patchai.config import path
from patchai.models import Finding

# Bandit rule -> the CWE it detects. Only these rules are run, so the scanner
# reports exactly the seven vulnerability types PatchAI handles.
BANDIT_RULES: dict[str, str] = {
    "B608": "CWE-89",  # SQL built with string formatting
    "B602": "CWE-78",  # subprocess with shell=True
    "B604": "CWE-78",  # any function called with shell=True
    "B605": "CWE-78",  # os.system / os.popen with a shell
    "B105": "CWE-798",  # password-like variable set to a string
    "B106": "CWE-798",  # password-like argument set to a string
    "B107": "CWE-798",  # password-like default argument
    "B303": "CWE-327",  # MD5 / SHA1
    "B324": "CWE-327",  # hashlib with a weak hash
    "B301": "CWE-502",  # pickle
    "B302": "CWE-502",  # marshal
    "B506": "CWE-502",  # yaml.load without SafeLoader
    "B701": "CWE-79",  # Jinja2 with autoescape turned off
    "B703": "CWE-79",  # Django mark_safe
    "B308": "CWE-79",  # mark_safe
}

# Our own severity per vulnerability type, so both scanners rank findings the same way.
SEVERITY: dict[str, str] = {
    "CWE-89": "high",
    "CWE-78": "high",
    "CWE-502": "high",
    "CWE-798": "high",
    "CWE-22": "medium",
    "CWE-79": "medium",
    "CWE-327": "medium",
}

# Folders that are not part of the code under review.
SKIP_DIRS = {"tests", "security_tests", ".venv", "venv", ".git", "__pycache__", "node_modules"}


# Vulnerability types covered by our Semgrep rules (data/semgrep_rules.yaml).
SEMGREP_CWES = {"CWE-22", "CWE-79"}


def scan(project_dir: str | Path, only_file: str | None = None,
         scanners: list[str] | None = None) -> list[Finding]:
    """Run the scanners (default: all) on a project, or one file in it, and merge the results."""
    project_dir = Path(project_dir).resolve()
    scanners = scanners or ["bandit", "semgrep"]
    findings = []
    if "bandit" in scanners:
        findings += run_bandit(project_dir, only_file)
    if "semgrep" in scanners:
        findings += run_semgrep(project_dir, only_file)
    return _deduplicate(findings)


def run_bandit(project_dir: Path, only_file: str | None = None) -> list[Finding]:
    """Run Bandit and convert its JSON report into Findings."""
    target = str(project_dir / only_file) if only_file else str(project_dir)
    command = [
        sys.executable, "-m", "bandit", "-f", "json", "-q",
        "-t", ",".join(BANDIT_RULES),
        "-x", ",".join(f"*/{d}/*" for d in SKIP_DIRS),
    ]
    command += [target] if only_file else ["-r", target]
    report = _run_json(command)
    findings = []
    for issue in report.get("results", []):
        cwe = BANDIT_RULES.get(issue["test_id"])
        if cwe is None:
            continue
        line_range = issue.get("line_range") or [issue["line_number"]]
        findings.append(
            _make_finding(
                project_dir,
                scanner="bandit",
                rule_id=issue["test_id"],
                cwe=cwe,
                file=issue["filename"],
                start=min(line_range),
                end=max(line_range),
                message=issue["issue_text"],
                code=issue.get("code", ""),
            )
        )
    return findings


def semgrep_available() -> bool:
    """True when the semgrep command can be found."""
    return _semgrep_command() is not None


def run_semgrep(project_dir: Path, only_file: str | None = None) -> list[Finding]:
    """Run Semgrep with our own rules (data/semgrep_rules.yaml). Skipped if not installed."""
    semgrep = _semgrep_command()
    rules = path("semgrep_rules")
    if semgrep is None or not rules.exists():
        return []
    target = str(project_dir / only_file) if only_file else str(project_dir)
    # --no-git-ignore: scan what is on disk. Without it Semgrep silently skips
    # files that git ignores, which hides vulnerabilities in ignored folders.
    command = [semgrep, "scan", "--config", str(rules), "--json", "--quiet", "--metrics=off", "--no-git-ignore"]
    for d in SKIP_DIRS:
        command += ["--exclude", d]
    command.append(target)
    report = _run_json(command, timeout=180)
    findings = []
    for result in report.get("results", []):
        cwe = result.get("extra", {}).get("metadata", {}).get("cwe")
        if cwe not in SEVERITY:
            continue
        findings.append(
            _make_finding(
                project_dir,
                scanner="semgrep",
                rule_id=result["check_id"].split(".")[-1],
                cwe=cwe,
                file=result["path"],
                start=result["start"]["line"],
                end=result["end"]["line"],
                message=result.get("extra", {}).get("message", ""),
                code=result.get("extra", {}).get("lines", ""),
            )
        )
    return findings


def _make_finding(project_dir: Path, *, scanner: str, rule_id: str, cwe: str, file: str,
                  start: int, end: int, message: str, code: str) -> Finding:
    """Build a Finding with a project-relative path and a stable id."""
    rel = Path(file).resolve().relative_to(project_dir).as_posix()
    finding_id = hashlib.sha1(f"{rule_id}|{rel}|{start}".encode()).hexdigest()[:12]
    try:  # the exact flagged lines (scanner snippets include line numbers and neighbours)
        lines = (project_dir / rel).read_text(encoding="utf-8").splitlines()
        code = "\n".join(lines[start - 1:end])
    except (OSError, UnicodeDecodeError):
        pass
    return Finding(
        id=finding_id, scanner=scanner, rule_id=rule_id, cwe=cwe,
        severity=SEVERITY[cwe], file_path=rel, start_line=start, end_line=end,
        message=message.strip(), code=code.strip(),
    )


def _deduplicate(findings: list[Finding]) -> list[Finding]:
    """When two scanners report the same type on the same line, keep only one."""
    seen: set[tuple[str, int, str | None]] = set()
    unique = []
    for f in sorted(findings, key=lambda f: (f.file_path, f.start_line)):
        key = (f.file_path, f.start_line, f.cwe)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def _run_json(command: list[str], timeout: int = 120) -> dict:
    """Run a scanner and parse its JSON output. Scanners exit with 1 when they find issues."""
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env)
    try:
        return json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return {}


def _semgrep_command() -> str | None:
    """Find semgrep next to the running Python (inside the venv) or on PATH."""
    scripts = str(Path(sys.executable).parent)
    return shutil.which("semgrep", path=scripts + os.pathsep + os.environ.get("PATH", ""))
