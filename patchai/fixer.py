"""Step 3: ask the model for a fix, check it, and retry with the error if it fails.

One attempt:
  1. build the prompt (on a retry: the previous fix and the exact error it caused)
  2. ask the model, parse its JSON answer            -> check "format"
  3. splice the fix into the file, run the guard     -> check "guard"
  4. on a temporary copy: tests, security test, scan -> checks "tests", "security_test", "rescan"
The loop stops at the first attempt that passes everything, or after max_attempts.
An answer identical to an earlier failed one is not checked again: it gets the same result.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from patchai import checks, llm
from patchai.config import get_config
from patchai.guard import check_fix
from patchai.models import Attempt, CheckResult, CodeContext, Finding, FixProposal, RetrievedChunk
from patchai.patching import apply_fix, clean_model_code, make_diff, read_text
from patchai.prompts import build_prompt
from patchai.scan import scan

EventFn = Callable[[str, str], None]


def parse_proposal(text: str) -> FixProposal:
    """Read the model's JSON answer. Raises ValueError if it isn't valid."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("The answer contains no JSON object.")
    try:
        return FixProposal.model_validate(json.loads(text[start:end + 1]))
    except (json.JSONDecodeError, ValidationError) as e:
        raise ValueError(f"The answer is not valid FixProposal JSON: {e}") from e


def fix(project_dir: str | Path, finding: Finding, context: CodeContext, retrieved: list[RetrievedChunk],
        model: str, max_attempts: int = 3, on_event: EventFn | None = None,
        chat_fn: Callable[..., llm.LLMReply] | None = None) -> list[Attempt]:
    """Run the fix-and-check loop. Returns every attempt (the last one decides the verdict)."""
    project_dir = Path(project_dir)
    emit = on_event or (lambda stage, message: None)
    retry_temperature = get_config()["generation"].get("retry_temperature")

    def ask(messages: list[dict], number: int) -> llm.LLMReply:
        if chat_fn is not None:  # a scripted model in tests
            return chat_fn(messages, model)
        # Retries use a slightly higher temperature, so the model doesn't repeat the same answer.
        return llm.chat(messages, model, temperature=None if number == 1 else retry_temperature)

    original_text = read_text(project_dir / finding.file_path)
    baseline: set[str] | None = None  # tests failing before the fix (computed once, when needed)
    findings_before: list[Finding] | None = None
    attempts: list[Attempt] = []
    error: str | None = None
    previous_fix: str | None = None
    tried: dict[str, Attempt] = {}  # fixed code -> the attempt that already checked it

    for number in range(1, max_attempts + 1):
        started = time.perf_counter()
        emit("generate", f"Attempt {number}: asking {model} for a fix")
        reply = ask(build_prompt(finding, context, retrieved, error, previous_fix), number)
        attempt = Attempt(number=number, proposal=None, raw_output=reply.text,
                          tokens_in=reply.tokens_in, tokens_out=reply.tokens_out)
        attempts.append(attempt)

        # Format: is the answer valid JSON in our shape?
        try:
            proposal = parse_proposal(reply.text)
        except ValueError as e:
            attempt.checks.append(CheckResult(name="format", passed=False, details=str(e)))
            error, previous_fix = f"Your answer could not be read. {e} Answer with JSON only.", None
            attempt.seconds = time.perf_counter() - started
            continue
        attempt.proposal = proposal
        attempt.checks.append(CheckResult(name="format", passed=True, details="Valid JSON answer."))

        if proposal.status != "fixed":  # the model says it cannot fix it, or that it is a false alarm
            emit("done", f"The model answered '{proposal.status}': {proposal.explanation}")
            attempt.seconds = time.perf_counter() - started
            break

        code = clean_model_code(proposal.fixed_code)
        previous_fix = code
        if code in tried:  # the same code as an attempt that already failed: same result, no need to re-run
            same = tried[code]
            attempt.diff, attempt.patched_file_text = same.diff, same.patched_file_text
            attempt.checks += [c.model_copy(update={"details": f"(same code as attempt {same.number}) {c.details}"})
                               for c in same.checks if c.name != "format"]
            error = f"You returned exactly the same code as attempt {same.number}, which already failed. {error or ''}"
            emit("retry", f"Attempt {number} repeated attempt {same.number}")
            attempt.seconds = time.perf_counter() - started
            continue
        tried[code] = attempt

        # Guard: fast safety rules on the patched file.
        emit("guard", f"Attempt {number}: checking the fix with the safety guard")
        patched = apply_fix(original_text, context, proposal)
        attempt.diff = make_diff(original_text, patched.text, finding.file_path)
        attempt.patched_file_text = patched.text
        guard = check_fix(original_text, patched, proposal, context, project_dir)
        attempt.checks.append(guard)
        if not guard.passed:
            error = f"The safety guard rejected the fix: {guard.details}"
            attempt.seconds = time.perf_counter() - started
            continue

        # Run it: tests, security test and a re-scan, on a temporary copy.
        if baseline is None:
            emit("tests", "Running the project's tests on the original code (baseline)")
            baseline, _ = checks.failing_tests(project_dir)
            findings_before = scan(project_dir, only_file=finding.file_path,
                                   scanners=checks.rescan_scanners(finding))
        with checks.patched_copy(project_dir, finding.file_path, patched.text) as copy:
            emit("tests", f"Attempt {number}: running the project's tests")
            attempt.checks.append(checks.run_tests(copy, baseline))
            emit("security_test", f"Attempt {number}: running the security test (trying the attack)")
            attempt.checks.append(checks.run_security_test(copy, finding))
            emit("rescan", f"Attempt {number}: re-scanning the fixed code")
            attempt.checks.append(checks.rescan(copy, finding, patched, findings_before or []))
        attempt.seconds = time.perf_counter() - started

        if attempt.passed:
            emit("done", f"Attempt {number} passed every check")
            break
        failed = [c for c in attempt.checks if not c.passed]
        error = " ".join(f"[{c.name}] {c.details}" for c in failed)
        emit("retry", f"Attempt {number} failed: {error[:200]}")

    return attempts
