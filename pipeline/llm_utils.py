"""
One safe way to ask the LLM for a JSON answer, used by every LLM call in the pipeline
(transcript extraction, course classification, syllabus-excerpt checks).

Why this exists: reasoning models spend part of their output budget "thinking" before
they answer. If the budget runs out during the thinking, the answer comes back EMPTY --
not an error, just nothing. A larger transcript (more courses) needs more budget, so a
fixed limit that works for one student silently fails for the next. This helper:

  1. Checks WHY an answer is empty or cut off (finish_reason / refusal).
  2. If the budget ran out, retries automatically with double the budget (up to a cap).
  3. If the model refused or returned something unparseable, raises a clear error
     instead of a raw JSON crash.
"""

import json
import os
import time
from typing import Any

# 31.10.2026 cost logging: every LLM call adds one entry (tokens, time). Prices are NOT hard-coded
# (they change); set them in .env to get euros:  GPUR_PRICE_INPUT=..  GPUR_PRICE_CACHED=..  GPUR_PRICE_OUTPUT=..
# (euros per 1 million tokens). Without prices only tokens are shown.
USAGE_LOG: list[dict] = []


def reset_usage() -> None:
    USAGE_LOG.clear()


def _record_usage(response, model: str, what: str, seconds: float) -> None:
    u = getattr(response, "usage", None)
    details = getattr(u, "prompt_tokens_details", None) if u else None
    USAGE_LOG.append({
        "what": what, "model": model, "seconds": round(seconds, 2),
        "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "cached_tokens": (getattr(details, "cached_tokens", 0) or 0) if details else 0,
        "output_tokens": getattr(u, "completion_tokens", 0) or 0,
    })


def usage_summary() -> dict:
    s = {"calls": len(USAGE_LOG), "seconds": round(sum(e["seconds"] for e in USAGE_LOG), 1),
         "input_tokens": sum(e["input_tokens"] for e in USAGE_LOG),
         "cached_tokens": sum(e["cached_tokens"] for e in USAGE_LOG),
         "output_tokens": sum(e["output_tokens"] for e in USAGE_LOG)}
    try:
        pin, pca, pout = (float(os.environ[k]) for k in ("GPUR_PRICE_INPUT", "GPUR_PRICE_CACHED", "GPUR_PRICE_OUTPUT"))
        s["euros"] = round(((s["input_tokens"] - s["cached_tokens"]) * pin + s["cached_tokens"] * pca
                            + s["output_tokens"] * pout) / 1_000_000, 4)
    except (KeyError, ValueError):
        s["euros"] = None
    return s


def save_usage(session_id: str, stage: str) -> None:
    """31.10.2026: append this stage's LLM usage to usage_<session>.json (read by the evaluation log)."""
    import json
    from datetime import datetime
    from pathlib import Path
    path = Path(f"usage_{session_id}.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        data = []
    data.append({"stage": stage, "at": datetime.now().isoformat(timespec="seconds"), **usage_summary(),
                 "calls_detail": list(USAGE_LOG)})
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")


def usage_line() -> str:
    s = usage_summary()
    cost = f" | about {s['euros']:.2f} EUR" if s["euros"] is not None else " | set GPUR_PRICE_* in .env for euros"
    return (f"LLM usage: {s['calls']} calls, {s['seconds']} s, {s['input_tokens']:,} input tokens "
            f"({s['cached_tokens']:,} cached), {s['output_tokens']:,} output tokens{cost}")


class LLMResponseError(ValueError):
    """The model did not produce a usable JSON answer. The message says why, in plain words."""


def call_llm_json(client, model: str, messages: list, max_tokens: int | None = 16000,
                  max_tokens_cap: int = 64000, what: str = "request") -> dict:
    """
    max_tokens=None means NO output limit at all: the parameter is not sent, so the model
    may use its full output capacity (used for transcript reading).
    """
    budget = max_tokens
    while True:
        kwargs: dict[str, Any] = {"model": model, "messages": messages, "response_format": {"type": "json_object"}}
        if budget is not None:
            kwargs["max_completion_tokens"] = budget
        t0 = time.time()
        response = client.chat.completions.create(**kwargs)
        _record_usage(response, model, what, time.time() - t0)
        choice = response.choices[0]
        message = choice.message
        finish = getattr(choice, "finish_reason", None)
        text = message.content or ""

        refusal = getattr(message, "refusal", None)
        if refusal:
            raise LLMResponseError(f"The model declined the {what}: {refusal}")

        if finish == "length":
            if budget is None:
                raise LLMResponseError(
                    f"The {what} did not fit even in the model's full output capacity. "
                    f"The input is unusually large -- split it into smaller parts."
                )
            if budget >= max_tokens_cap:
                raise LLMResponseError(
                    f"The {what} did not fit even with the maximum output budget ({max_tokens_cap} tokens). "
                    f"The input is unusually large -- split it into smaller parts."
                )
            budget = min(budget * 2, max_tokens_cap)
            print(f"  (answer did not fit -- retrying the {what} with more room: {budget} tokens)")
            continue

        if finish == "content_filter":
            raise LLMResponseError(f"The {what} was blocked by the provider's content filter.")

        if not text.strip():
            raise LLMResponseError(
                f"The model returned an empty answer for the {what} (finish_reason={finish!r}). "
                f"If this repeats, the uploaded file may be unreadable (blurred, cropped or rotated)."
            )

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMResponseError(
                f"The model's answer for the {what} was not valid JSON. Start of answer: {text[:300]!r}"
            ) from e
