"""
Stage 1/2 checkpoint mechanism -- Steps 3 and 4 of the agreed, ordered pipeline.

Step 3 (save_checkpoint): after classification, any course that did NOT come
back genuinely HIGH confidence (MEDIUM, LOW, or INSUFFICIENT_TITLE_INFO) is
flagged. A checkpoint file records everything -- resolved AND flagged -- plus
a plain-language message telling the student exactly which courses need a
short syllabus excerpt (<=6-7 pages). The pipeline stops here and waits;
nothing continues automatically.

Note: a course that came back HIGH confidence with an EMPTY categories list
(a genuine non-technical course -- language lab, civics, etc.) is NOT
flagged. That is a correctly resolved answer per Rule 5 of the classification
prompt, not a failure requiring evidence.

Step 4 (resume_with_excerpt): once the student returns with that excerpt
PDF, this resolves ONLY the flagged courses against it -- never re-touches
an already-HIGH-confidence course, never re-calls the LLM for anything else.
Courses that remain evidence-insufficient even after the excerpt are
excluded, not guessed, and stay auditable.

The checkpoint persists raw (course_id, title, credits) for EVERY course --
resolved and flagged alike -- so Stage 4/5 can rebuild full credit lookups
for the whole transcript without needing Stage 1-3's in-memory state, even
across a completely separate process or session.
"""

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from transcript_parser import ExtractedCourse
from file_intake import PreparedFile, DOMAIN_OPTIONS
from course_classifier import upgrade_classification_with_excerpt_pdf
from knowledge_base import KnowledgeBase


def is_flagged(classification: dict) -> bool:
    """
    Flagged = not genuinely HIGH confidence. An empty categories list at HIGH
    confidence is a legitimate, resolved answer (a real non-technical
    course) and is NOT flagged.
    """
    return classification.get("confidence") != "HIGH"


@dataclass
class Checkpoint:
    session_id: str
    institution: str
    regulation: str
    degree_field: str
    cgpa: float
    domain: str
    grade_n_max: float
    grade_n_min: float
    resolved: list             # HIGH-confidence classification dicts, untouched
    flagged: list               # non-HIGH classification dicts, pending resolution
    all_courses_raw: list       # {course_id, title, credits} for EVERY course -- resolved and flagged alike
    student_prompt: str
    # Credit -> ECTS conversion (see german_conversion.compute_ects_factor). Optional so
    # checkpoints saved before this existed still load; Stage 4-5 asks for them then.
    degree_years: Optional[float] = None
    lateral_entry: Optional[bool] = None
    program_total_credits: Optional[float] = None
    ects_factor: Optional[float] = None
    ects_basis: Optional[str] = None
    ects_explanation: Optional[str] = None
    # 28.10.2026: optional GATE score (only University of Rostock route B uses it) and the values the
    # student confirmed on the check screen (confirm_extraction.py)
    gate_score: Optional[float] = None
    confirmed_values: Optional[dict] = None


def build_extraction_helper_prompt(flagged: list, domain: str = "") -> str:
    """
    A ready-to-copy prompt the student can hand -- together with their own,
    full official regulations document -- to any AI assistant (Claude,
    ChatGPT, etc.) to self-extract just the small excerpt this system needs,
    without manually hunting through a hundred-page document.

    Rules enforced here that a naive version of this prompt would miss:
      1. Verbatim preservation. Our own classifier requires a genuine
         evidence_quote from the source -- if the student's assistant
         paraphrases or summarizes instead of quoting the original text, the
         excerpt loses exactly the evidentiary value it needs to have.
      2. Explicit "not found" handling. If the uploaded document doesn't
         actually cover a named subject (wrong document, wrong version,
         wrong regulation year), a silent omission would let the student
         think it worked when it didn't.
      3. No branch restriction. Earlier versions of this prompt tried
         restricting the search to the student's own branch first (or even
         only their own branch). Both caused real problems: the same subject
         can genuinely be officially defined in a different branch's section
         (a shared elective), so restricting the search risked reporting a
         real, correct course as NOT FOUND. The current rule is simpler and
         safer: search the WHOLE uploaded document, no restriction by
         branch. If the subject appears in more than one branch's section
         (a real ambiguity, not a search-scope problem), extract ALL of
         them and clearly label each one by which branch/section it came
         from, so the student -- who actually knows what they studied --
         can pick the right one themselves. The student's field (if given)
         is passed along only as helpful context, never as a filter.
    """
    subject_names = [f.get("title", "") for f in flagged if f.get("title")]
    subject_lines = "\n".join(f"[{s}]" for s in subject_names) if subject_names else "[SUBJECT NAME]"
    # domain is the internal key ("cs"); show the student-readable label instead.
    field_label = dict(DOMAIN_OPTIONS).get(domain, domain).split(" (")[0] if domain else ""
    field_line = (
        f"For context, my field of study is: {field_label}\n\n"
        if field_label else ""
    )

    return (
        "I need the official syllabus for only the following subject(s):\n\n"
        f"{subject_lines}\n\n"
        f"{field_line}"
        "From the university documents I have uploaded, find the section/pages that "
        "specifically describe only these subjects and extract their complete "
        "syllabus/course contents (topics or units).\n\n"
        "Search the ENTIRE uploaded document -- do not limit your search to any "
        "particular branch's section. If a subject exists anywhere in the document, "
        "under any branch, extract it.\n\n"
        "If a subject appears under MORE THAN ONE branch's section (the same or a very "
        "similar name defined separately for different branches), do not just pick one -- "
        "extract ALL versions you find, each one clearly labeled with which branch/section "
        "it came from, so I can identify which one I actually studied. Do not silently "
        "choose one version over another.\n\n"
        "Preserve the original wording exactly -- do not summarize or paraphrase.\n"
        "Do not extract information for any other subjects.\n"
        "Do not classify the subjects or add information from outside the uploaded documents.\n"
        "If a named subject cannot be located anywhere in the uploaded document at all, "
        "say so explicitly for that subject rather than omitting it silently.\n"
        "Keep the total result short -- aim for no more than 6-7 pages combined.\n\n"
        "Create a clean PDF containing only the requested subjects' syllabus information, "
        "with the subject name, which branch/section each version was found under, and "
        "source/page references where available."
    )


def build_student_prompt(flagged: list, domain: str = "") -> str:
    if not flagged:
        return (
            "No courses require additional evidence -- every course was classified "
            "with HIGH confidence from its title alone."
        )

    lines = [
        "Some subjects in your transcript could not be confidently verified from the "
        "subject name alone.",
        "",
        "For the subjects listed below, please use the prompt provided together with "
        "your university's official study regulations, syllabus, module handbook, or "
        "other relevant academic documents. The AI will extract the syllabus for only "
        "the subjects we specify and prepare it as a short PDF (aim for 6-7 pages or "
        "less), which you can then upload back to GPU-R.",
        "",
        "Any subject that remains unresolved even after this will be excluded from "
        "your profile rather than guessed -- and that exclusion will be clearly "
        "recorded, not hidden.",
        "",
        "This step is OPTIONAL: if you don't send a syllabus, these subjects are simply not "
        "counted (and listed as 'not counted' in your report). Send one only for subjects "
        "you want counted.",
        "",
        "Subjects requiring syllabus evidence:",
    ]
    for f in flagged:
        reason = f.get("reasoning", "").strip()
        lines.append(f"  - {f.get('title', '')}")
        if reason:
            lines.append(f"      Why: {reason}")
    lines.append("")
    lines.append("How to get this done without hunting through the document by hand:")
    lines.append("  1. Copy the prompt below (between the two lines).")
    lines.append("  2. Open any AI assistant you have access to (Claude, ChatGPT, etc.).")
    lines.append("  3. Paste the prompt, and attach your full official regulations document to that chat.")
    lines.append("  4. Download the PDF it gives you back.")
    lines.append("  5. Upload that PDF here to continue.")
    lines.append("")
    lines.append("--- Prompt to copy into the AI ---")
    lines.append(build_extraction_helper_prompt(flagged, domain=domain))
    lines.append("--- End of prompt ---")
    return "\n".join(lines)


def save_checkpoint(session_id: str, classification_result: list, courses: list[ExtractedCourse],
                     institution: str, regulation: str, degree_field: str, cgpa: float,
                     domain: str, grade_n_max: float, grade_n_min: float,
                     path: Optional[str] = None, degree: Optional[dict] = None) -> Checkpoint:
    """
    Splits classification_result into resolved (HIGH) vs flagged (everything
    else), builds the student-facing prompt, and writes it all -- plus raw
    course data for the ENTIRE transcript -- to a checkpoint file so the
    pipeline can resume later, possibly in a separate process, once the
    student's excerpt PDF arrives.
    """
    title_lookup = {c.course_id: c.title for c in courses}
    credits_lookup = {c.course_id: c.credits for c in courses}

    resolved = [c for c in classification_result if not is_flagged(c)]
    flagged = []
    for c in classification_result:
        if is_flagged(c):
            if not credits_lookup.get(c["course_id"]):
                # A 0-credit course adds nothing to any category, whatever it covers,
                # so the student is never asked for its syllabus. Resolved here only --
                # never saved to the knowledge base (the same title may carry credits
                # at another university).
                resolved.append({**c, "categories": [], "confidence": "HIGH",
                                 "reasoning": "0 credits: cannot add to any category, so no syllabus is needed. "
                                              + str(c.get("reasoning", ""))})
                continue
            entry = dict(c)
            entry["title"] = title_lookup.get(c["course_id"], "")
            flagged.append(entry)

    all_courses_raw = [
        {"course_id": c.course_id, "title": c.title, "credits": c.credits}
        for c in courses
    ]

    checkpoint = Checkpoint(
        session_id=session_id, institution=institution, regulation=regulation,
        degree_field=degree_field, cgpa=cgpa, domain=domain,
        grade_n_max=grade_n_max, grade_n_min=grade_n_min,
        resolved=resolved, flagged=flagged, all_courses_raw=all_courses_raw,
        student_prompt=build_student_prompt(flagged, domain=domain),
        **(degree or {}),
    )

    out_path = Path(path or f"checkpoint_{session_id}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(asdict(checkpoint), f, indent=2)

    return checkpoint


def load_checkpoint(session_id: str, path: Optional[str] = None) -> Checkpoint:
    in_path = Path(path or f"checkpoint_{session_id}.json")
    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Checkpoint(**data)


def resume_with_excerpt(checkpoint: Checkpoint, excerpt_file: PreparedFile, taxonomy: dict,
                         knowledge_base: KnowledgeBase, api_key: Optional[str] = None,
                         model: str = "gpt-6-astra") -> tuple[list, list]:
    """
    Step 4: resolves ONLY the flagged courses against the student's excerpt.
    Never re-touches an already-resolved (HIGH-confidence) course.

    Returns (final_classification_result, excluded_courses):
      - final_classification_result: checkpoint.resolved (untouched) +
        flagged courses that got a genuine HIGH-confidence, evidence-backed
        result from the excerpt.
      - excluded_courses: flagged courses whose evidence remained
        insufficient even after the excerpt -- NOT guessed into a category;
        recorded and auditable, left out of the final profile, per the
        'verify and normalize, or exclude' principle.
    """
    course_lookup = {
        c["course_id"]: ExtractedCourse(course_id=c["course_id"], title=c["title"], credits=c["credits"])
        for c in checkpoint.all_courses_raw
    }

    newly_resolved = []
    still_excluded = []

    for flagged_entry in checkpoint.flagged:
        course_id = flagged_entry["course_id"]
        course = course_lookup.get(course_id)
        if course is None:
            still_excluded.append(flagged_entry)
            continue

        result = upgrade_classification_with_excerpt_pdf(
            course=course, excerpt_file=excerpt_file, taxonomy=taxonomy,
            knowledge_base=knowledge_base, api_key=api_key, model=model,
        )

        # HIGH with categories = resolved; HIGH with an empty list = proven "no category"
        # from the syllabus (also resolved -- it simply adds no credits).
        if result.get("confidence") == "HIGH":
            newly_resolved.append(result)
        else:
            still_excluded.append(result)

    final_classification_result = checkpoint.resolved + newly_resolved
    return final_classification_result, still_excluded


if __name__ == "__main__":
    print("Checkpoint module loaded.")
    print("Use save_checkpoint(...) after Step 2 classification (Step 3), and")
    print("resume_with_excerpt(...) once the student's excerpt PDF arrives (Step 4).")
