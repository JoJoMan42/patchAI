"""Puts the model's fixed code back into the file and produces a diff.

The model returns the complete fixed function instead of a diff, because small models
often write broken diffs. We splice the function into the file ourselves, add any new
imports at the top, and compute the diff with difflib.
"""

from __future__ import annotations

import ast
import difflib
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

from patchai.models import CodeContext, FixProposal


@dataclass
class PatchedFile:
    """A file after the fix was applied, and where the rewritten region now sits."""

    text: str
    start_line: int
    end_line: int
    added_imports: list[str]


def read_text(file: str | Path) -> str:
    """Read a file exactly as it is (keeps Windows line endings)."""
    return Path(file).read_bytes().decode("utf-8")


def write_text(file: str | Path, text: str) -> None:
    """Write a file exactly as given (no line-ending conversion)."""
    Path(file).write_bytes(text.encode("utf-8"))


PROMPT_TAGS = "vulnerable_code|previous_fix|fixed_code|code|python"
_OPEN_TAG = re.compile(rf"^\s*<({PROMPT_TAGS})>[ \t]*\n?")
_CLOSE_TAG = re.compile(rf"\n?[ \t]*</({PROMPT_TAGS})>\s*$")
_FENCE = re.compile(r"^\s*```[a-zA-Z]*\n(.*?)\n?\s*```\s*$", re.DOTALL)


def clean_model_code(code: str) -> str:
    """Remove wrapping the model put around its code: markdown fences, and the tags from our
    prompt (some models answer "<vulnerable_code>def f(): ...</vulnerable_code>"). Then dedent.

    This matters for a fair comparison: without it, a correct fix wrapped in tags would be
    counted as a syntax error.
    """
    code = code.strip("\n")
    for _ in range(2):  # tags inside fences, or fences inside tags
        if fence := _FENCE.match(code):
            code = fence.group(1)
        code = _CLOSE_TAG.sub("", _OPEN_TAG.sub("", code, count=1), count=1)  # Python never starts/ends like this
    return textwrap.dedent(code).strip("\n")


def split_leading_imports(code: str) -> tuple[list[str], str]:
    """If the model put import lines above the function, separate them out."""
    imports, rest = [], code.splitlines()
    while rest and (rest[0].startswith("import ") or rest[0].startswith("from ") or not rest[0].strip()):
        line = rest.pop(0)
        if line.strip():
            imports.append(line.strip())
    return imports, "\n".join(rest)


def apply_fix(file_text: str, context: CodeContext, proposal: FixProposal) -> PatchedFile:
    """Replace the context region with the model's fixed code and add new imports."""
    newline = "\r\n" if "\r\n" in file_text else "\n"
    lines = file_text.splitlines(keepends=True)

    code = clean_model_code(proposal.fixed_code)
    extra_imports, code = split_leading_imports(code) if context.function_name else ([], code)

    # Re-indent the fixed code to where the original region was (e.g. inside a class).
    region = [(context.indent + line if line.strip() else "") + newline for line in code.splitlines()]
    trailing = lines[context.end_line - 1] if context.end_line <= len(lines) else ""
    if region and not trailing.endswith(("\n", "\r")):
        region[-1] = region[-1].rstrip("\r\n")  # the file did not end with a newline

    new_lines = lines[: context.start_line - 1] + region + lines[context.end_line:]
    start, end = context.start_line, context.start_line + len(region) - 1

    # Add imports the fix needs, below the existing imports.
    existing = {line.strip() for line in lines}
    wanted = [imp.strip() for imp in proposal.imports_to_add + extra_imports]
    to_add = []
    for imp in wanted:
        if imp.startswith(("import ", "from ")) and imp not in existing and imp not in to_add:
            to_add.append(imp)
    if to_add:
        at = _import_insert_line(file_text)
        new_lines[at:at] = [imp + newline for imp in to_add]
        if at <= context.start_line - 1:
            start, end = start + len(to_add), end + len(to_add)

    return PatchedFile(text="".join(new_lines), start_line=start, end_line=end, added_imports=to_add)


def make_diff(old: str, new: str, file_path: str) -> str:
    """A unified diff between two versions of a file."""
    diff = difflib.unified_diff(
        old.replace("\r\n", "\n").splitlines(keepends=True),
        new.replace("\r\n", "\n").splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    return "".join(diff)


def changed_line_count(diff: str) -> int:
    """How many lines a diff adds or removes."""
    return sum(
        1
        for line in diff.splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )


def _import_insert_line(file_text: str) -> int:
    """0-based line index just below the last top-level import (or the module docstring)."""
    try:
        tree = ast.parse(file_text)
    except SyntaxError:
        return 0
    last = 0
    for i, stmt in enumerate(tree.body):
        is_docstring = i == 0 and isinstance(stmt, ast.Expr) and isinstance(getattr(stmt, "value", None), ast.Constant)
        if isinstance(stmt, (ast.Import, ast.ImportFrom)) or is_docstring:
            last = stmt.end_lineno or stmt.lineno
    return last
