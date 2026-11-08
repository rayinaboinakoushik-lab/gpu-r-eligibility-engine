"""
Turns the pipeline's final profile (final_matching_profile_<session>.json) into the student the engine reads.

The engine needs the COURSE LIST (C4 decides per course), not category totals. Stage 4-5 therefore saves
"courses" since 27.10.2026. Older profiles hold only totals and are refused with a clear message.

Student dict the engine reads:
{
  "name": str, "field": "cs"|"eee"|"mechanical"|"civil",
  "degree_field": "information_technology" (an id of data/taxonomy/degree_fields.json),
  "degree_subfield": None,                 # only needed by 10623
  "german_grade": 2.81,
  "total_ects": 184.5,                     # credits on the memo x factor (as before; lateral entry: years 2-4 only)
  "lateral_entry": True,
  "country": "India",
  "courses": [{"id", "title", "ects", "categories": [full category ids]}],
  "excluded_courses": [...],               # shown as "not counted", never matched
  "confirmations": {"gate_score": 640}     # opens gated routes
}
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from gpur.engine import TAXONOMY_DIR, EngineError

FIELDS = ("cs", "eee", "mechanical", "civil")


# ---------------------------------------------------------------------------- degree field
def load_degree_fields() -> dict:
    return json.loads((TAXONOMY_DIR / "degree_fields.json").read_text(encoding="utf-8"))["degree_fields"]


def _norm(text: str) -> str:
    t = text.lower().replace("&", " and ")
    t = re.sub(r"\b(b\.?\s?tech|b\.?\s?e|bachelor of (technology|engineering|science)|b\.?\s?sc|in|of)\b", " ", t)
    return re.sub(r"[^a-z]+", " ", t).strip()


# Order matters: more specific wording first (CSE specialisations before plain CSE, ECE before EEE).
_KEYWORDS = [
    ("cse_specialisations", [r"computer science.*\b(ai|artificial|machine learning|data science|cyber|iot|internet of things)\b",
                             r"\bcse\b.*\b(ai|ml|ds|cyber|iot)\b", r"artificial intelligence and data science", r"\bai and ds\b"]),
    ("information_technology", [r"information technology", r"\bit\b", r"\bcsit\b"]),
    ("computer_science", [r"computer science", r"\bcse\b", r"informatik"]),
    ("electronics_communication", [r"electronics and communication", r"\bece\b", r"telematics", r"instrumentation", r"\beie\b"]),
    ("electrical_electronic_engineering", [r"electrical", r"\beee\b", r"elektrotechnik"]),
    ("mechanical_related", [r"automobile", r"production", r"industrial", r"mechatronics", r"aero"]),
    ("mechanical_engineering", [r"mechanical", r"maschinenbau"]),
    ("civil_related", [r"environmental", r"transportation", r"geoinformatics"]),
    ("civil_engineering", [r"\bcivil\b", r"bauingenieur"]),
    ("business_informatics", [r"business informatics", r"wirtschaftsinformatik"]),
]


def guess_degree_field(program_text: str, degree_fields: dict | None = None) -> str | None:
    """Best guess from the transcript's programme name. Only a GUESS: the student confirms it (run_eligibility)."""
    degree_fields = degree_fields or load_degree_fields()
    n = _norm(program_text or "")
    for fid, info in degree_fields.items():                      # 1. exact alias
        if any(_norm(a) == n for a in info.get("aliases", [])):
            return fid
    for fid, patterns in _KEYWORDS:                              # 2. keywords
        if fid in degree_fields and any(re.search(p, n) for p in patterns):
            return fid
    return None


# ---------------------------------------------------------------------------- profile -> student
def _full_ids(taxonomy: dict) -> tuple[dict, set]:
    atomic = set(taxonomy["category_evidence_status"])
    sums = set(taxonomy.get("aggregate_categories") or {}) | set(taxonomy.get("contextual_categories") or {})
    short = {c.split(".", 1)[1]: c for c in atomic | sums}
    return short, sums


def build_student(profile: dict, taxonomy: dict | None = None) -> tuple[dict, list]:
    """profile = final_matching_profile JSON. Returns (student, warnings). Raises EngineError instead of guessing."""
    field = profile.get("field")
    if field not in FIELDS:
        raise EngineError(f"profile field {field!r} is not one of {FIELDS}")
    if "courses" not in profile:
        raise EngineError("this profile has only category totals (saved before 27.10.2026). "
                          "Run run_stage_4_to_5.py again with the same session ID: it now saves the course list.")
    if taxonomy is None:
        taxonomy = json.loads((TAXONOMY_DIR / f"{field}_taxonomy.json").read_text(encoding="utf-8"))
    short, sums = _full_ids(taxonomy)
    atomic = set(taxonomy["category_evidence_status"])
    warnings = []

    courses = []
    for c in profile["courses"]:
        cats = []
        for x in c.get("categories") or []:
            full = x if ("." in x) else short.get(x, x)
            if full in sums:                                     # rule 6: sums are computed, never assigned
                warnings.append(f"{c.get('title')}: sum category {full} ignored (sums are computed by the engine)")
                continue
            if full not in atomic:
                raise EngineError(f"course {c.get('title')!r}: category {x!r} is not in the {field} taxonomy")
            cats.append(full)
        if not cats:
            continue                                             # non-technical course: counts nowhere
        courses.append({"id": c["course_id"], "title": c.get("title") or c["course_id"],
                        "ects": round(float(c["ects"]), 2), "categories": cats})

    deg = profile.get("degree_field_id")
    if not deg:
        raise EngineError("the profile has no confirmed degree field (degree_field_id); run_eligibility asks for it")
    if deg not in load_degree_fields():
        raise EngineError(f"degree field {deg!r} is not in degree_fields.json")

    conv = profile.get("ects_conversion") or {}
    total = conv.get("memo_ects")                                # as before: credits on the memo x factor
    if total is None:
        if not conv.get("factor") or conv.get("memo_credits") is None:
            raise EngineError("the profile has no credit conversion (ects_conversion.memo_ects); rerun Stage 4-5")
        total = float(conv["memo_credits"]) * float(conv["factor"])
    total = round(float(total), 2)
    if conv.get("basis") != "official":
        warnings.append("course ECTS are estimates (programme total credits not given); "
                        "give the total credits from your regulations for the official values")

    student = {
        "name": profile.get("name") or "student",
        "field": field,
        "degree_field": deg,
        "degree_subfield": profile.get("degree_subfield"),
        "german_grade": float(profile["german_grade"]),
        "total_ects": total,
        "lateral_entry": bool(conv.get("lateral_entry")),
        "ects_factor": float(conv.get("factor") or 0),           # 1 credit in ECTS: tolerance of the degree-total check
        "country": profile.get("country", "India"),
        "courses": courses,
        "excluded_courses": list(profile.get("excluded_courses") or []),
        "confirmations": dict(profile.get("confirmations") or {}),
    }
    return student, warnings


def load_profile(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
