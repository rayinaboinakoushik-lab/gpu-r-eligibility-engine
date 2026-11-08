"""
Verified course-classification knowledge base.

Principle (from the finalized plan): reuse previously verified semantic
academic knowledge when sufficiently equivalent; use the LLM only when the
knowledge base cannot safely resolve the course.

This is NOT the caching mechanism that was removed earlier in this project.
That removed cache wrapped the expensive, full-regulations-document
classification call (reclassify_with_regulations()) and was deleted because
it kept a dangerous, costly path reachable. This is different in kind: it
stores only ALREADY-VERIFIED, evidence-backed classifications (HIGH
confidence from title, or resolved via a real syllabus excerpt) so that the
*next* student's identical or equivalent course never needs to spend an LLM
call at all -- cheap in, cheap forever after verification.

Matching is done on a NORMALIZED course title alone. Neither institution nor
regulation/curriculum-year is part of the signature: what actually decides a
course's category is its real semantic content, not which institution
taught it or which curriculum revision it belongs to. A course keeps the
same meaning wherever it's found, under whatever administrative label wraps
it -- so once a course is verified anywhere, it's verified everywhere, and
the knowledge base's whole purpose (never pay for the same classification
twice) only works if it's keyed on the thing that actually determines the
answer: the course itself, not its institutional wrapper.

This is intentionally strict on the (normalized) title -- a near-miss is
treated as a NEW course requiring real classification, never assumed
equivalent. Being strict here is the safe failure mode: worst case, we
spend one extra LLM call on a course that was actually identical; we never
silently reuse a classification for a course that wasn't really the same.
"""

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


_GENERIC_MATH = re.compile(
    r"^(?:[A-Z]{1,6}\d{1,4}[A-Z]?\s+)?"                      # optional subject code: "MA101", "M3"
    r"(?:(?:ENGINEERING|APPLIED|HIGHER|ADVANCED|BASIC|ADVANCED ENGINEERING)\s+)?"
    r"(?:MATHEMATICS|MATHS|MATH)"
    r"(?:\s*(?:I{1,3}|IV|V|[1-5]))?"
    r"(?:\s|$)"
)


def is_generic_math_title(title: str) -> bool:
    """
    True for maths courses whose title does not say what they teach:
    "Mathematics I", "Maths-2", "Engineering Mathematics III", "Mathematics",
    "Mathematics - I (Matrices, Calculus)". What such a course actually
    covers (calculus vs linear algebra vs differential equations vs
    statistics) differs by university and curriculum year, and German
    programs require exactly that split. So these courses ALWAYS need the
    student's own syllabus: never answered from the title, never answered
    from the knowledge base, and never stored in it.

    Titles that DO name their subject are not affected: "Discrete
    Mathematics", "Mathematics for Machine Learning", "Mathematical and
    Statistical Foundations", "Linear Algebra".
    """
    cleaned = re.sub(r"[^A-Z0-9 ]", " ", title.strip().upper())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return False
    m = _GENERIC_MATH.match(cleaned + " ")
    if not m:
        return False
    rest = cleaned[m.end():].strip() if m.end() <= len(cleaned) else ""
    # Anything after the numeral must not name a specific subject ("FOR MACHINE LEARNING").
    return rest == "" or not re.match(r"^(FOR|OF|AND|IN)\b", rest)


def normalize_course_signature(title: str, field: str = "cs") -> str:
    """
    Builds a stable lookup key for the knowledge base: field + normalized course
    title. No institution or regulation/curriculum-year dimension -- see module
    docstring for why those were dropped.

    The FIELD is part of the key because each field has its own taxonomy: the same
    title can be correctly classified differently in two fields ("Basic Electrical
    Engineering" has no category in CS but is general_ee in EEE), and one
    field's category IDs may not even exist in another's taxonomy. So an answer is
    only ever reused within the field it was verified in.
    """
    def clean(s: str) -> str:
        # 04.11.2026 (Koushik approved): "&", "and" and "/" are only joiners, so "Structural Dynamics & Earthquake
        # Engg." = "... and ..." (batch 1: S12 missed its map entry) and "CAD/CAM" = "CAD & CAM" = "CAD / CAM".
        # Checked: no two course-map titles with different categories become one key. Saved entries are re-keyed on load.
        s = s.strip().upper().replace("&", " ").replace("/", " ")
        s = re.sub(r"[^A-Z0-9 ]", "", s)
        s = re.sub(r"\bAND\b", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        return s

    return f"{field.strip().lower()}::{clean(title)}"


@dataclass
class VerifiedEntry:
    signature: str
    title: str
    categories: list           # FLAT list of every category this course genuinely belongs
                                # to. No primary/secondary ranking -- overlap across
                                # categories is normal and every match is an equal,
                                # independent one. May be empty if genuinely no category applies.
    confidence: str            # only "HIGH" entries should ever be stored
    reasoning: str
    evidence_quote: Optional[str]   # present if resolved via excerpt, else None
    source: str                # "title_only" or "student_excerpt"
    verified_count: int = 1    # how many times this exact signature has been confirmed
    field: str = "cs"          # the field (taxonomy) this answer was verified in


# ---------------------------------------------------------------------------------------------
# Approved course map (30.10.2026): the 545 JNTUH titles Koushik approved (data/taxonomy/
# GPU-R_course_map.json) are answered from the map, never guessed by the LLM. Read-only: the map
# changes only through review. Branch-aware: a title mapped for one branch is used only for the
# fields of that branch (or "all"). Categories outside the field file are dropped (the field's
# classifier could not output them either).
# ---------------------------------------------------------------------------------------------
FIELD_BRANCHES = {"cs": {"CS/IT/CSIT", "all"}, "eee": {"EEE", "ECE", "all"},
                  "mechanical": {"Mechanical", "all"}, "civil": {"Civil", "all"}}


def load_approved_map(field: str, map_path: Optional[Path] = None, taxonomy_path: Optional[Path] = None) -> dict:
    """signature -> VerifiedEntry for every approved title usable in this field."""
    from paths import TAXONOMY_DIR
    map_path = map_path or TAXONOMY_DIR / "GPU-R_course_map.json"
    taxonomy_path = taxonomy_path or TAXONOMY_DIR / f"{field}_taxonomy.json"
    if not map_path.exists() or not taxonomy_path.exists():
        return {}
    courses = json.loads(map_path.read_text(encoding="utf-8"))["courses"]
    atomic = set(json.loads(taxonomy_path.read_text(encoding="utf-8"))["category_evidence_status"])
    branches = FIELD_BRANCHES.get(field, {"all"})
    out = {}
    for c in courses:
        if not branches & set(c.get("branches", [])) or is_generic_math_title(c["title"]):
            continue
        sig = normalize_course_signature(c["title"], field)
        cats = [x for x in c.get("categories", []) if x in atomic]
        out[sig] = VerifiedEntry(signature=sig, title=c["title"], categories=cats, confidence="HIGH",
                                 reasoning=f"approved GPU-R course map ({c.get('status')})", evidence_quote=None,
                                 source="approved_course_map", verified_count=1, field=field)
    return out


class KnowledgeBase:
    """
    A simple, local, file-backed store. Swap the load/save methods for a
    real database later without changing the lookup/record API used by the
    rest of the pipeline.

    Lookup order (30.10.2026): 1. approved course map (human-reviewed), 2. learned entries
    (HIGH-confidence results saved from earlier students), 3. nothing -> the LLM classifies.
    """

    def __init__(self, path: str = "verified_knowledge_base.json", use_approved_map: bool = True):
        self.path = Path(path)
        self._entries: dict[str, VerifiedEntry] = {}
        self._approved: dict[str, dict] = {}            # field -> {signature: VerifiedEntry}
        self.use_approved_map = use_approved_map
        self._load()

    def _approved_for(self, field: str) -> dict:
        if not self.use_approved_map:
            return {}
        if field not in self._approved:
            self._approved[field] = load_approved_map(field)
        return self._approved[field]

    def _load(self) -> None:
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for data in raw.values():
            if is_generic_math_title(data.get("title", "")):
                continue  # stored before the generic-maths rule existed; never valid to reuse
            data.setdefault("field", "cs")  # entries saved before fields were separated were all CS
            data["signature"] = normalize_course_signature(data["title"], data["field"])
            self._entries[data["signature"]] = VerifiedEntry(**data)

    def _save(self) -> None:
        raw = {sig: asdict(entry) for sig, entry in self._entries.items()}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(raw, f, indent=2)

    def lookup(self, title: str, field: str = "cs") -> Optional[VerifiedEntry]:
        """
        Returns a verified entry ONLY if it was previously stored at HIGH
        confidence. MEDIUM/LOW/insufficient results are never stored here in
        the first place (see record()), so a hit always means "safe to
        reuse without a fresh LLM call."
        """
        if is_generic_math_title(title):
            return None  # always needs the student's own syllabus
        sig = normalize_course_signature(title, field)
        approved = self._approved_for(field).get(sig)
        if approved is not None:
            return approved
        return self._entries.get(sig)

    def record(self, title: str,
               categories: list,
               confidence: str, reasoning: str, source: str,
               evidence_quote: Optional[str] = None, field: str = "cs") -> None:
        """
        Stores a classification result -- but ONLY if it's genuinely
        trustworthy: HIGH confidence, and (if source == "student_excerpt")
        a real evidence_quote must be present. This mirrors the same
        evidence-enforcement rule already used in course_classifier.py's
        upgrade functions -- the knowledge base must never become a way to
        smuggle in an unverified guess as if it were confirmed.
        """
        if confidence != "HIGH":
            return  # only HIGH-confidence, evidence-backed results are reusable knowledge
        if source == "student_excerpt" and (not evidence_quote or len(evidence_quote.strip()) < 10):
            return  # same evidence-quote discipline as upgrade_classification_with_excerpt*
        if is_generic_math_title(title):
            return  # one student's "Mathematics I" says nothing about another's

        sig = normalize_course_signature(title, field)
        if sig in self._approved_for(field):
            return  # the approved map already answers this title; never overwritten by a learned result
        existing = self._entries.get(sig)
        if existing:
            existing.verified_count += 1
            # Keep the existing stored classification; a repeat confirmation
            # increases confidence in the entry, it doesn't overwrite it with
            # a possibly-inconsistent new one.
        else:
            self._entries[sig] = VerifiedEntry(
                signature=sig, title=title,
                categories=list(categories) if categories else [],
                confidence=confidence, reasoning=reasoning, evidence_quote=evidence_quote,
                source=source, verified_count=1, field=field.strip().lower(),
            )
        self._save()

    def stats(self) -> dict:
        return {
            "approved_map_titles_loaded": {f: len(v) for f, v in self._approved.items()},
            "total_verified_courses": len(self._entries),
            "from_title_only": sum(1 for e in self._entries.values() if e.source == "title_only"),
            "from_student_excerpt": sum(1 for e in self._entries.values() if e.source == "student_excerpt"),
        }


if __name__ == "__main__":
    print("Knowledge base module loaded.")
    print("Use KnowledgeBase().lookup(...) before any LLM classification call,")
    print("and KnowledgeBase().record(...) after any HIGH-confidence, evidence-backed result.")
