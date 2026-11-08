"""
Every run counts (07.11.2026). Prints how many times GPU-R has been run, from all sources:
  evaluation runs   tests/synthetic/results/eval_log.jsonl (scored synthetic transcripts)
  terminal runs     runs_ledger.jsonl in the repo folder (your own runs with run_eligibility.py)
  website runs      the server's ledger: set GPUR_LEDGER_URL (database) to include it

Usage (from the repo folder):  py tools/run_count.py
"""
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "pipeline")]
import run_ledger            # noqa: E402
from eval_log import load_log   # noqa: E402


def main():
    ev = load_log()
    samples = {r["sample"] for r in ev}
    courses = sum(len(r.get("courses") or []) for r in ev)
    decisions = sum((r.get("verdicts") or {}).get("programmes", 0) for r in ev)
    local = run_ledger.rows(default_file=REPO / "runs_ledger.jsonl") if not os.environ.get("GPUR_LEDGER_URL") else []
    server = run_ledger.rows() if os.environ.get("GPUR_LEDGER_URL") else []
    led = local + server
    s = run_ledger.summary(led)
    print("GPU-R run count")
    print(f"  evaluation runs : {len(ev):4}  ({len(samples)} synthetic transcripts, {courses} courses checked, {decisions} programme decisions)")
    for src in ("terminal", "website"):
        n = s["by_source"].get(src, 0)
        print(f"  {src + ' runs':16}: {n:4}")
    print(f"  all runs        : {len(ev) + s['runs']:4}  (finished outside evaluation: {s['finished']}, failed: {s['failed']})")
    if not os.environ.get("GPUR_LEDGER_URL"):
        print("  note: website runs are only included when GPUR_LEDGER_URL points to the server's database")


if __name__ == "__main__":
    main()
