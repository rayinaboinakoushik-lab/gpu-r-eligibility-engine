"""
Step 6: eligibility. Reads the final profile from Stage 4-5 and runs the engine (gpur/engine.py) on
every programme of the student's field. No LLM here.

Usage (from the repo folder):
    py pipeline/run_eligibility.py final_matching_profile_<session>.json [--all]
    py pipeline/run_eligibility.py profile.json --gate 640      (opens GATE routes)

Writes eligibility_<session>.json (full results) and eligibility_<session>.md (report) next to the profile.
Replaces run_matching.py (old engine, reference only).
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # repo root: makes "gpur" importable

from gpur import engine, profile as prof, report                    # noqa: E402

CONFIRMATIONS = {   # gated routes: what the student must confirm (engine_config.json "gated_routes")
    "water_thesis": "Was your bachelor thesis on a water-related topic? (y/n)",
    "module_average_confirmed": "Is your average in the listed modules good enough (see the programme note)? (y/n)",
    "subject_points_confirmed": "Do you have at least 10 subject/thesis points as the programme requires? (y/n)",
}


def confirm_degree(p: dict, degree_fields: dict) -> str:
    guess = prof.guess_degree_field(p.get("degree_field", ""), degree_fields)
    ids = list(degree_fields)
    print(f'\nYour degree on the transcript: "{p.get("degree_field")}"')
    for i, fid in enumerate(ids, 1):
        print(f"  {i:2}. {fid:36} e.g. {degree_fields[fid]['aliases'][0]}" + ("   <- our guess" if fid == guess else ""))
    while True:
        raw = input(f"Pick your degree (1-{len(ids)})" + (" [Enter = our guess]" if guess else "") + ": ").strip()
        if not raw and guess:
            return guess
        if raw.isdigit() and 1 <= int(raw) <= len(ids):
            return ids[int(raw) - 1]
        print("  Please enter a number from the list.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("--all", action="store_true", help="show the checks of not-eligible programmes too")
    ap.add_argument("--gate", type=float, help="GATE score, opens the GATE routes")
    ap.add_argument("--no-questions", action="store_true", help="never ask; gated routes stay closed")
    args = ap.parse_args()

    path = Path(args.profile)
    p = prof.load_profile(path)
    degree_fields = prof.load_degree_fields()
    if not p.get("degree_field_id"):
        if args.no_questions:
            print("ERROR: the profile has no confirmed degree field; run without --no-questions once.")
            return 1
        p["degree_field_id"] = confirm_degree(p, degree_fields)
        path.write_text(json.dumps(p, indent=2, ensure_ascii=False), encoding="utf-8")   # asked once, saved
    # 04.11.2026: the working steps live in pipeline/service.py, shared with the web API.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import service
    try:
        answers = {}
        if not args.no_questions:      # ask only for gates of this field that are not answered yet
            for need, where in service.pending_confirmations(
                    {**p, "confirmations": {**p.get("confirmations", {}),
                                            **({"gate_score": args.gate} if args.gate is not None else {})}}).items():
                print("\nOne more route opens only if you confirm this:")
                for w in where:
                    print("  -", w)
                try:
                    ans = input(CONFIRMATIONS.get(need, f"Confirm {need} (y/n)") + " ").strip().lower()
                except EOFError:
                    ans = ""
                answers[need] = ans.startswith("y")    # no answer = route stays closed
        out = service.check_eligibility(p, confirmations=answers, gate_score=args.gate)
    except (engine.EngineError, service.ServiceError) as e:
        print("ERROR:", e)
        return 1
    student, warnings, results = out["student"], out["warnings"], out["results"]

    print(report.to_text(student, results, warnings, full=args.all))
    stem = path.stem.replace("final_matching_profile_", "")
    out_json = path.with_name(f"eligibility_{stem}.json")
    out_md = path.with_name(f"eligibility_{stem}.md")
    out_json.write_text(json.dumps({"student": {k: v for k, v in student.items() if k != "courses"},
                                    "warnings": warnings, "results": results}, indent=2, ensure_ascii=False), encoding="utf-8")
    out_md.write_text(report.to_markdown(student, results, warnings), encoding="utf-8")
    print(f"\nSaved {out_json.name} and {out_md.name}")
    if not os.environ.get("GPUR_EVAL_RUN"):     # 07.11.2026: every terminal run counts (evaluation runs are in eval_log)
        import run_ledger
        counts = {str(n): sum(1 for r in results if r["list"] == n) for n in (1, 2, 3, 4)}
        run_ledger.record({"source": "terminal", "status": "done", "field": student.get("field"),
                           "degree_field_id": p.get("degree_field_id"), "n_courses": len(p.get("courses") or []) or None,
                           "list_counts": counts})
    return 0


if __name__ == "__main__":
    sys.exit(main())
