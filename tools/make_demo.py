"""
Store the result of one real online run of a SYNTHETIC sample as the website's demo (12.11.2026).

    py tools/make_demo.py <session_id> [--degree information_technology] [--n-max 10] [--n-min 5]

Reads GPUR_ACCESS_KEY from .env (never typed in a chat), fetches GET /sessions/<id> from the live API and writes
data/demo/demo_s18.json in the shape the website's "See a sample result" expects. It keeps only what the result page
needs: no course list, no check-screen values, no session id. The student's name is replaced by a fixed label.
Nothing is recalculated: the lists are exactly what the API returned.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "demo" / "demo_s18.json"


def fetch(api: str, sid: str, key: str) -> dict:
    req = urllib.request.Request(f"{api}/sessions/{sid}", headers={"X-Access-Key": key})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def build(view: dict, sid: str, degree: str, n_max: float, n_min: float, when: str) -> dict:
    if view.get("status") != "done" or not view.get("results"):
        raise SystemExit(f"session is not finished (status {view.get('status')!r}); run the eligibility step first")
    vals = (view.get("check_screen") or {}).get("values") or {}
    return {
        "_about": (f"GPU-R demo result ({when}, Koushik approved): the real online run of synthetic sample S18 "
                   f"(fictional B.Tech IT graduate, MAKAUT curriculum), session {sid}: real AI reading and "
                   f"classification, syllabus skipped, degree {degree}, no confirmations. Engine with the per-area "
                   "condition limits of 11.11.2026 and the Frankfurt HIS gate of 12.11.2026. Stored as returned by "
                   "the API, not recalculated. No personal data."),
        "status": "done",
        "demo": True,
        "field": view.get("field"),
        "degree_field_id": degree,
        "student": {"name": "SAMPLE STUDENT 18 (fictional)", "program": vals.get("program"),
                    "institution": vals.get("institution"), "cgpa": vals.get("stated_cgpa"),
                    "n_max": n_max, "n_min": n_min},
        "check_screen": {"field_options": (view.get("check_screen") or {}).get("field_options", [])},
        "profile": view.get("profile"),
        "results": view["results"],
    }


def main(argv: list) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_id")
    ap.add_argument("--degree", default="information_technology")
    ap.add_argument("--n-max", type=float, default=10)
    ap.add_argument("--n-min", type=float, default=5)
    ap.add_argument("--api", default=os.environ.get("GPUR_API", "https://gpu-r-api.onrender.com"))
    a = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    key = os.environ.get("GPUR_ACCESS_KEY")
    if not key:
        raise SystemExit("GPUR_ACCESS_KEY is not set in .env")
    demo = build(fetch(a.api, a.session_id, key), a.session_id, a.degree, a.n_max, a.n_min,
                 dt.date.today().strftime("%d.%m.%Y"))
    OUT.write_text(json.dumps(demo, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    c = demo["results"]["counts"]
    print(f"written {OUT}: lists 1/2/3/4 = {c.get('1')}/{c.get('2')}/{c.get('3')}/{c.get('4')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
