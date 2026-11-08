"""
Runs Steps 4-5 once the student has uploaded their excerpt PDF -- resumes
EXACTLY where run_stage_1_to_3.py stopped, using the saved checkpoint. Only
the flagged courses are ever touched here; anything already resolved at HIGH
confidence in Stage 1-3 is never re-sent to the LLM.

  Step 4: resolve flagged courses against the excerpt, or exclude -- never guess
  Step 5: assemble the final, matching-engine-ready profile (German grade + ECTS)

Run in the same folder as everything else, after run_stage_1_to_3.py has
produced checkpoint_<SESSION_ID>.json and the student has provided their
excerpt PDF:
    python.exe run_stage_4_to_5.py
"""

from dotenv import load_dotenv
load_dotenv()

import json
from dataclasses import asdict

from file_intake import prepare_file
from course_classifier import load_taxonomy, compute_atomic_profile, attach_credits_for_aggregates
from german_conversion import build_final_profile
from knowledge_base import KnowledgeBase
from checkpoint import load_checkpoint, resume_with_excerpt
from transcript_parser import ExtractedCourse
from run_stage_1_to_3 import ask_degree_structure

DOMAIN_TAXONOMY_PATHS = {
    "cs": "cs_taxonomy.json",
    "civil": "civil_taxonomy.json",
    "mechanical": "mechanical_taxonomy.json",
    "eee": "eee_taxonomy.json",
}


def ask(prompt_text: str, default: str = "") -> str:
    """
    Asks the student a question in the console. With a default, pressing Enter
    keeps it. Without one, the question is required and is asked again until
    answered -- used for anything personal (file paths, session ID), which must
    never fall back to someone else's value.
    """
    shown = f" [{default}]" if default else ""
    while True:
        # strip() twice: surrounding spaces, then the quotes Windows "Copy as path" adds
        answer = input(f"{prompt_text}{shown}: ").strip().strip('"\'').strip()
        if answer:
            return answer
        if default:
            return default
        print("  This is required.")


def main():
    print("=== Student input ===")
    SESSION_ID = ask("Session ID (printed at the end of run_stage_1_to_3.py)")
    try:
        checkpoint = load_checkpoint(SESSION_ID)
    except FileNotFoundError:
        print(f"ERROR: no saved session '{SESSION_ID}' found. Check the ID printed at the end of run_stage_1_to_3.py.")
        return

    # Asked only when needed. OPTIONAL since 29.10.2026 (Koushik): Enter skips it, and the flagged
    # courses are then NOT counted and listed openly as "not counted (no syllabus given)" -- never guessed.
    EXCERPT_PATH = ""
    if checkpoint.flagged:
        titles = ", ".join(f.get("title", f["course_id"]) for f in checkpoint.flagged)
        print(f"{len(checkpoint.flagged)} course(s) need syllabus evidence: {titles}")
        print("Give the syllabus PDF to have them counted, or press Enter to skip "
              "(skipped courses are not counted and are listed in your report).")
        EXCERPT_PATH = input("Path to your syllabus excerpt PDF [Enter = skip]: ").strip().strip('"\'').strip()
    print()

    # Same taxonomy the student's domain was scoped to in Stage 1-3 -- never
    # hardcoded to "cs" regardless of what was actually chosen there.
    # 04.11.2026: the working steps live in service.py, shared with the web API.
    import service
    if checkpoint.flagged and not EXCERPT_PATH:
        print(f"Skipped: {len(checkpoint.flagged)} course(s) not counted (no syllabus given).")
    excerpt_file = None
    if checkpoint.flagged and EXCERPT_PATH:
        excerpt_file = prepare_file(EXCERPT_PATH)
        if not excerpt_file.readable:
            print("ERROR: could not read excerpt file:", excerpt_file.error)
            return
        print(f"Resolving {len(checkpoint.flagged)} flagged course(s) against the student's excerpt...")
    if not checkpoint.flagged:
        print("No flagged courses were saved in this checkpoint -- nothing to resolve via excerpt.")

    # Credit -> ECTS factor, decided in Stage 1-3. Checkpoints saved before that question
    # existed don't have it, so it is asked here once and written back to the checkpoint.
    if not checkpoint.ects_factor:
        all_courses = [ExtractedCourse(**c) for c in checkpoint.all_courses_raw]
        degree = ask_degree_structure(sum(c.credits or 0 for c in all_courses))
        for k, v in degree.items():
            setattr(checkpoint, k, v)
        with open(f"checkpoint_{SESSION_ID}.json", "w", encoding="utf-8") as f:
            json.dump(asdict(checkpoint), f, indent=2)

    try:
        out = service.build_profile(checkpoint, excerpt_file=excerpt_file)
    except service.ServiceError as e:
        print(f"ERROR: {e}")
        return
    if excerpt_file is not None:
        print(f"  {out['newly_resolved']} of {len(checkpoint.flagged)} flagged courses resolved via excerpt evidence.")
        print(f"  {len(out['excluded'])} remain excluded (insufficient evidence even after the excerpt).")
        for e in out["excluded"]:
            print(f"    EXCLUDED: {e['course_id']} -- {e.get('reasoning', '')}")
    factor = checkpoint.ects_factor
    print(f"\n1 credit = {factor:.2f} ECTS -- {checkpoint.ects_explanation}")
    for title, rule in out["lab_rule"]:
        print(f"  Lab rule: {title} -> {rule}")
    print("\nBuilding final matching-ready profile...")
    final_profile = out["final_profile"]
    memo_credits = out["profile"]["ects_conversion"]["memo_credits"]

    print("\n=== FINAL MATCHING-READY PROFILE ===")
    print("Field        :", checkpoint.domain, "(matched only against this field's program file)")
    print("Degree field :", final_profile.degree_field)
    print("German grade :", final_profile.german_grade)
    print(f"ECTS         : 1 credit = {factor:.2f} ECTS ({checkpoint.ects_basis}); "
          f"{memo_credits:g} credits on the memo = {memo_credits * factor:.1f} ECTS")
    print("\nAtomic profile (ECTS):")
    for cat, val in final_profile.atomic_profile_ects.items():
        print(f"  {cat}: {val}")
    print("\nAggregate/contextual profile (ECTS):")
    for agg, val in final_profile.aggregate_profile_ects.items():
        print(f"  {agg}: {val}")
    print("\nExcluded courses (auditable, never guessed):")
    for c in final_profile.excluded_courses:
        print(f"  {c}")
    print("\n=== WARNINGS ===")
    for w in final_profile.warnings:
        print("-", w)

    with open(f"final_matching_profile_{SESSION_ID}.json", "w", encoding="utf-8") as f:
        json.dump(out["profile"], f, indent=2)
    from llm_utils import save_usage, usage_line
    save_usage(SESSION_ID, "stage_4_to_5")
    print(usage_line())
    print(f"\nSaved to final_matching_profile_{SESSION_ID}.json")


if __name__ == "__main__":
    main()
