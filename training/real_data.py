"""Real-world training examples from CVEfixes (real CVEs and the commits that fixed them).

Source: the CVEfixes dataset (Bhandari, Naseer and Moonen, PROMISE 2021), as published on
Hugging Face at hitoshura25/cvefixes (Apache-2.0). Each row is one CVE with the git diff of the
commit that fixed it.

What this script does:
  1. keep Python fixes for our 7 vulnerability types
  2. download the fixed file from GitHub at the fixing commit, and undo the diff to get the
     vulnerable file (the dataset only stores the changed lines, not whole functions)
  3. run OUR scanners on the vulnerable file; keep a finding only if
       - it is inside a function the commit changed, and
       - the scanner no longer reports it in the fixed version of that function
  4. keep only fixes that our pipeline could accept: same function signature, at most 30
     changed lines, no new third-party imports, no new helper functions defined elsewhere
  5. write data/real_fixes/cvefixes.jsonl (the vulnerable file, the function before/after)

The result is small (real fixes are messy, so most are filtered out) but every kept example is
a real fix, from a real project, for a real CVE. make_dataset.py mixes them into training.

Run once (any laptop, no GPU; downloads about 1.2 GB the first time):
    python training/real_data.py
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
import sys
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from patchai.context import get_context  # noqa: E402
from patchai.models import CWE_NAMES  # noqa: E402
from patchai.scan import scan  # noqa: E402

DATASET = "hitoshura25/cvefixes"
SHARDS = [f"data/train-0000{i}-of-00003.parquet" for i in range(3)]
OUT = ROOT / "data" / "real_fixes" / "cvefixes.jsonl"
CACHE = Path.home() / ".cache" / "patchai" / "cvefixes"  # outside the repo (about 1.2 GB)
MAX_CHANGED_LINES = 30
MAX_FUNCTION_LINES = 80
MAX_FILE_LINES = 3000
MAX_PER_CVE = 3
SKIP_PATH = re.compile(r"(^|/)(tests?|testing|docs?|examples?|migrations)(/|$)|(^|/)test_[^/]*$|_test\.py$")

EXPLANATIONS = {
    "CWE-89": "User input was built into the SQL text, so it could change the query. The fix keeps the input out "
              "of the SQL, as in the project's own security patch.",
    "CWE-78": "User input reached a shell command, so it could run extra commands. The fix stops the input from "
              "being interpreted by a shell, as in the project's own security patch.",
    "CWE-22": "A user-supplied path could use ../ to reach files outside the intended folder. The fix restricts "
              "the path, as in the project's own security patch.",
    "CWE-79": "User-controlled text was put into HTML without escaping, so it could run scripts in the browser. "
              "The fix escapes it, as in the project's own security patch.",
    "CWE-798": "A credential was written in the source code. The fix removes it from the code, as in the project's "
               "own security patch.",
    "CWE-327": "A weak or broken cryptographic algorithm was used. The fix replaces it with a strong one, as in the "
               "project's own security patch.",
    "CWE-502": "Untrusted data was deserialized with a loader that can create arbitrary objects. The fix uses a safe "
               "loader, as in the project's own security patch.",
}


# ---------------------------------------------------------------- 1. read the dataset

def load_rows(cache: Path) -> list[dict]:
    """Python rows for our vulnerability types, from all shards."""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    rows = []
    columns = ["cve_id", "repo_url", "hash", "language", "cwe_id", "diff_with_context"]
    for shard in SHARDS:
        print(f"Reading {shard} (downloads once, then cached)...")
        path = hf_hub_download(DATASET, shard, repo_type="dataset", cache_dir=str(cache / "hf"))
        table = pq.read_table(path, columns=columns).to_pandas()
        keep = table[(table.language == "Python") & table.cwe_id.isin(list(CWE_NAMES))]
        rows += keep.to_dict("records")
    print(f"{len(rows)} Python fixes for our 7 types")
    return rows


# ---------------------------------------------------------------- 2. rebuild the vulnerable file

def split_diff(diff: str) -> dict[str, list[str]]:
    """{file path: its diff lines} for every file in a git diff."""
    files: dict[str, list[str]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current = None
        elif line.startswith("+++ "):
            path = line[4:].strip()
            current = path[2:] if path.startswith("b/") else None
            if current:
                files[current] = []
        elif current is not None and (line.startswith("@@") or line[:1] in (" ", "+", "-", "\\") or line == ""):
            files[current].append(line)
    return files


def undo_diff(after: str, diff_lines: list[str]) -> str | None:
    """The file before the commit, from the file after it and the diff. None if they don't match."""
    after_lines = after.split("\n")
    out: list[str] = []
    pos = 0  # index in after_lines
    hunk = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
    i = 0
    while i < len(diff_lines):
        m = hunk.match(diff_lines[i])
        if not m:
            i += 1
            continue
        new_start = int(m.group(1)) - 1 if m.group(2) != "0" else int(m.group(1))
        if new_start < pos:
            return None
        out += after_lines[pos:new_start]
        pos = new_start
        i += 1
        while i < len(diff_lines) and not diff_lines[i].startswith("@@"):
            line = diff_lines[i]
            tag, text = (line[:1], line[1:]) if line else (" ", "")
            if tag == " ":
                if pos >= len(after_lines) or after_lines[pos] != text:
                    return None
                out.append(text)
                pos += 1
            elif tag == "+":
                if pos >= len(after_lines) or after_lines[pos] != text:
                    return None
                pos += 1
            elif tag == "-":
                out.append(text)
            i += 1
    out += after_lines[pos:]
    return "\n".join(out)


def fetch(url: str, cache: Path) -> str | None:
    """Download a text file (cached on disk). None if it is gone."""
    key = cache / "github" / re.sub(r"[^A-Za-z0-9._-]", "_", url.split("githubusercontent.com/")[-1])[:200]
    if key.exists():
        text = key.read_text(encoding="utf-8")
        return text if text != "<missing>" else None
    key.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "patchai-dataset"}),
                                    timeout=20) as response:
            text = response.read().decode("utf-8")
    except (urllib.error.URLError, UnicodeDecodeError, TimeoutError, ConnectionError):
        text = None
    key.write_text(text if text is not None else "<missing>", encoding="utf-8")
    return text


def raw_url(repo_url: str, commit: str, path: str) -> str | None:
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", repo_url.strip())
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{commit}/{path}" if m else None


# ---------------------------------------------------------------- 3 + 4. find real, acceptable fixes

def functions(tree: ast.AST) -> dict[str, ast.AST]:
    """{qualified name: function node} for every function and method."""
    found: dict[str, ast.AST] = {}

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    found.setdefault(name, child)
                visit(child, name + ".")

    visit(tree, "")
    return found


def span(node: ast.AST) -> tuple[int, int]:
    return min([node.lineno] + [d.lineno for d in node.decorator_list]), node.end_lineno or node.lineno


def source_of(text: str, node: ast.AST) -> str:
    start, end = span(node)
    return textwrap.dedent("\n".join(text.split("\n")[start - 1:end])).strip("\n")


def top_level_names(tree: ast.Module) -> set[str]:
    names = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            names |= {t.id for t in stmt.targets if isinstance(t, ast.Name)}
    return names


def import_lines(tree: ast.Module, text: str) -> dict[str, tuple[str, set[str]]]:
    """{import line: (top-level module, names it defines)} for the file's top-level imports."""
    out = {}
    for stmt in tree.body:
        line = ast.get_source_segment(text, stmt) or ""
        if isinstance(stmt, ast.Import):
            out[line] = (stmt.names[0].name.split(".")[0],
                         {(a.asname or a.name).split(".")[0] for a in stmt.names})
        elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module:
            out[line] = (stmt.module.split(".")[0], {a.asname or a.name for a in stmt.names})
    return out


# Real fixes that work but would teach the wrong lesson.
BAD_LESSONS = [
    ("CWE-78", re.compile(r"shell\s*=\s*True"), "still_uses_a_shell"),
    ("CWE-502", re.compile(r"full_load|FullLoader|UnsafeLoader"), "loader_not_fully_safe"),
    ("CWE-89", re.compile(r",\s*\(\s*\w+\s*\)\s*\)"), "parameters_not_a_tuple"),  # execute(sql, (name)) is a bug
]


def used_names(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def candidate_files(rows: list[dict], cache: Path) -> list[dict]:
    """Rebuild (before, after) for every changed Python file."""
    files = []
    stats = Counter()
    for n, row in enumerate(rows):
        for path, lines in split_diff(row["diff_with_context"] or "").items():
            if not path.endswith(".py") or SKIP_PATH.search(path):
                continue
            url = raw_url(row["repo_url"], row["hash"], path)
            after = fetch(url, cache) if url else None
            if after is None:
                stats["file_unavailable"] += 1
                continue
            after = after.replace("\r\n", "\n")
            before = undo_diff(after, lines)
            if before is None or before == after:
                stats["diff_does_not_apply"] += 1
                continue
            if before.count("\n") > MAX_FILE_LINES:
                stats["file_too_long"] += 1
                continue
            files.append({"row": row, "path": path, "before": before, "after": after})
        if (n + 1) % 25 == 0:
            print(f"  {n + 1}/{len(rows)} fixes downloaded, {len(files)} files so far")
    print(f"{len(files)} changed Python files rebuilt ({dict(stats)})")
    return files


def examples_from(files: list[dict]) -> tuple[list[dict], Counter]:
    """Scan the vulnerable and fixed files and keep the real, acceptable function-level fixes."""
    stats: Counter = Counter()
    with tempfile.TemporaryDirectory() as tmp:
        before_root, after_root = Path(tmp) / "before", Path(tmp) / "after"
        for i, f in enumerate(files):
            for root, key in ((before_root, "before"), (after_root, "after")):
                (root / f"f{i:04d}").mkdir(parents=True)
                (root / f"f{i:04d}" / "module.py").write_bytes(f[key].encode("utf-8"))
        print("Scanning the vulnerable files...")
        found_before = scan(before_root)
        print("Scanning the fixed files...")
        found_after = scan(after_root)

        after_by_case: dict[str, list] = {}
        for finding in found_after:
            after_by_case.setdefault(finding.file_path.split("/")[0], []).append(finding)

        examples, per_cve, seen = [], Counter(), set()
        for finding in found_before:
            case = finding.file_path.split("/")[0]
            f = files[int(case[1:])]
            row = f["row"]
            try:
                tree_b, tree_a = ast.parse(f["before"]), ast.parse(f["after"])
            except SyntaxError:
                stats["not_python3"] += 1
                continue
            folder = before_root / case
            context = get_context(folder, finding.model_copy(update={"file_path": "module.py"}))
            if not context.function_name:
                stats["not_in_a_function"] += 1
                continue
            funcs_b, funcs_a = functions(tree_b), functions(tree_a)
            name = next((q for q, node in funcs_b.items() if span(node)[0] == context.start_line), None)
            if name is None or name not in funcs_a:
                stats["function_renamed_or_removed"] += 1
                continue
            node_b, node_a = funcs_b[name], funcs_a[name]
            old, new = source_of(f["before"], node_b), source_of(f["after"], node_a)
            key = (row["cve_id"], name)
            if key in seen:
                continue
            seen.add(key)
            if old == new:
                stats["function_not_changed_by_fix"] += 1
                continue
            a_start, a_end = span(node_a)
            still = [g for g in after_by_case.get(case, []) if g.rule_id == finding.rule_id
                     and a_start <= g.start_line <= a_end]
            if still:
                stats["fixed_version_still_flagged"] += 1
                continue
            changed = sum(1 for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="")
                          if line[:1] in "+-" and not line.startswith(("+++", "---")))
            if changed > MAX_CHANGED_LINES or old.count("\n") >= MAX_FUNCTION_LINES:
                stats["change_too_large"] += 1
                continue
            if ast.dump(node_b.args) != ast.dump(node_a.args):
                stats["signature_changed"] += 1
                continue
            new_helpers = (top_level_names(tree_a) - top_level_names(tree_b)) & used_names(node_a)
            if new_helpers:
                stats["uses_new_helper"] += 1
                continue
            lesson = next((why for cwe, pattern, why in BAD_LESSONS if cwe == finding.cwe and pattern.search(new)), None)
            if lesson:
                stats[lesson] += 1
                continue
            imports_b, imports_a = import_lines(tree_b, f["before"]), import_lines(tree_a, f["after"])
            uses = used_names(node_a)
            added = {line: mod for line, (mod, names) in imports_a.items() if line not in imports_b and names & uses}
            known = {mod for mod, _ in imports_b.values()} | set(sys.stdlib_module_names)
            if any(mod not in known for mod in added.values()):
                stats["new_third_party_import"] += 1
                continue
            if per_cve[row["cve_id"]] >= MAX_PER_CVE:
                stats["cve_limit"] += 1
                continue
            per_cve[row["cve_id"]] += 1
            examples.append({
                "cve_id": row["cve_id"], "repo": row["repo_url"], "commit": row["hash"], "path": f["path"],
                "cwe": finding.cwe, "cwe_label": row["cwe_id"], "rule": f"{finding.scanner}:{finding.rule_id}",
                "function": name, "start_line": context.start_line, "end_line": context.end_line,
                "vulnerable": textwrap.dedent(context.source.replace("\r\n", "\n")).strip("\n"),
                "fixed": new, "imports_to_add": sorted(added), "explanation": EXPLANATIONS[finding.cwe],
                "file_text": f["before"],
            })
            stats["kept"] += 1
    return examples, stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--cache", type=Path, default=CACHE, help="where downloads are kept")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()

    started = time.time()
    files = candidate_files(load_rows(args.cache), args.cache)
    examples, stats = examples_from(files)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")
    info = {"examples": len(examples), "cves": len({e["cve_id"] for e in examples}),
            "projects": len({e["repo"] for e in examples}),
            "by_cwe": dict(sorted(Counter(e["cwe"] for e in examples).items())),
            "filtered": dict(sorted(stats.items())), "minutes": round((time.time() - started) / 60, 1),
            "source": f"https://huggingface.co/datasets/{DATASET} (CVEfixes v1.0.8, Apache-2.0)"}
    (args.out.parent / "cvefixes_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
