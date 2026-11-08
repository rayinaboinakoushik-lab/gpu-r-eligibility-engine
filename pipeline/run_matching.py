"""
REFERENCE ONLY (27.10.2026): replaced by run_eligibility.py, which uses the new engine (gpur/engine.py).

Runs the matching engine for one student profile and prints a ranked result.

Usage:
    py run_matching.py <final_matching_profile.json> [--all]

Writes matching_result_<name>.json next to the profile.
"""

import argparse
import json
import re
from pathlib import Path

from matching_engine import MatchingEngine, StudentProfile, results_to_json, summarize, VERDICT_ORDER

ICON = {"PASS": "✓", "FAIL": "✗"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("--all", action="store_true", help="also print NOT_ELIGIBLE programs in full")
    ap.add_argument("--data-dir", default=".")
    ap.add_argument("--field", choices=["cs", "eee", "mechanical", "civil"],
                    help="only for profiles saved before the field was recorded in the profile")
    args = ap.parse_args()

    with open(args.profile, encoding="utf-8") as f:
        data = json.load(f)
    if "field" not in data:
        if not args.field:
            print("This profile was saved before the field was recorded in it.\n"
                  "Add the student's field, e.g.:  py run_matching.py " + args.profile + " --field cs")
            return
        data["field"] = args.field
    student = StudentProfile.from_json(data)

    engine = MatchingEngine(student.field, data_dir=args.data_dir)
    results = engine.match(student)
    counts = summarize(results)

    print(f"\n=== {student.name} | field: {student.field} | German grade {student.german_grade:.2f} ===")
    conv = data.get("ects_conversion")
    if conv:
        print(f"ECTS: 1 credit = {conv['factor']:.2f} ECTS ({conv['basis']})"
              + ("" if conv["basis"] == "official" else " -- subject ECTS are estimates; "
                 "give the program total credits for the official value"))
    else:
        print("ECTS: profile built with the old fixed 1 credit = 1.5 ECTS -- rerun Stage 4-5 to convert officially")
    print(f"{len(results)} programs checked: " + ", ".join(f"{v} {counts[v]}" for v in VERDICT_ORDER))
    for verdict in VERDICT_ORDER:
        group = [r for r in results if r.verdict == verdict]
        if not group:
            continue
        print(f"\n--- {verdict} ({len(group)}) ---")
        for r in group:
            print(f"\n• {r.program} -- {r.university}")
            if verdict == "NOT_ELIGIBLE" and not args.all:
                print(f"    {r.summary}")
                continue
            if verdict == "CONDITIONAL":
                print(f"    {r.summary}")
            for c in r.checks:
                print(f"    {ICON[c.status]} {c.label}: {c.detail}")
            for a in r.also_required:
                print(f"    + to apply you also need: {a}")

    if student.excluded_courses:
        print("\nNot counted (could not be confidently classified, so they count toward no category):")
        for e in student.excluded_courses:
            ects = f", {e['ects']:g} ECTS" if isinstance(e.get("ects"), (int, float)) else ""
            print(f"  - {e.get('title') or e.get('course_id')}{ects}")
        print("  With the official syllabus for these courses, the profile can be re-checked.")

    # One result file per profile: final_matching_profile_<session>.json -> matching_result_<session>.json
    stem = Path(args.profile).stem.replace("final_matching_profile_", "")
    out = Path(args.profile).with_name(f"matching_result_{stem}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results_to_json(student, results), f, indent=2, ensure_ascii=False)
    print(f"\nSaved full result to {out}")


if __name__ == "__main__":
    main()
