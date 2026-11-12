"""
RAG lab, step 1: turn the 228 frozen programme records into retrievable text chunks.

Design (10.11.2026):
- One chunk per requirement section (grade, each subject requirement, conditions, English, ...),
  not fixed-size character windows: a section is one rule, so a retrieved chunk is one rule.
- Every chunk starts with a context header (programme, university, field, section). Without it,
  "at least 18 ECTS in analysis and linear algebra" would not say WHICH programme it belongs to.
- Every chunk keeps its source (regulation URL) as metadata, so answers can cite it.
This module only reads data; it never changes the records and is not used by the rule engine.
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

FROZEN_GLOB = "data/frozen/GPU-R_*_FROZEN_*.json"
FIELD_NAMES = {
    "computer_science": "Computer Science",
    "electrical_electronic_engineering": "Electrical/Electronic Engineering",
    "mechanical_engineering": "Mechanical Engineering",
    "civil_engineering": "Civil Engineering",
}


def load_records(root: str | Path = ".") -> list[dict]:
    files = sorted(glob.glob(str(Path(root) / FROZEN_GLOB)))
    records: list[dict] = []
    for f in files:
        records.extend(json.loads(Path(f).read_text(encoding="utf-8")))
    return records


def _txt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "; ".join(_txt(v) for v in value if _txt(v))
    if isinstance(value, dict):
        parts = [f"{k}: {_txt(v)}" for k, v in value.items() if _txt(v) and not k.startswith("_")]
        return "; ".join(parts)
    return str(value)


def _source(rec: dict) -> str:
    src = rec.get("official_sources") or {}
    reg = src.get("admission_regulation") or {}
    if isinstance(reg, dict) and reg.get("url"):
        return reg["url"]
    return src.get("program_page") or ""


def record_chunks(rec: dict) -> list[dict]:
    """All chunks of one record. Each chunk: id, record_id, section, text, metadata."""
    program, uni = rec.get("program", ""), rec.get("university", "")
    field = FIELD_NAMES.get(rec.get("_domain", ""), rec.get("_domain", ""))
    header = f"Programme: {program} | University: {uni} | Field: {field}"
    source = _source(rec)
    out: list[dict] = []

    def add(section: str, body: str, item: int | None = None):
        body = body.strip()
        if not body:
            return
        cid = f"{rec['id']}:{section}" + (f":{item}" if item is not None else "")
        out.append({
            "id": cid, "record_id": str(rec["id"]), "section": section, "item": item,
            "text": f"{header}\nSection: {section.replace('_', ' ')}\n{body}",
            "program": program, "university": uni, "field": rec.get("_domain", ""), "source_url": source,
        })

    src = rec.get("official_sources") or {}
    reg = src.get("admission_regulation") or {}
    add("overview", "\n".join(x for x in [
        f"Official programme page: {src.get('program_page', '')}",
        f"Admission regulation: {reg.get('title', '')} ({reg.get('url', '')})" if isinstance(reg, dict) else "",
        f"Intake and deadlines: {_txt(rec.get('logistics'))}",
        f"Admission type: {_txt(rec.get('admission_type'))}",
    ] if x.split(': ', 1)[-1].strip()))

    adf = rec.get("accepted_degree_fields") or {}
    add("accepted_degrees", f"Accepted bachelor fields: {', '.join(adf.get('primary_fields') or []) or 'not specified'}\n"
                            f"{_txt(adf.get('note'))}")

    gr = rec.get("grade_requirement") or {}
    add("grade", f"Grade rule: {rec.get('gpa_rule_type', '')}; minimum German grade: "
                 f"{gr.get('value') if gr.get('value') is not None else 'none'}\n{_txt(gr.get('note'))}")

    scr = rec.get("subject_credit_requirements") or {}
    for i, it in enumerate(scr.get("items") or []):
        need = "presence of the subject only" if it.get("requires_subject_presence_only") else f"at least {it.get('min_ects')} ECTS"
        cats = [it.get("canonical_category")] + list(it.get("covered_categories") or [])
        add("subject_requirement", f"Requirement item {i}: {need}\nRegulation wording: {_txt(it.get('raw_label'))}\n"
                                   f"Subject areas: {', '.join(c for c in cats if c)}", item=i)
    if _txt(scr.get("note")):
        add("subject_notes", _txt(scr.get("note")))

    ca = rec.get("conditional_admission") or {}
    add("conditional_admission", f"Conditional admission allowed: {'yes' if ca.get('allowed') else 'no'}; "
                                 f"maximum missing ECTS: {ca.get('max_ects') if ca.get('max_ects') is not None else 'not specified'}\n"
                                 f"{_txt(ca.get('mechanism'))}")
    if rec.get("minimum_total_ects") is not None:
        add("total_credits", f"Minimum total ECTS of the bachelor degree: {rec['minimum_total_ects']}")

    sel = rec.get("subsequent_selection_criteria_display") or {}
    adm = rec.get("admission_type") or {}
    add("selection", f"Selection step after the basic requirements: {'yes' if sel.get('has_subsequent_hurdles') else 'no'}\n"
                     f"Restricted admission (Zulassungsbeschraenkung): {'yes' if adm.get('restricted') else 'no'}; "
                     f"numerus clausus: {'yes' if adm.get('numerus_clausus') else 'no'}\n"
                     f"{_txt(sel.get('descriptive_notes'))}")

    add("english", _txt(rec.get("language_english")))
    add("german", _txt(rec.get("language_german")))
    add("aps", _txt(rec.get("aps_certificate")))
    add("tests", _txt(rec.get("standardized_test_requirements")))
    add("other_documents", _txt(rec.get("other_requirements")))
    add("practical_experience", _txt(rec.get("practical_experience_requirement")))
    return out


def all_chunks(root: str | Path = ".") -> list[dict]:
    return [c for r in load_records(root) for c in record_chunks(r)]


if __name__ == "__main__":
    chunks = all_chunks()
    from collections import Counter
    print(f"{len(chunks)} chunks from {len(load_records())} records")
    print(Counter(c["section"] for c in chunks).most_common())
