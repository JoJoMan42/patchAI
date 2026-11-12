"""Talks to the local model server (Ollama). This is the only file that calls a model."""

from __future__ import annotations

import time
from dataclasses import dataclass

from patchai.config import get_config
from patchai.models import FixProposal


class LLMError(RuntimeError):
    """The model server is not reachable or the model is missing."""


@dataclass
class LLMReply:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    seconds: float


def _client():
    import ollama

    return ollama.Client(host=get_config()["ollama_url"])


def list_models() -> list[str]:
    """Names of the models installed in Ollama (empty if Ollama is not running)."""
    try:
        response = _client().list()
    except Exception:
        return []
    names = []
    for m in response.models:
        name = m.model or ""
        names.append(name.removesuffix(":latest"))
    return names


def resolve_model(name: str | None = None) -> str:
    """The model to use: the one asked for, else our fine-tuned model, else the first installed fallback."""
    cfg = get_config()["models"]
    installed = list_models()
    if not installed:
        raise LLMError("Ollama is not running. Install it from https://ollama.com and run `ollama serve`.")
    wanted = name or cfg["default"]
    if _is_installed(wanted, installed):
        return wanted
    if name:  # the caller asked for a specific model that isn't there
        raise LLMError(f"Model `{name}` is not installed. Run `ollama pull {name}`.")
    for fallback in cfg["fallbacks"]:
        if _is_installed(fallback, installed):
            return fallback
    raise LLMError(f"No model installed. Run `ollama pull {cfg['fallbacks'][0]}`.")


def chat(messages: list[dict], model: str, temperature: float | None = None) -> LLMReply:
    """Send a chat to the model. Its answer is forced to match the FixProposal JSON shape."""
    gen = get_config()["generation"]
    started = time.perf_counter()
    try:
        response = _client().chat(
            model=model,
            messages=messages,
            format=FixProposal.model_json_schema(),  # structured output: always valid JSON
            keep_alive=gen.get("keep_alive"),
            options={
                "temperature": gen["temperature"] if temperature is None else temperature,
                "num_ctx": gen["context_window"],
                "num_predict": gen["max_output_tokens"],
            },
        )
    except Exception as e:
        raise LLMError(f"The model call failed: {e}") from e
    return LLMReply(
        text=response.message.content or "",
        model=model,
        tokens_in=response.prompt_eval_count or 0,
        tokens_out=response.eval_count or 0,
        seconds=time.perf_counter() - started,
    )


def warm_up(model: str) -> float:
    """Load the model into memory before it is needed. Returns the seconds it took."""
    gen = get_config()["generation"]
    started = time.perf_counter()
    try:
        _client().generate(model=model, keep_alive=gen.get("keep_alive"))  # empty call: just loads
    except Exception as e:
        raise LLMError(f"Could not load `{model}`: {e}") from e
    return time.perf_counter() - started


def model_status() -> dict:
    """What the interfaces show about the model setup. Never raises.

    Keys: ollama (bool), installed (list), default (str | None),
    fine_tuned (bool), problem (str | None, one sentence for the user).
    """
    cfg = get_config()["models"]
    installed = list_models()
    if not installed:
        return {"ollama": False, "installed": [], "default": None, "fine_tuned": False,
                "problem": "Ollama is not running. Install it from https://ollama.com and run `ollama serve`."}
    try:
        default = resolve_model(None)
    except LLMError as e:
        return {"ollama": True, "installed": installed, "default": None, "fine_tuned": False,
                "problem": str(e)}
    fine_tuned = default.startswith("patchai")
    problem = None
    if not fine_tuned:
        problem = (f"The fine-tuned model `{cfg['default']}` is not installed, so the base model "
                   f"`{default}` is used. See training/README.md.")
    return {"ollama": True, "installed": installed, "default": default,
            "fine_tuned": fine_tuned, "problem": problem}


def _is_installed(name: str, installed: list[str]) -> bool:
    return name.removesuffix(":latest") in installed
