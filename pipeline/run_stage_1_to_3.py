"""
Runs Steps 1-3 of the agreed pipeline and STOPS -- the pause is the point,
not a bug:
  Step 1: transcript + domain + Nmax/Nmin           (file_intake)
  Step 2: extraction + classification                (transcript_extractor + course_classifier)
  Step 3: flag uncertain courses, save a checkpoint,
          print the exact message to hand the student -- then stop.

Nothing continues past this point automatically. Once the student uploads
their excerpt PDF, run run_stage_4_to_5.py with the same SESSION_ID to
resume from exactly where this left off (Steps 4-5).

Run in the same folder as everything else:
    python.exe run_stage_1_to_3.py
"""

from dotenv import load_dotenv
load_dotenv()

from file_intake import build_student_intake, DOMAIN_OPTIONS
from transcript_extractor import extract_transcript_openai
from course_classifier import load_taxonomy, classify_courses_openai, make_course_ids_unique
from knowledge_base import KnowledgeBase
from checkpoint import save_checkpoint
from german_conversion import compute_ects_factor
import confirm_extraction as ce

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


def ask_float(prompt_text: str, default: float) -> float:
    while True:
        raw = input(f"{prompt_text} [{default}]: ").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            print("  Please enter a number (e.g. 10 or 4.0).")


def ask_degree_structure(memo_credits: float) -> dict:
    """
    The three facts the official credit -> ECTS formula needs (60 x years / program total).
    Returns the checkpoint's degree fields, factor included.
    """
    print("\n=== Your degree (for converting credits to ECTS) ===")
    print(f"Credits found on your memo: {memo_credits:g}")
    while True:
        raw = input("How many years is your degree program by regulation (e.g. 4 for B.Tech, 3 for B.Sc)? ").strip()
        try:
            years = float(raw)
            if 2 <= years <= 6:
                break
        except ValueError:
            pass
        print("  Please enter the number of years, e.g. 4.")
    while True:
        raw = input("Did you join through lateral entry (directly into year 2)? (y/n): ").strip().lower()
        if raw in ("y", "yes", "n", "no"):
            lateral = raw.startswith("y")
            break
        print("  Please answer y or n.")
    total = None
    while True:
        raw = input("Total credits of your FULL degree program, as printed in your regulations "
                    "(e.g. 160) -- press Enter if you don't know: ").strip()
        if not raw:
            break
        try:
            total = float(raw)
            if total > 0:
                break
        except ValueError:
            pass
        print("  Please enter a number, or press Enter to skip.")

    ects = compute_ects_factor(years, lateral, memo_credits, total)
    print(f"  1 credit = {ects.factor:.2f} ECTS ({ects.explanation})")
    return {"degree_years": years, "lateral_entry": lateral, "program_total_credits": total,
            "ects_factor": ects.factor, "ects_basis": ects.basis, "ects_explanation": ects.explanation}


def generate_session_id() -> str:
    """
    Internal technical ID only -- links this Stage 1-3 run to its Stage 4-5
    continuation. Not something the student provides or needs to think about;
    auto-generated and printed at the end so it can be reused later.
    """
    import uuid
    return "run_" + uuid.uuid4().hex  # full 32 characters: unique across any number of students


def collect_pre_extraction_inputs():
    """
    Only what's needed BEFORE we can read the transcript. Domain/field is
    intentionally NOT asked here anymore -- asking it blind, before the
    transcript is even read, is exactly how "cs" ended up attached to an
    actual Information Technology student. It's asked right after
    extraction instead, defaulting to the student's own real detected
    program, so a plain Enter confirms real data instead of a guess.
    """
    print("=== Student input ===")
    transcript_path = ask("Path to your transcript file (image or PDF)")
    n_max = ask_float("Best possible grade on your transcript's scale (Nmax)", 10.0)
    n_min = ask_float(
        "Minimum PASSING grade on your transcript's scale (Nmin) -- "
        "NOT zero, the actual pass mark (e.g. 4.0 or 5.0 for a 10-point scale)",
        4.0,
    )
    scale_description = ask(
        "Short description of your grading scale (for the record)",
        f"{n_max}-point CGPA scale, Nmin={n_min}",
    )
    print()
    session_id = generate_session_id()
    return transcript_path, session_id, n_max, n_min, scale_description


def main():
    TRANSCRIPT_PATH, SESSION_ID, N_MAX, N_MIN, SCALE_DESCRIPTION = collect_pre_extraction_inputs()

    # Steps 1-2 (04.11.2026: the working steps live in service.py, shared with the web API)
    import service
    print("Extracting transcript...")
    try:
        extraction, initial = service.read_transcript(TRANSCRIPT_PATH, N_MAX, N_MIN, SCALE_DESCRIPTION)
    except service.ServiceError as e:
        print(f"ERROR: {e}")
        return

    # Step 2b (28.10.2026): show everything that was read; continue only on "fine", else take corrections.
    values, extraction.courses = ce.confirm(initial, extraction.courses)
    ce.apply_to_extraction(extraction, values)

    # Domain selection -- a CONTROLLED choice, not free text. We only have
    # data (taxonomy + program database) for these 4 fields. The student
    # picks the ONE closest match; that single choice scopes the entire
    # run -- classification AND matching happen only inside that one
    # field's files, never a mix. E.g. a Cyber Security or IT student picks
    # "cs" here -- not because their transcript literally says "cs", but
    # because it's the closest available match.
    print(f"\nYour transcript's detected program is: \"{extraction.program}\"")
    print("Choose the field CLOSEST to yours. This decides which course categories and which "
          "Master's programs you are matched against -- only this one field, never a mix.\n")
    for i, (_, label) in enumerate(DOMAIN_OPTIONS, start=1):
        print(f"  {i}. {label}")
    print()
    # No default on purpose: every student must make this choice explicitly.
    while True:
        raw = input(f"Enter a number (1-{len(DOMAIN_OPTIONS)}): ").strip()
        if raw.isdigit() and 1 <= int(raw) <= len(DOMAIN_OPTIONS):
            domain = DOMAIN_OPTIONS[int(raw) - 1][0]
            break
        print(f"  Please enter a number from 1 to {len(DOMAIN_OPTIONS)}.")

    # Credit -> ECTS from the confirmed memo values (option B), rounded up to 1 decimal.
    degree = ce.degree_from_confirmed(values)
    print(f"\n1 credit = {degree['ects_factor']:.1f} ECTS -- {degree['ects_explanation']}")
    gate_score = ce.ask_gate()                               # optional

    print("Classifying courses (knowledge base checked first, only new courses reach the LLM)...")
    try:
        checkpoint = service.classify_and_save(SESSION_ID, extraction, values, domain, N_MAX, N_MIN,
                                               gate_score=gate_score)
    except service.ServiceError as e:
        print(f"\nERROR: {e}")
        return

    from llm_utils import save_usage, usage_line
    save_usage(SESSION_ID, "stage_1_to_3")
    print(usage_line())
    print(f"\nCheckpoint saved: checkpoint_{SESSION_ID}.json")
    print(f"  {len(checkpoint.resolved)} courses resolved at HIGH confidence.")
    print(f"  {len(checkpoint.flagged)} courses flagged -- pipeline stops here.")
    print("\n=== MESSAGE TO SHOW THE STUDENT ===\n")
    print(checkpoint.student_prompt)
    print("\n=== END ===")
    print(f"\nOnce the student's excerpt PDF is ready, run run_stage_4_to_5.py with "
          f"SESSION_ID = \"{SESSION_ID}\" to continue.")


if __name__ == "__main__":
    main()
