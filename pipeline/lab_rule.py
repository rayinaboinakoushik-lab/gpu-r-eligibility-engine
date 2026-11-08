"""
Taxonomy rule 7 in code (30.10.2026): "LABS follow their theory course: a lab gets the categories of the
subject it practises." The LLM is told this, but did not always follow it (real run 29.10: Compiler
Construction Lab lost theoretical CS). This makes it deterministic.

Matching, for every course whose title ends in LAB / LABORATORY / PRACTICAL(S) ("WORKSHOP" is not used: "IT WORKSHOP" would shrink to "IT"):
  1. exact:   the title without "LAB" equals another (non-lab) course title -> that course
  2. contained: it appears inside exactly one non-lab title (e.g. COMPILER CONSTRUCTION LAB ->
     PRINCIPLES OF COMPILER CONSTRUCTION)
  3. combined lab: split on AND / & and match each part with 1, then 2
     (COMPUTER NETWORKS AND WEB PROGRAMMING LAB -> DATA COMMUNICATION AND COMPUTER NETWORKS + WEB PROGRAMMING)
A matched lab gets the UNION of its theory courses' categories (its own LLM categories are replaced).
An unmatched lab keeps what the classifier gave it. Two candidates in step 2 = ambiguous -> unchanged.

31.10.2026 (Koushik): the rule also applies to labs the classifier was NOT sure about. If every matched
theory course is HIGH, the lab becomes HIGH with their categories, so no syllabus is asked for it
(found on a JNTUK memo: METROLOGY & INSTRUMENTATION LAB). Unmatched unsure labs stay flagged.
"""
from __future__ import annotations

import re

_LAB_SUFFIX = re.compile(r"\s*(LABORATORY|LAB|PRACTICALS?)\s*$")


def _norm(title: str) -> str:
    t = (title or "").upper().replace("&", " AND ")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9+# ]", " ", t)).strip()


def _base(title: str):
    n = _norm(title)
    if not _LAB_SUFFIX.search(n):
        return None
    return _LAB_SUFFIX.sub("", n).strip()


def _find(part: str, theory: dict):
    if part in theory:
        return [part]
    hits = [t for t in theory if re.search(rf"(^| ){re.escape(part)}( |$)", t)]
    return hits if len(hits) == 1 else []


# 04.11.2026 (Koushik approved): a lab named only after a general skill is never matched to a theory course
# (batch 1, S18: LANGUAGE LABORATORY was matched to FORMAL LANGUAGE & AUTOMATA THEORY -> theoretical CS).
# Blocked only when EVERY word is a skill word and at least one marker word is present, so
# "C LANGUAGE LAB", "SCRIPTING LANGUAGES LAB" and "COMMUNICATION LAB" (ECE) are still matched.
_SKILL_MARKERS = {"LANGUAGE", "ENGLISH", "SKILL", "SKILLS", "SOFT"}
_SKILL_WORDS = _SKILL_MARKERS | {"COMMUNICATION", "COMMUNICATIVE", "PROFESSIONAL", "INTERPERSONAL", "PERSONALITY",
                                 "DEVELOPMENT", "TECHNICAL", "BUSINESS", "AND"}


def _is_skill_lab(base: str) -> bool:
    words = set(base.split())
    return bool(words) and words <= _SKILL_WORDS and bool(words & _SKILL_MARKERS)


def lab_theory_matches(titles: list[str]) -> dict:
    """lab title -> list of theory titles (normalised). Only matched labs are returned."""
    theory = {_norm(t): t for t in titles if _base(t) is None}
    out = {}
    for t in titles:
        b = _base(t)
        if not b or _is_skill_lab(b):
            continue
        found = _find(b, theory)
        if not found:
            parts = [p.strip() for p in b.split(" AND ") if p.strip()]
            if len(parts) > 1:
                per = [_find(p, theory) for p in parts]
                if all(per):
                    found = [x for f in per for x in f]
        if found:
            out[t] = found
    return out


def apply_lab_rule(classifications: list[dict], titles_by_id: dict) -> list[dict]:
    """classifications: [{course_id, categories, ...}]; titles_by_id: course_id -> printed title.
    Returns new list; matched labs carry the union of their theory courses' categories and a 'lab_rule' note."""
    by_title = {}
    for c in classifications:
        by_title.setdefault(_norm(titles_by_id.get(c["course_id"], "")), c)
    matches = lab_theory_matches([titles_by_id.get(c["course_id"], "") for c in classifications])
    out = []
    for c in classifications:
        t = titles_by_id.get(c["course_id"], "")
        if t in matches:
            cats = []
            for th in matches[t]:
                for x in by_title.get(th, {}).get("categories", []):
                    if x not in cats:
                        cats.append(x)
            theory_sure = all(by_title.get(th, {}).get("confidence") == "HIGH" for th in matches[t])
            if cats and (c.get("confidence") == "HIGH" or theory_sure):
                c = {**c, "categories": cats, "lab_rule": f"categories of: {', '.join(matches[t])}"}
                if c.get("confidence") != "HIGH":
                    c["confidence"] = "HIGH"
                    c["reasoning"] = f"[LAB RULE] follows its theory course(s): {', '.join(matches[t])}"
        out.append(c)
    return out
