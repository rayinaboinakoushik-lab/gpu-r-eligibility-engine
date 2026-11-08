"""
GPU-R service layer (04.11.2026): the working steps of the pipeline as plain functions, with no questions and
no printing. The terminal scripts (run_stage_1_to_3.py, run_stage_4_to_5.py, run_eligibility.py) and the web
API (api/main.py) both call these, so both ways in always give the same result.

Nothing here decides anything new: every line was moved from the scripts unchanged in logic (reading,
check-screen values, classification, lab rule, checkpoint, syllabus step, final profile, engine).

    read_transcript      transcript bytes/path + Nmax/Nmin  -> extraction + check-screen values
    apply_course_corrections   the student's title/credit corrections (the check screen's c<number>)
    classify_and_save    confirmed values + field          -> checkpoint (resolved / flagged courses)
    build_profile        checkpoint + optional syllabus    -> final matching profile (dict, as saved to JSON)
    pending_confirmations / check_eligibility             -> engine results (no LLM)
"""
from __future__ import annotations

import json
import sys
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))          # pipeline modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))      # repo root (gpur)

import confirm_extraction as ce                                    # noqa: E402
from checkpoint import Checkpoint, save_checkpoint, resume_with_excerpt   # noqa: E402
from course_classifier import (load_taxonomy, classify_courses_openai, make_course_ids_unique,  # noqa: E402
                               compute_atomic_profile, attach_credits_for_aggregates)
from file_intake import build_student_intake, PreparedFile, VALID_DOMAINS   # noqa: E402
from german_conversion import build_final_profile                  # noqa: E402
from knowledge_base import KnowledgeBase                           # noqa: E402
from lab_rule import apply_lab_rule                                # noqa: E402
from paths import taxonomy_path as _resolve                        # noqa: E402
from transcript_extractor import extract_transcript_openai         # noqa: E402
from transcript_parser import ExtractedCourse, TranscriptExtractionResult   # noqa: E402

DOMAIN_TAXONOMY_PATHS = {
    "cs": "cs_taxonomy.json",
    "civil": "civil_taxonomy.json",
    "mechanical": "mechanical_taxonomy.json",
    "eee": "eee_taxonomy.json",
}


class ServiceError(Exception):
    """A step cannot continue; the message says why in plain words (never a guess instead)."""


def new_session_id() -> str:
    return "run_" + uuid.uuid4().hex


# --------------------------------------------------------------------------------------------- step 1-2
def read_transcript(transcript, n_max: float, n_min: float, scale_description: Optional[str] = None,
                    filename: Optional[str] = None) -> tuple[TranscriptExtractionResult, dict]:
    """Reads the transcript (path or uploaded bytes). Returns (extraction, values for the check screen)."""
    intake = build_student_intake(transcript, "", n_max, n_min,
                                  scale_description or f"{n_max}-point CGPA scale, Nmin={n_min}", filename=filename)
    if not intake.ready_for_step2:
        raise ServiceError("Cannot proceed -- Step 1 intake not ready: " + "; ".join(intake.warnings))
    extraction = extract_transcript_openai(intake.transcript)
    if not extraction.courses:
        raise ServiceError("no courses could be read from the transcript. Cannot proceed.")
    # Each course must have its own ID (a misread code can appear twice on a memo).
    extraction.courses = make_course_ids_unique(extraction.courses)
    return extraction, ce.initial_values(extraction)


def missing_values(values: dict) -> list:
    """Required check-screen values that are still empty (CGPA, years studied, credits for award)."""
    return ce._missing(values)


def apply_course_corrections(extraction: TranscriptExtractionResult, corrections: list) -> None:
    """[{"index": 1-based, "title"?: str, "credits"?: number}] -- the check screen's c<number> corrections."""
    for c in corrections or []:
        i = int(c["index"])
        if not 1 <= i <= len(extraction.courses):
            raise ServiceError(f"course correction index {i} is outside 1-{len(extraction.courses)}")
        course = extraction.courses[i - 1]
        if c.get("title"):
            course.title = str(c["title"]).strip()
        if c.get("credits") is not None:
            course.credits = float(c["credits"])


def extraction_to_dict(extraction: TranscriptExtractionResult) -> dict:
    return asdict(extraction)


def extraction_from_dict(d: dict) -> TranscriptExtractionResult:
    d = dict(d)
    d["courses"] = [ExtractedCourse(**c) for c in d.get("courses", [])]
    return TranscriptExtractionResult(**d)


# --------------------------------------------------------------------------------------------- step 2-3
def classify_and_save(session_id: str, extraction: TranscriptExtractionResult, values: dict, domain: str,
                      n_max: float, n_min: float, gate_score: Optional[float] = None,
                      checkpoint_path: Optional[str] = None, kb: Optional[KnowledgeBase] = None) -> Checkpoint:
    """Confirmed values + chosen field -> classification (knowledge base first, then LLM), lab rule, checkpoint."""
    if domain not in VALID_DOMAINS:
        raise ServiceError(f"field must be one of {sorted(VALID_DOMAINS)}, got {domain!r}")
    missing = missing_values(values)
    if missing:
        raise ServiceError("required values are still missing: " + ", ".join(missing))
    ce.apply_to_extraction(extraction, values)

    # Credit -> ECTS from the confirmed memo values (option B), rounded up to 1 decimal.
    degree = ce.degree_from_confirmed(values)
    degree["gate_score"] = gate_score
    degree["confirmed_values"] = values

    # Taxonomy file is picked BY the chosen field -- never hardcoded; a missing file refuses cleanly.
    tax_file = DOMAIN_TAXONOMY_PATHS[domain]
    if not _resolve(tax_file).exists():
        raise ServiceError(f"no taxonomy file exists yet for '{domain}' ({tax_file}). Refusing rather than "
                           f"misclassifying with another field's taxonomy.")
    taxonomy = load_taxonomy(tax_file)
    kb = kb or KnowledgeBase()

    classification_result = classify_courses_openai(extraction.courses, taxonomy, knowledge_base=kb)
    # 31.10.2026: lab rule before flagging -- an unsure lab whose theory course(s) are sure follows them
    classification_result = apply_lab_rule(classification_result,
                                           {c.course_id: c.title for c in extraction.courses})
    return save_checkpoint(
        session_id=session_id, classification_result=classification_result,
        courses=extraction.courses, institution=extraction.institution or "UNKNOWN_INSTITUTION",
        regulation=extraction.regulation or "UNKNOWN_REGULATION",
        degree_field=extraction.program, cgpa=extraction.stated_cgpa, domain=domain,
        grade_n_max=n_max, grade_n_min=n_min, degree=degree, path=checkpoint_path,
    )


# --------------------------------------------------------------------------------------------- step 4-5
def build_profile(checkpoint: Checkpoint, excerpt_file: Optional[PreparedFile] = None,
                  kb: Optional[KnowledgeBase] = None) -> dict:
    """
    Syllabus step (resolve flagged courses with the excerpt, or skip: then they are NOT counted) + final
    matching profile. Returns {"profile": <dict exactly as saved to final_matching_profile_*.json>,
    "final_profile": <FinalMatchingProfile>, "newly_resolved": n, "excluded": [...], "lab_rule": [...]}.
    """
    tax_file = DOMAIN_TAXONOMY_PATHS.get(checkpoint.domain)
    if tax_file is None:
        raise ServiceError(f"checkpoint domain '{checkpoint.domain}' has no known taxonomy mapping.")
    if not _resolve(tax_file).exists():
        raise ServiceError(f"no taxonomy file exists for '{checkpoint.domain}' ({tax_file}). "
                           f"Cannot resume this session's classification consistently.")
    if not checkpoint.ects_factor:
        raise ServiceError("this checkpoint has no credit -> ECTS factor (saved before 28.10.2026); "
                           "run run_stage_4_to_5.py once in the terminal for it")
    taxonomy = load_taxonomy(tax_file)
    kb = kb or KnowledgeBase()

    newly_resolved = 0
    if not checkpoint.flagged:
        final_classification_result, excluded = checkpoint.resolved, []
    elif excerpt_file is None:
        # OPTIONAL since 29.10.2026 (Koushik): skipped courses are NOT counted and are listed openly.
        final_classification_result = checkpoint.resolved
        excluded = [{**f, "categories": [], "reasoning": "not counted: no syllabus given"} for f in checkpoint.flagged]
    else:
        if not excerpt_file.readable:
            raise ServiceError(f"could not read excerpt file: {excerpt_file.error}")
        final_classification_result, excluded = resume_with_excerpt(
            checkpoint=checkpoint, excerpt_file=excerpt_file, taxonomy=taxonomy, knowledge_base=kb)
        newly_resolved = len(final_classification_result) - len(checkpoint.resolved)

    all_courses = [ExtractedCourse(**c) for c in checkpoint.all_courses_raw]
    factor = checkpoint.ects_factor
    final_classification_result = apply_lab_rule(final_classification_result,
                                                 {c.course_id: c.title for c in all_courses})
    lab_notes = [(next((c.title for c in all_courses if c.course_id == r["course_id"]), r["course_id"]), r["lab_rule"])
                 for r in final_classification_result if r.get("lab_rule")]

    atomic_profile = compute_atomic_profile(final_classification_result, all_courses)
    aggregate_input = attach_credits_for_aggregates(final_classification_result, all_courses)
    excluded_summary = [
        {"course_id": e["course_id"],
         "title": next((c.title for c in all_courses if c.course_id == e["course_id"]), ""),
         "categories": e.get("categories", []), "confidence": e.get("confidence"),
         "ects": round(next((c.credits for c in all_courses if c.course_id == e["course_id"]), 0) * factor, 2)}
        for e in excluded
    ]
    final_profile = build_final_profile(
        degree_field=checkpoint.degree_field, cgpa=checkpoint.cgpa, atomic_profile_native=atomic_profile,
        taxonomy=taxonomy, course_classifications=aggregate_input, excluded_courses=excluded_summary,
        grade_n_max=checkpoint.grade_n_max, grade_n_min=checkpoint.grade_n_min, ects_ratio=factor,
    )
    if checkpoint.ects_basis != "official":
        final_profile.warnings.append(checkpoint.ects_explanation)
    memo_credits = sum(c.credits or 0 for c in all_courses)

    def credits_of(cid):
        return next((c.credits for c in all_courses if c.course_id == cid), 0) or 0

    profile = {
        "field": checkpoint.domain,
        "name": (checkpoint.confirmed_values or {}).get("student_name") or "student",
        "confirmations": ({"gate_score": checkpoint.gate_score} if checkpoint.gate_score is not None else {}),
        "degree_field": final_profile.degree_field,
        "german_grade": final_profile.german_grade,
        "ects_conversion": {
            "factor": factor, "basis": checkpoint.ects_basis, "explanation": checkpoint.ects_explanation,
            "degree_years": checkpoint.degree_years, "lateral_entry": checkpoint.lateral_entry,
            "program_total_credits": checkpoint.program_total_credits,
            "memo_credits": memo_credits, "memo_ects": round(memo_credits * factor, 2),
        },
        # 27.10.2026: the course list the engine counts with; excluded courses stay in excluded_courses.
        "courses": [
            {"course_id": r["course_id"],
             "title": next((c.title for c in all_courses if c.course_id == r["course_id"]), ""),
             "credits": credits_of(r["course_id"]),
             "ects": round(credits_of(r["course_id"]) * factor, 2),
             "categories": r.get("categories", []),
             "confidence": r.get("confidence")}
            for r in final_classification_result
        ],
        "atomic_profile_ects": final_profile.atomic_profile_ects,
        "aggregate_profile_ects": final_profile.aggregate_profile_ects,
        "excluded_courses": final_profile.excluded_courses,
        "warnings": final_profile.warnings,
    }
    return {"profile": profile, "final_profile": final_profile, "newly_resolved": newly_resolved,
            "excluded": excluded, "lab_rule": lab_notes}


# --------------------------------------------------------------------------------------------- step 6
def degree_options(profile: dict) -> dict:
    """{"options": [degree field ids], "guess": id or None} for the degree question."""
    from gpur import profile as prof
    fields = prof.load_degree_fields()
    return {"options": list(fields), "guess": prof.guess_degree_field(profile.get("degree_field", ""), fields)}


def pending_confirmations(profile: dict) -> dict:
    """Gated routes of this field that still need a yes/no from the student: {need: [where, ...]}."""
    from gpur import engine, profile as prof
    if not profile.get("degree_field_id"):          # the gates do not depend on the degree; any valid id works here
        d = degree_options(profile)
        profile = {**profile, "degree_field_id": d["guess"] or d["options"][0]}
    student, _ = prof.build_student(profile)
    fd = engine.load_field(student["field"])
    gates = fd.config.get("gated_routes", {})
    asked = {}
    for rid in sorted(r for r in fd.records if r in gates):
        need = gates[rid]["needs"]
        if need == "gate_score" or need in student["confirmations"]:
            continue
        rec = fd.records[rid]
        asked.setdefault(need, []).append(f"{rec['program']} ({rec['university']}): {gates[rid]['why']}")
    return asked


def check_eligibility(profile: dict, confirmations: Optional[dict] = None, gate_score: Optional[float] = None) -> dict:
    """Runs the engine on every programme of the student's field (no LLM). Unanswered gates stay closed."""
    from gpur import engine, profile as prof, report
    p = json.loads(json.dumps(profile))
    if gate_score is not None:
        p.setdefault("confirmations", {})["gate_score"] = gate_score
    try:
        student, warnings = prof.build_student(p)
        fd = engine.load_field(student["field"])
        for need, ans in (confirmations or {}).items():
            student["confirmations"][need] = bool(ans)
        results = engine.evaluate_field(student, fd)
    except engine.EngineError as e:
        raise ServiceError(str(e)) from e
    return {"student": student, "warnings": warnings, "results": results,
            "markdown": report.to_markdown(student, results, warnings)}
