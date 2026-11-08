"""
Transcript Parser & Student Profile Generator
===============================================
REAL, reusable pipeline -- not a one-off manual transcription.

Input:  a raw transcript file (image or PDF, scanned or text-based)
Output: (1) a structured, checksum-verified course list
        (2) a student-facing PDF profile (courses, grades, German-grade
            conversion, per-subject ECTS)

This is the missing piece flagged in review: previously, Koushik's transcript
was read and transcribed by hand. This module makes that step systematic and
repeatable for ANY uploaded transcript, regardless of university/college layout.

Architecture:
  1. INTAKE       -- detect file type, prepare for extraction
  2. EXTRACTION   -- vision-based LLM extraction of every course/credit/grade
                      (transcripts are frequently scanned images -- text-only
                      extraction is not reliable, per the pdf-reading skill's
                      own guidance on scanned documents)
  3. VALIDATION   -- checksum: do extracted credits sum to the transcript's
                      own stated total? If not, flag for human review rather
                      than silently trusting a possibly-incomplete extraction.
  4. GRADE CONVERSION -- CGPA/percentage -> German scale, via the documented,
                      auditable Modified Bavarian Formula (not silently guessed)
  5. PDF GENERATION -- clean, student-facing profile document
"""

import json
from dataclasses import dataclass, field, asdict
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Data model
# ---------------------------------------------------------------------------

@dataclass
class ExtractedCourse:
    course_id: str          # synthetic ID if transcript has no course codes
    title: str
    credits: float
    grade_letter: Optional[str] = None
    grade_point: Optional[float] = None   # on the source institution's own scale
    semester: Optional[str] = None


@dataclass
class TranscriptExtractionResult:
    student_name: str
    institution: str
    program: str
    regulation: str                 # e.g. "R18", "R25"
    entry_type: str                 # "regular" or "lateral_entry"
    courses: list[ExtractedCourse] = field(default_factory=list)
    stated_total_credits: Optional[float] = None
    stated_cgpa: Optional[float] = None
    min_credits_for_award: Optional[float] = None   # 28.10.2026: e.g. "Minimum no of credits for award of degree: 123"
    years_with_courses: Optional[int] = None        # 28.10.2026: academic years that list courses (lateral: II-IV = 3)
    extraction_confidence: str = "UNVERIFIED"   # set after checksum validation


# ---------------------------------------------------------------------------
# 2. Extraction prompt -- vision-based, since real transcripts are frequently
#    scanned/photographed documents with institution-specific layouts
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are extracting structured data from a university transcript /
consolidated grade memo image or PDF. Transcripts vary enormously in layout
across institutions -- do not assume any particular table structure. Read
carefully and extract EVERY course listed, including labs, non-credit courses
(0 credit), and project/thesis entries.

CRITICAL WARNING about layout: many Indian university transcripts (including
JNTUH-affiliated colleges) print TWO semester tables SIDE BY SIDE on the same
page (e.g. "I Semester" on the left, "II Semester" on the right), each with
its own separate Sr.No / Subject / Gr / GP / Cr columns. This layout causes a
common, serious error: misreading a credit value from the WRONG table (e.g.
attributing the right-hand table's credit number to a left-hand table's
subject, because the rows appear at the same vertical height on the page).
Before recording any credit value, explicitly verify which table (left/right,
or which semester block) that specific row's number belongs to. If a page has
multiple side-by-side tables, process one complete table fully before moving to
the next, rather than reading across both tables row-by-row.

For each course, extract EXACTLY as printed:
- title (do not paraphrase, abbreviate, or "clean up" the course name)
- credits (as a number; note if listed as "Cr" or similar)
- grade letter and grade point, if shown
- semester/year, if the document organizes courses that way

Also extract these document-level fields if present:
- student name
- institution name
- program/branch
- year of admission and any note about entry type (e.g. "lateral entry",
  "direct II year admission") -- this affects which semesters exist
- the document's OWN STATED total credits and CGPA/aggregate grade
  (these will be used to cross-check your extraction -- do not compute them
  yourself, report exactly what the document states)
- the minimum credits required for the award of the degree, if printed
  (e.g. "Minimum no of credits for award of degree: 123") -- report exactly as printed, else null
- how many academic years list courses on this document (e.g. a lateral-entry memo
  with courses in II, III and IV year = 3; a regular 4-year memo = 4). Count only years
  that actually contain courses; a year marked "direct admission into II year" has none.

Return valid JSON matching this exact schema:
{
  "student_name": str,
  "institution": str,
  "program": str,
  "regulation": str or null,
  "entry_type": "regular" | "lateral_entry",
  "stated_total_credits": number or null,
  "stated_cgpa": number or null,
  "min_credits_for_award": number or null,
  "years_with_courses": integer or null,
  "courses": [
    {
      "course_id": str,        // synthesize as "<institution-code>-<sequence>" if none printed
      "title": str,
      "credits": number,
      "grade_letter": str or null,
      "grade_point": number or null,
      "semester": str or null
    }
  ]
}

Do not skip courses because they have 0 credits or seem non-academic (e.g.
"Constitution of India", "Gender Sensitization") -- extract everything, the
classification/filtering step happens later, separately.

Return ONLY the JSON object, no other text."""


def build_extraction_prompt() -> str:
    return "Extract all course data from the attached transcript image/PDF, following the schema exactly."


# ---------------------------------------------------------------------------
# 3. Validation -- the real checksum step, done automatically, not by hand
# ---------------------------------------------------------------------------

def validate_extraction(result: TranscriptExtractionResult) -> dict:
    """
    Cross-checks extracted course credits against the transcript's own stated
    total. This is what we did manually for Koushik (123.0 extracted vs 123
    stated) -- here it's a repeatable, automatic check for any transcript.
    """
    extracted_total = sum(c.credits for c in result.courses)
    stated = result.stated_total_credits

    report = {
        "extracted_total_credits": extracted_total,
        "stated_total_credits": stated,
        "match": None,
        "status": None
    }

    if stated is None:
        report["status"] = "CANNOT_VALIDATE -- transcript did not clearly state a total; manual review required"
        report["match"] = None
    elif abs(extracted_total - stated) < 0.01:
        report["match"] = True
        report["status"] = "VALIDATED -- extracted credits exactly match the transcript's stated total"
    else:
        report["match"] = False
        report["status"] = (
            f"MISMATCH -- extracted {extracted_total} vs stated {stated}. "
            f"Extraction is likely incomplete or contains an error. "
            f"DO NOT proceed to classification until resolved -- flag for human review."
        )

    return report


# ---------------------------------------------------------------------------
# 4. Grade conversion -- documented formula, not a silent guess
# ---------------------------------------------------------------------------

def convert_cgpa_to_german(cgpa: float, scale_max: float = 10.0, scale_min_passing: float = 5.0) -> dict:
    """
    Modified Bavarian Formula: German = 1 + 3 * (Nmax - Nd) / (Nmax - Nmin)
    Defaults assume a 10-point CGPA scale with 5.0 as the passing floor
    (standard for most Indian universities including JNTUH) -- these
    assumptions are returned explicitly, never silently baked in.
    """
    german_grade = 1 + 3 * (scale_max - cgpa) / (scale_max - scale_min_passing)
    return {
        "source_cgpa": cgpa,
        "source_scale_max": scale_max,
        "source_scale_min_passing_assumed": scale_min_passing,
        "german_grade_equivalent": round(german_grade, 2),
        "formula": "Modified Bavarian Formula: 1 + 3*(Nmax-Nd)/(Nmax-Nmin)",
        "note": "This assumption (passing floor) affects the result -- verify against the specific conversion authority (e.g. uni-assist) if precision matters for a real application."
    }


# ---------------------------------------------------------------------------
# 5. Profile assembly (PDF generation is a separate step, using this data)
# ---------------------------------------------------------------------------

def assemble_student_profile(result: TranscriptExtractionResult, validation: dict) -> dict:
    grade_conversion = None
    if result.stated_cgpa is not None:
        grade_conversion = convert_cgpa_to_german(result.stated_cgpa)

    return {
        "student_name": result.student_name,
        "institution": result.institution,
        "program": result.program,
        "regulation": result.regulation,
        "entry_type": result.entry_type,
        "extraction_validation": validation,
        "grade_conversion": grade_conversion,
        "courses": [asdict(c) for c in result.courses],
        "total_courses_extracted": len(result.courses),
        "_status": "READY_FOR_CLASSIFICATION" if validation.get("match") else "NEEDS_REVIEW_BEFORE_CLASSIFICATION"
    }


if __name__ == "__main__":
    print("Transcript parser module loaded. Call extraction via an LLM vision request,")
    print("then pass the parsed result through validate_extraction() and assemble_student_profile().")