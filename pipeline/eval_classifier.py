"""
Measures course-classification accuracy against a human-reviewed answer key.

Every course gets one of three results:
  CORRECT  -- classifier was HIGH confidence and its categories exactly match the key
  FLAGGED  -- classifier was NOT HIGH confidence, so the pipeline would ask the
              student for a syllabus excerpt instead of guessing. Safe, not wrong.
  WRONG    -- classifier was HIGH confidence but its categories differ from the key.
              These are the dangerous ones: a wrong answer the pipeline would accept.

The target is: WRONG = 0 on every run, and as few FLAGGED as possible.

With --runs N, the whole answer key is classified N separate times, each with a
fresh, empty knowledge base (so nothing is reused and every course really goes
to the LLM). Any course whose answer changes between runs is reported as
INCONSISTENT -- the knowledge base would store whichever answer came first,
permanently, for every student, so inconsistency must be found here, not in
production.

This script never touches the real verified_knowledge_base.json.

Usage (same folder as the pipeline, same .env):
    py eval_classifier.py
    py eval_classifier.py --runs 3
    py eval_classifier.py --key answer_key_eee.json          (EE field; picks eee_taxonomy.json itself)
    py eval_classifier.py --key ../tests/gold/answer_key_cs.json   (relabelled keys, 30.10.2026)

Saving money (31.10.2026) -- only re-test what changed:
    py pipeline/eval_classifier.py --key answer_key_mechanical.json --only workshop
    py pipeline/eval_classifier.py --key answer_key_eee.json --only "iot,sensor network"
    py pipeline/eval_classifier.py --retest eval_report_20261031_123157.json   (only WRONG + FLAGGED of that run)
A bare key name is looked up in tests/gold/. Every run prints and saves the LLM usage (calls, tokens, time, euros).
"""

from dotenv import load_dotenv
load_dotenv()

import argparse
import json
import os
import tempfile
from datetime import datetime

from course_classifier import load_taxonomy, classify_courses_openai
from eval_selection import resolve_key, select_courses
from llm_utils import reset_usage, usage_line, usage_summary


from knowledge_base import KnowledgeBase
from transcript_parser import ExtractedCourse


def short(cat_id: str) -> str:
    return cat_id.split(".")[-1]


def fmt(cats) -> str:
    return "[" + ", ".join(short(c) for c in sorted(cats)) + "]" if cats else "[none]"


def run_once(key_courses: list, taxonomy: dict, with_map: bool = False) -> dict:
    """Classifies every answer-key course once, with a throwaway empty knowledge base.
    with_map=False (default): the LLM alone, so the approved course map cannot answer for it.
    with_map=True: the full system (approved map first, LLM for the rest)."""
    courses = [ExtractedCourse(course_id=c["id"], title=c["title"], credits=c["credits"])
               for c in key_courses]
    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeBase(path=os.path.join(tmp, "eval_kb.json"), use_approved_map=with_map)
        results = classify_courses_openai(courses, taxonomy, knowledge_base=kb)
    # 30.10.2026: measure what the system outputs, i.e. after the lab rule (taxonomy rule 7 in code)
    from lab_rule import apply_lab_rule
    results = apply_lab_rule(results, {c.course_id: c.title for c in courses})
    return {r["course_id"]: r for r in results}


def score(key_courses: list, results: dict) -> list:
    rows = []
    for c in key_courses:
        r = results.get(c["id"], {})
        got = set(r.get("categories", []))
        expected = set(c["expected"])
        conf = r.get("confidence", "MISSING")
        if conf != "HIGH":
            verdict = "FLAGGED"
        elif got == expected:
            verdict = "CORRECT"
        else:
            verdict = "WRONG"
        rows.append({
            "id": c["id"], "title": c["title"], "verdict": verdict, "confidence": conf,
            "expected": sorted(expected), "got": sorted(got),
            "extra": sorted(got - expected), "missing": sorted(expected - got),
            "reasoning": r.get("reasoning", ""),
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", default=None, help="answer key (bare name -> tests/gold/); with --retest taken from the report")
    parser.add_argument("--only", default=None, help="re-test only titles containing any of these comma-separated words")
    parser.add_argument("--retest", default=None, help="eval report: re-test only its WRONG and FLAGGED courses")
    parser.add_argument("--taxonomy", default=None,
                        help="defaults to the taxonomy of the answer key's field (e.g. eee -> eee_taxonomy.json)")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--with-map", action="store_true",
                        help="measure the full system: approved course map first, LLM only for unknown titles")
    args = parser.parse_args()

    retest_ids = None
    if args.retest:
        with open(args.retest, encoding="utf-8") as f:
            old = json.load(f)
        retest_ids = {r["id"] for run in old["runs"] for r in run if r["verdict"] in ("WRONG", "FLAGGED")}
        args.key = args.key or old["key"]
    args.key = resolve_key(args.key or "answer_key_cs.json")
    with open(args.key, encoding="utf-8") as f:
        key_data = json.load(f)
    key_courses = select_courses(key_data["courses"], args.only, retest_ids)
    if not key_courses:
        print("No courses selected -- nothing sent to the LLM (0 cost).")
        return
    reset_usage()
    args.taxonomy = args.taxonomy or f"{key_data.get('field', 'cs')}_taxonomy.json"
    taxonomy = load_taxonomy(args.taxonomy)
    print(f"Answer key: {args.key} ({len(key_courses)} courses) | taxonomy: {args.taxonomy} | "
          + ("full system (approved map + LLM)" if args.with_map else "LLM alone (approved map off)"))

    all_runs = []
    for i in range(1, args.runs + 1):
        print(f"Run {i}/{args.runs}: classifying {len(key_courses)} courses (fresh, no knowledge base)...")
        rows = score(key_courses, run_once(key_courses, taxonomy, with_map=args.with_map))
        all_runs.append(rows)

        counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("CORRECT", "FLAGGED", "WRONG")}
        total = len(rows)
        print(f"  CORRECT {counts['CORRECT']}/{total} ({100 * counts['CORRECT'] / total:.1f}%)   "
              f"FLAGGED {counts['FLAGGED']}   WRONG {counts['WRONG']}")
        for r in rows:
            if r["verdict"] == "WRONG":
                print(f"    WRONG   {r['id']} {r['title']}: expected {fmt(r['expected'])}, got {fmt(r['got'])}")
        for r in rows:
            if r["verdict"] == "FLAGGED":
                print(f"    FLAGGED {r['id']} {r['title']} ({r['confidence']}): got {fmt(r['got'])}")

    inconsistent = []
    if args.runs > 1:
        for idx, c in enumerate(key_courses):
            answers = {(run[idx]["confidence"], tuple(run[idx]["got"])) for run in all_runs}
            if len(answers) > 1:
                inconsistent.append({"id": c["id"], "title": c["title"],
                                     "answers": [{"confidence": a[0], "categories": list(a[1])} for a in answers]})
        print(f"\nINCONSISTENT across {args.runs} runs: {len(inconsistent)}")
        for item in inconsistent:
            variants = " vs ".join(f"{a['confidence']} {fmt(a['categories'])}" for a in item["answers"])
            print(f"    {item['id']} {item['title']}: {variants}")

    wrong_total = sum(1 for run in all_runs for r in run if r["verdict"] == "WRONG")
    print("\nRESULT:", "PASS -- no wrong answers accepted" if wrong_total == 0
          else f"FAIL -- {wrong_total} wrong answer(s) would have been accepted")

    print(usage_line())
    report_path = f"eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({"key": args.key, "taxonomy": args.taxonomy, "runs": all_runs,
                   "inconsistent": inconsistent,
                   "selection": {"only": args.only, "retest": args.retest, "courses": len(key_courses)},
                   "llm_usage": usage_summary()}, f, indent=2)
    print(f"Full details saved to {report_path}")


if __name__ == "__main__":
    main()
