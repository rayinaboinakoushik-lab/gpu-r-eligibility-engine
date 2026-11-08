"""
Run ledger (07.11.2026): every eligibility check counts. One anonymous row per finished or failed run,
from the website or the terminal scripts. Evaluation runs are already counted in tools/eval_log.

Privacy: only the fields in ALLOWED are ever stored. No name, institution, roll number, CGPA, grades,
course titles or file names, so the ledger can be kept and published as statistics.

Storage:
  GPUR_LEDGER_URL set   -> PostgreSQL table gpur_runs (persistent; for the Render server, e.g. a free EU database)
  otherwise             -> JSON lines file GPUR_LEDGER_FILE (default: runs_ledger.jsonl in the current folder)
A ledger problem never breaks a run: errors are printed and the run goes on.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ALLOWED = {
    "ts", "source", "status", "failed_step", "field", "degree_field_id",
    "n_courses", "n_not_counted", "n_syllabus_resolved",
    "list_counts", "seconds", "llm_calls", "input_tokens", "cached_tokens", "output_tokens",
}
SOURCES = {"website", "terminal"}
_TABLE = "gpur_runs"


def _clean(entry: dict) -> dict:
    row = {k: v for k, v in entry.items() if k in ALLOWED}
    row.setdefault("ts", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if row.get("source") not in SOURCES:
        raise ValueError(f"source must be one of {sorted(SOURCES)}")
    return row


def _file(default: Path | None = None) -> Path:
    return Path(os.environ.get("GPUR_LEDGER_FILE") or default or "runs_ledger.jsonl")


def _db():
    import psycopg                                  # only needed when GPUR_LEDGER_URL is set
    conn = psycopg.connect(os.environ["GPUR_LEDGER_URL"], autocommit=True)
    conn.execute(f"CREATE TABLE IF NOT EXISTS {_TABLE} (id BIGSERIAL PRIMARY KEY, "
                 "ts TIMESTAMPTZ NOT NULL DEFAULT now(), data JSONB NOT NULL)")
    return conn


def record(entry: dict, default_file: Path | None = None) -> dict | None:
    """Store one anonymous run row. Returns the stored row, or None if storing failed."""
    try:
        row = _clean(entry)
        if os.environ.get("GPUR_LEDGER_URL"):
            with _db() as conn:
                conn.execute(f"INSERT INTO {_TABLE} (data) VALUES (%s)", (json.dumps(row),))
        else:
            with _file(default_file).open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
    except Exception as e:                          # noqa: BLE001 -- counting must never break a student's run
        print(f"[run ledger] not recorded: {type(e).__name__}: {e}")
        return None


def rows(default_file: Path | None = None) -> list[dict]:
    if os.environ.get("GPUR_LEDGER_URL"):
        with _db() as conn:
            return [r[0] for r in conn.execute(f"SELECT data FROM {_TABLE} ORDER BY id").fetchall()]
    p = _file(default_file)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def summary(data: list[dict] | None = None, default_file: Path | None = None) -> dict:
    """Totals for the website and the README: runs, finished, failed, per source, averages of finished runs."""
    data = rows(default_file) if data is None else data
    done = [r for r in data if r.get("status") == "done"]
    by_source: dict[str, int] = {}
    for r in data:
        by_source[r.get("source", "?")] = by_source.get(r.get("source", "?"), 0) + 1
    def avg(key):
        vals = [r[key] for r in done if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 1) if vals else None
    return {"runs": len(data), "finished": len(done), "failed": len(data) - len(done),
            "by_source": by_source, "avg_seconds": avg("seconds"), "avg_courses": avg("n_courses")}


def usage_totals(usage: list[dict]) -> dict:
    """Adds up the per-step usage entries the API keeps for a session."""
    keys = ("seconds", "calls", "input_tokens", "cached_tokens", "output_tokens")
    t = {k: sum((u.get(k) or 0) for u in usage) for k in keys}
    return {"seconds": round(t["seconds"], 1), "llm_calls": t["calls"], "input_tokens": t["input_tokens"],
            "cached_tokens": t["cached_tokens"], "output_tokens": t["output_tokens"]}
