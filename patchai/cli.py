"""Command line for PatchAI.

  patchai doctor [--warm]             check that everything is installed (and load the model)
  patchai scan  <project>             list vulnerabilities
  patchai index <project>             build the RAG indexes
  patchai fix   <project> [--finding ID] [--model NAME]   fix one, then approve or reject
  patchai demo  [--reset]             the safe demo copy of the vulnerable shop
  patchai app                         open the review app in the browser
  patchai serve [--port 8765]         run the local server for the VS Code extension
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from patchai import llm, review
from patchai.config import get_config
from patchai.models import FixResult, cwe_name
from patchai.pipeline import fix_finding, scan_project

app = typer.Typer(help="PatchAI: an AI that fixes security vulnerabilities in Python code.", no_args_is_help=True)
console = Console()


@app.command()
def doctor(warm: bool = typer.Option(False, "--warm", help="Also load the model into memory now")) -> None:
    """Check that the scanners, the model server, the models and RAG are ready."""
    from patchai.embeddings import get_embedder, get_reranker
    from patchai.scan import semgrep_available

    def row(name: str, ok: bool, detail: str) -> None:
        console.print(f"  {'[green]✔' if ok else '[red]✘'}[/] {name}: {detail}")

    console.print("[bold]PatchAI setup check[/]")
    row("Bandit", True, "installed")
    row("Semgrep", semgrep_available(), "installed" if semgrep_available() else "missing: pip install semgrep (needed for path traversal and XSS)")
    status = llm.model_status()
    models = status["installed"]
    row("Ollama", status["ollama"], "running" if status["ollama"] else "not running: install from https://ollama.com, then `ollama serve`")
    for name in [get_config()["models"]["default"], *get_config()["models"]["fallbacks"]]:
        have = name in models
        hint = "installed" if have else ("train it (see training/README.md)" if name.startswith("patchai") else f"`ollama pull {name}`")
        row(f"Model {name}", have, hint)
    embedder = get_embedder()
    row("Embeddings", embedder.name != "hash", embedder.name)
    reranker = get_reranker()
    row("Reranker", reranker is not None, reranker.name if reranker else "off")
    if status["default"]:
        console.print(f"  Fixes will use [bold]{status['default']}[/].")
    if status["problem"]:
        console.print(f"  [yellow]{status['problem']}[/]")
    if warm and status["default"]:
        with console.status(f"Loading {status['default']}..."):
            seconds = llm.warm_up(status["default"])
        console.print(f"  Model loaded in {seconds:.0f}s and kept in memory.")


@app.command()
def demo(reset: bool = typer.Option(False, "--reset", help="Throw away every applied fix")) -> None:
    """Print the path of the safe demo copy of the vulnerable shop (created on first use)."""
    from patchai.demo import demo_project

    console.print(str(demo_project(reset=reset)))


@app.command(name="app")
def run_app() -> None:
    """Open the review app in the browser."""
    import subprocess
    import sys

    from patchai.config import ROOT

    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "review_app.py")], check=False)


@app.command()
def serve(port: int = typer.Option(8765, help="Port for the local server")) -> None:
    """Run the local server the VS Code extension talks to."""
    import uvicorn

    uvicorn.run("patchai.server:app", host="127.0.0.1", port=port)


@app.command()
def scan(project: Path) -> None:
    """List the vulnerabilities in a project."""
    findings = scan_project(project)
    table = Table(title=f"{len(findings)} vulnerabilities in {project}")
    for col in ("ID", "Severity", "Type", "Location", "Message"):
        table.add_column(col)
    for f in findings:
        table.add_row(f.id, f.severity, f"{f.cwe} {cwe_name(f.cwe)}", f"{f.file_path}:{f.start_line}", f.message[:60])
    console.print(table)


@app.command()
def index(project: Path) -> None:
    """Build (or update) the RAG indexes for a project."""
    from patchai.rag_index import build_index

    counts = build_index(project)
    console.print("Indexed: " + ", ".join(f"{n} {name} chunks" for name, n in counts.items()))


@app.command()
def fix(project: Path, finding: str = typer.Option("", help="Finding ID (default: the first one)"),
        model: str = typer.Option("", help="Model name (default: from config.yaml)")) -> None:
    """Fix one vulnerability, show the evidence, then approve or reject it."""
    findings = scan_project(project)
    chosen = next((f for f in findings if f.id == finding), None) if finding else (findings[0] if findings else None)
    if chosen is None:
        console.print("[red]No matching finding.[/]")
        raise typer.Exit(1)
    console.print(f"Fixing [bold]{cwe_name(chosen.cwe)}[/] in {chosen.file_path}:{chosen.start_line}")
    with console.status("Working...") as status:
        result = fix_finding(project, chosen, model=model or None,
                             on_event=lambda stage, msg: status.update(msg))
    show_result(result)
    if result.verdict != "fixed":
        return
    if typer.confirm("Apply this fix to the project?", default=False):
        console.print(f"[green]Applied to {review.approve(project, result)}[/]")
    else:
        reason = typer.prompt("Why are you rejecting it?")
        review.reject(project, result, reason)
        console.print("Rejected and recorded.")


def show_result(result: FixResult) -> None:
    """Print a fix result: retrieved context, every attempt's checks, and the final diff."""
    if result.error:
        console.print(f"[red]Error:[/] {result.error}")
    for chunk in result.retrieved:
        console.print(f"  [dim]RAG[/] {chunk.source:8} {chunk.score:.2f}  {chunk.title}")
    for attempt in result.attempts:
        marks = "  ".join(f"{'[green]✔' if c.passed else '[red]✘'}[/] {c.name}" for c in attempt.checks)
        console.print(f"Attempt {attempt.number} ({attempt.seconds:.0f}s): {marks}")
        for c in attempt.checks:
            if not c.passed:
                console.print(f"    [red]{c.name}:[/] {c.details[:300]}")
    final = result.final
    if final and final.proposal:
        console.print(Panel(final.proposal.explanation or "-", title=f"Explanation (confidence {final.proposal.confidence:.0%})"))
    if result.diff:
        console.print(Syntax(result.diff, "diff"))
    colour = {"fixed": "green", "failed": "red"}.get(result.verdict, "yellow")
    console.print(f"Verdict: [bold {colour}]{result.verdict.upper()}[/] with {result.model} in {result.seconds:.0f}s")


if __name__ == "__main__":
    app()
