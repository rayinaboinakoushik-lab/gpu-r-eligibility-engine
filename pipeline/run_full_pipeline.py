"""
Real end-to-end run -- nothing hardcoded. Every value (CGPA, field, atomic
profile) comes from actually running the pipeline against your real
transcript, not typed in by hand.

Chain:
  file_intake.prepare_file()
    -> transcript_extractor.extract_transcript_openai()   [grade, field, courses]
    -> course_classifier (title-only classification + syllabus resolution)
    -> merge into a stabilized atomic_profile + excluded_courses
    -> german_conversion.build_final_profile()            [grade + ECTS + aggregates]

Run in the same folder as everything else:
    python.exe run_full_pipeline.py
"""

from dotenv import load_dotenv
load_dotenv()

import json

from file_intake import prepare_file
from transcript_extractor import extract_transcript_openai
from course_classifier import (
    load_taxonomy, classify_courses_openai, compute_atomic_profile, attach_credits_for_aggregates,
)
from german_conversion import build_final_profile
from knowledge_base import KnowledgeBase

TRANSCRIPT_PATH = r"C:\Users\koush\Downloads\KOUSHIK.jpeg"  # adjust if needed
TAXONOMY_PATH = "cs_taxonomy.json"


def main():
    # 1. Intake
    prepared = prepare_file(TRANSCRIPT_PATH)
    print("File prepared:", prepared.readable)
    if not prepared.readable:
        print("ERROR:", prepared.error)
        return

    # 2. Extraction -- real values, not typed in
    print("\nExtracting transcript...")
    extraction = extract_transcript_openai(prepared)
    print(f"  student_name = {extraction.student_name}")
    print(f"  program (field) = {extraction.program}")
    print(f"  stated_cgpa = {extraction.stated_cgpa}")
    print(f"  courses extracted = {len(extraction.courses)}")

    if extraction.stated_cgpa is None:
        print("ERROR: stated_cgpa was not extracted -- cannot proceed to grade conversion.")
        return
    if not extraction.program:
        print("ERROR: program/field was not extracted -- cannot proceed to field gate.")
        return

    # 3. Classification -- real values, not typed in.
    #    Knowledge-base-first: checks verified_knowledge_base.json before any
    #    LLM call; only genuinely new courses reach the model; new HIGH-
    #    confidence results get recorded back for reuse by future students.
    print("\nLoading taxonomy and classifying courses...")
    taxonomy = load_taxonomy(TAXONOMY_PATH)
    kb = KnowledgeBase()  # loads verified_knowledge_base.json if it exists
    institution = extraction.institution or "UNKNOWN_INSTITUTION"
    regulation = extraction.regulation or "UNKNOWN_REGULATION"
    classification_result = classify_courses_openai(
        extraction.courses, taxonomy,
        institution=institution, regulation=regulation, knowledge_base=kb,
    )
    kb_stats = kb.stats()
    print(f"  Knowledge base: {kb_stats['total_verified_courses']} verified courses on file "
          f"({kb_stats['from_title_only']} title-only, {kb_stats['from_student_excerpt']} excerpt-verified).")

    uncertain = [c for c in classification_result if c["confidence"] == "MEDIUM"]
    high_confidence = [c for c in classification_result if c["confidence"] == "HIGH"]

    print(f"  {len(high_confidence)} of {len(extraction.courses)} classified HIGH confidence from title alone.")
    print(f"  {len(uncertain)} need student-guided syllabus verification (excluded from this run's profile).")
    for u in uncertain:
        print(f"    UNCERTAIN: {u['course_id']} -- {u.get('categories', [])} (confidence: {u['confidence']})")

    # 4. Build atomic profile from HIGH-confidence courses only
    #    (MEDIUM-confidence courses excluded until resolved via the student's
    #    own syllabus excerpt -- same rule as merge_final_profile.py)
    high_conf_course_ids = {c["course_id"] for c in high_confidence}
    courses_for_profile = [c for c in extraction.courses if c.course_id in high_conf_course_ids]
    atomic_profile = compute_atomic_profile(high_confidence, courses_for_profile)

    excluded_courses = [
        {"course_id": u["course_id"], "categories": u.get("categories", []), "confidence": u["confidence"]}
        for u in uncertain
    ]

    # 5. German conversion -- real values flow in, nothing retyped.
    #    Only HIGH-confidence courses feed the aggregate union computation,
    #    same as the atomic profile above -- MEDIUM/excluded courses stay out
    #    of every total until resolved via student excerpt.
    print("\nBuilding final matching-ready profile...")
    aggregate_input = attach_credits_for_aggregates(high_confidence, courses_for_profile)
    final_profile = build_final_profile(
        degree_field=extraction.program,
        cgpa=extraction.stated_cgpa,
        atomic_profile_native=atomic_profile,
        taxonomy=taxonomy,
        course_classifications=aggregate_input,  # correct union-of-unique-course-IDs path
        excluded_courses=excluded_courses,
        grade_n_max=10.0,
        grade_n_min=4.0,  # still a flagged assumption -- confirm against JNTUH's own scale
        ects_ratio=1.5,
    )

    print("\n=== FINAL MATCHING-READY PROFILE (real, derived end-to-end) ===")
    print("Degree field :", final_profile.degree_field)
    print("German grade :", final_profile.german_grade)
    print("\nAtomic profile (ECTS):")
    for cat, val in final_profile.atomic_profile_ects.items():
        print(f"  {cat}: {val}")
    print("\nAggregate profile (ECTS):")
    for agg, val in final_profile.aggregate_profile_ects.items():
        print(f"  {agg}: {val}")
    print("\nExcluded courses (pending review):")
    for c in final_profile.excluded_courses:
        print(f"  {c}")
    print("\n=== WARNINGS ===")
    for w in final_profile.warnings:
        print("-", w)

    with open("final_matching_profile.json", "w", encoding="utf-8") as f:
        json.dump({
            "degree_field": final_profile.degree_field,
            "german_grade": final_profile.german_grade,
            "atomic_profile_ects": final_profile.atomic_profile_ects,
            "aggregate_profile_ects": final_profile.aggregate_profile_ects,
            "excluded_courses": final_profile.excluded_courses,
            "warnings": final_profile.warnings,
        }, f, indent=2)
    print("\nSaved to final_matching_profile.json")


if __name__ == "__main__":
    main()
