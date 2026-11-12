"""A tiny local API so the VS Code extension can use the pipeline.

Run it with:  python -m uvicorn patchai.server:app --port 8765
It only listens on this computer. The only thing it remembers is the latest fix for each
finding, so that the reviewer's decision can be logged with the full details.
"""

from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from patchai import demo as demo_module
from patchai import llm, review
from patchai.config import ROOT, get_config
from patchai.models import Finding, FixResult
from patchai.pipeline import fix_finding, scan_project
from patchai.scan import semgrep_available

VERSION = "1.0.0"

app = FastAPI(title="PatchAI local server")
_recent_fixes: dict[str, FixResult] = {}  # finding id -> latest FixResult
_jobs: dict[str, dict] = {}  # job id -> {"done", "events", "result", "error"}


class ScanRequest(BaseModel):
    project_dir: str


class FixRequest(BaseModel):
    project_dir: str
    finding: Finding
    model: str | None = None


class DecisionRequest(BaseModel):
    project_dir: str
    finding_id: str
    decision: Literal["approved", "rejected"]
    reason: str | None = None
    model: str = ""


class DemoRequest(BaseModel):
    reset: bool = False


@app.get("/health")
def health() -> dict:
    status = llm.model_status()
    default = status["default"] or get_config()["models"]["default"]
    return {"ok": True, "models": status["installed"], "default_model": default,
            "version": VERSION, "root": str(ROOT), "ollama": status["ollama"],
            "fine_tuned": status["fine_tuned"], "semgrep": semgrep_available(),
            "problem": status["problem"]}


@app.post("/scan")
def scan(request: ScanRequest) -> dict:
    project = _project(request.project_dir)
    return {"findings": [f.model_dump() for f in scan_project(project)]}


@app.post("/fix")
def fix(request: FixRequest) -> dict:
    project = _project(request.project_dir)
    result = fix_finding(project, request.finding, model=request.model or None)
    if result.error and not result.attempts:
        raise HTTPException(status_code=503, detail=result.error)
    _recent_fixes[request.finding.id] = result
    return result.model_dump()


@app.post("/fix/start")
def fix_start(request: FixRequest) -> dict:
    """Start a fix as a background job, so clients can show progress instead of waiting."""
    project = _project(request.project_dir)
    job_id = uuid.uuid4().hex
    job = _jobs[job_id] = {"done": False, "events": [], "result": None, "error": None}
    while len(_jobs) > 20:  # keep only the newest jobs
        _jobs.pop(next(iter(_jobs)))

    def run() -> None:
        result = fix_finding(project, request.finding, model=request.model or None,
                             on_event=lambda stage, message: job["events"].append(
                                 {"stage": stage, "message": message}))
        if result.error and not result.attempts:
            job["error"] = result.error
        else:
            _recent_fixes[request.finding.id] = result
            job["result"] = result.model_dump()
        job["done"] = True

    threading.Thread(target=run, daemon=True).start()
    return {"job_id": job_id}


@app.get("/fix/status/{job_id}")
def fix_status(job_id: str) -> dict:
    """The events so far and, once done, the result or the error."""
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return {"done": job["done"], "events": list(job["events"]),
            "result": job["result"], "error": job["error"]}


@app.post("/demo")
def demo(request: DemoRequest) -> dict:
    """The safe demo copy of the vulnerable shop (created or reset on demand)."""
    return {"project_dir": str(demo_module.demo_project(reset=request.reset))}


@app.post("/decision")
def decision(request: DecisionRequest) -> dict:
    # The extension applies an accepted fix itself (so VS Code can undo it); we only record it.
    result = _recent_fixes.get(request.finding_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No fix with that finding id was made by this server.")
    if request.decision == "rejected" and not (request.reason or "").strip():
        raise HTTPException(status_code=422, detail="A reason is required to reject a fix.")
    review.record_decision(request.project_dir, result, request.decision, request.reason)
    return {"ok": True}


def _project(project_dir: str) -> Path:
    project = Path(project_dir)
    if not project.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a folder: {project_dir}")
    return project
