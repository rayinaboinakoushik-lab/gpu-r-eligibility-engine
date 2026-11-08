"""31.10.2026: which answer-key courses an eval run sends to the LLM (re-test only what changed).
No LLM / OpenAI import here, so it is testable in CI."""
from __future__ import annotations

from pathlib import Path

GOLD_DIR = Path(__file__).resolve().parents[1] / "tests" / "gold"


def resolve_key(name: str) -> str:
    """A bare name like answer_key_cs.json is looked up in tests/gold/ (31.10.2026)."""
    p = Path(name)
    if p.exists():
        return str(p)
    if (GOLD_DIR / p.name).exists():
        return str(GOLD_DIR / p.name)
    raise FileNotFoundError(f"answer key {name!r} not found here or in {GOLD_DIR}")


def select_courses(key_courses: list, only: str | None = None, retest_ids: set | None = None) -> list:
    """--only: comma-separated words, a course is kept if its title contains any (case-insensitive).
    --retest: keep only the course ids given (WRONG + FLAGGED of an earlier report)."""
    out = key_courses
    if only:
        words = [w.strip().lower() for w in only.split(",") if w.strip()]
        out = [c for c in out if any(w in c["title"].lower() for w in words)]
    if retest_ids is not None:
        out = [c for c in out if c["id"] in retest_ids]
    return out
