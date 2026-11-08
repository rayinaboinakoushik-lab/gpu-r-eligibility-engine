# REFERENCE ONLY (27.10.2026): old engine of 14.10, kept to compare while the new engine is written (Day 3).
# It expects the OLD APPROVED_*.json files and does not implement the new counting rules.
"""
GPU-R matching engine v1.

Takes ONE student's final profile and checks it against every program in that student's
field file (never another field). Every program gets a verdict with the reason for each check.

Checks that decide the verdict:
  1. Grade     -- HARD_MAX_GRADE: German grade must be <= the program's limit (German scale:
                  lower is better). NO_GRADE_THRESHOLD: passes, with a note on later selection.
  2. Subjects  -- each subject_credit_requirements item is compared with the student's ECTS in
                  the SAME category (taxonomy and program file share their categories). Items
                  pooling several categories use a safe minimum. "presence only" items need > 0.
English is NOT a matching check: it is shown per program as the score the student must reach
to apply (e.g. "IELTS 6.5 or TOEFL iBT 90"), together with the other application requirements.

Verdicts (best first):
  ELIGIBLE             every check passes
  CONDITIONAL          grade passes, only subject ECTS are short, and the program allows
                       conditional admission (within its stated max_ects, if it states one)

Excluded courses (not confidently classified in Part 1: "verify or exclude, never guess") count
toward NO category. Matching uses only the verified profile totals; excluded courses are listed
for the student as "not counted", with the option to re-check them with an official syllabus.
  NOT_ELIGIBLE         at least one check fails for certain

Application requirements (English score, APS, GRE, German, work experience, thesis) are listed
per program as "to apply you also need" -- shown to the student, not part of the verdict.
"""

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

PROGRAM_FILES = {
    "cs": "APPROVED_computer_science.json",
    "eee": "APPROVED_electrical_electronic_engineering.json",
    "mechanical": "APPROVED_mechanical_engineering.json",
    "civil": "APPROVED_civil_engineering.json",
}
TAXONOMY_FILES = {
    "cs": "cs_taxonomy.json",
    "eee": "eee_taxonomy.json",
    "mechanical": "mechanical_taxonomy.json",
    "civil": "civil_taxonomy.json",
}

PASS, FAIL = "PASS", "FAIL"

# When a program states only a CEFR level, the lowest score of that level's standard band is used.
CEFR_TO_IELTS = {"B1": 4.0, "B2": 5.5, "C1": 7.0, "C2": 8.5}
CEFR_TO_TOEFL_IBT = {"B1": 42, "B2": 72, "C1": 95, "C2": 114}
VERDICT_ORDER = ["ELIGIBLE", "CONDITIONAL", "NOT_ELIGIBLE"]


# ---------------------------------------------------------------------------------------------
# Student profile
# ---------------------------------------------------------------------------------------------

@dataclass
class StudentProfile:
    name: str
    field: str                 # cs / eee / mechanical / civil
    german_grade: float
    category_totals: dict      # category id -> ECTS, exactly as built in Part 1
    country: str = "India"
    excluded_courses: list = field(default_factory=list)   # shown as "not counted"; never matched

    @staticmethod
    def from_json(data: dict) -> "StudentProfile":
        """Reads the Part 1 final profile (final_matching_profile_<session>.json) as it is."""
        totals = dict(data.get("atomic_profile_ects") or {})
        totals.update(data.get("aggregate_profile_ects") or {})
        return StudentProfile(
            name=data.get("name") or data.get("degree_field") or "student",
            field=data["field"], german_grade=data["german_grade"],
            country=data.get("country", "India"), category_totals=totals,
            excluded_courses=list(data.get("excluded_courses") or []),
        )


# ---------------------------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------------------------

@dataclass
class Check:
    kind: str                  # grade / subject
    label: str
    status: str                # PASS / FAIL
    detail: str
    required: Optional[float] = None
    achieved: Optional[float] = None
    shortfall: float = 0.0


@dataclass
class ProgramResult:
    program_id: str
    program: str
    university: str
    verdict: str
    summary: str
    checks: list
    also_required: list
    notes: list
    grade_limit: Optional[float] = None


# ---------------------------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------------------------

class MatchingEngine:
    def __init__(self, field_name: str, data_dir: str = "."):
        if field_name not in PROGRAM_FILES:
            raise ValueError(f"Unknown field '{field_name}'. Expected one of {list(PROGRAM_FILES)}.")
        base = Path(data_dir)
        self.field = field_name
        self.programs = self._load_json(base / PROGRAM_FILES[field_name], "program file")
        taxonomy = self._load_json(base / TAXONOMY_FILES[field_name], "taxonomy")
        self.atomic = set(taxonomy["category_evidence_status"])
        self.pools = {}
        for section in ("aggregate_categories", "contextual_categories"):
            for cid, info in (taxonomy.get(section) or {}).items():
                self.pools[cid] = set(info.get("formula_components", []))

    @staticmethod
    def _load_json(path: Path, what: str):
        if not path.exists():
            raise SystemExit(f"Missing {what}: {path.name} -- put it in the same folder as the scripts.")
        try:
            with open(path, encoding="utf-8-sig") as f:
                return json.load(f)
        except json.JSONDecodeError:
            raise SystemExit(f"The {what} {path.name} ({path.stat().st_size} bytes) is not valid JSON -- "
                             f"it is empty or damaged. Download it again and replace it.")

    # --- category helpers ------------------------------------------------------------------

    def _expand(self, category: str) -> set:
        """A category plus, for an aggregate like general_cs, all of its parts."""
        out, todo = set(), [category]
        while todo:
            c = todo.pop()
            if c in out:
                continue
            out.add(c)
            todo.extend(self.pools.get(c, ()))
        return out

    def _measurable(self, category: str) -> bool:
        return category in self.atomic or category in self.pools

    # --- individual checks -----------------------------------------------------------------

    def _grade_check(self, program: dict, student: StudentProfile) -> Check:
        rule = program.get("gpa_rule_type")
        limit = (program.get("grade_requirement") or {}).get("value")
        if rule == "HARD_MAX_GRADE" and isinstance(limit, (int, float)):
            ok = student.german_grade <= limit
            return Check("grade", "Minimum grade", PASS if ok else FAIL,
                         f"German grade {student.german_grade:.2f} {'≤' if ok else '>'} required {limit:.2f}"
                         " (German scale: lower is better)",
                         required=limit, achieved=student.german_grade)
        if rule == "HARD_MAX_GRADE":
            return Check("grade", "Minimum grade", PASS,
                         "The program has a grade limit but its value is not recorded -- check the program page.")
        return Check("grade", "Minimum grade", PASS,
                     f"No fixed grade limit (your German grade {student.german_grade:.2f} may still "
                     "count in the selection ranking).", achieved=student.german_grade)

    def _subject_check(self, item: dict, student: StudentProfile) -> Check:
        label = item.get("raw_label") or item.get("canonical_category", "subject requirement")
        wanted = [item["canonical_category"]] + list(item.get("covered_categories") or [])
        wanted = list(dict.fromkeys(wanted))
        targets = set()
        for c in wanted:
            targets |= self._expand(c)
        unmeasurable = [c for c in wanted if not self._measurable(c)]

        presence_only = bool(item.get("requires_subject_presence_only"))
        need = float(item.get("min_ects") or 0)
        return self._subject_check_from_totals(item, label, wanted, targets, unmeasurable,
                                               presence_only, need, student)

    def _subject_check_from_totals(self, item, label, wanted, targets, unmeasurable,
                                   presence_only, need, student) -> Check:  # noqa: C901
        """
        The program file and the taxonomy use the same categories, so a requirement is checked
        directly against the student's total for that category (aggregates such as general_cs
        are already built in Part 1 without double counting).
        Only an item that pools several categories (covered_categories) needs care: the largest
        single total is used (a safe minimum -- never counts a course twice). A category the
        taxonomy does not measure counts as 0. Every requirement ends as PASS or FAIL.
        """
        totals = student.category_totals
        req = None if presence_only else need
        need_txt = "some coursework (no minimum ECTS)" if presence_only else f"{need:g} ECTS"
        if len(wanted) == 1 and wanted[0] in totals:
            low = float(totals[wanted[0]])
        else:
            low = max((float(totals[k]) for k in targets if k in totals), default=0.0)
        low = round(low, 2)
        bar = 0.0 if presence_only else need

        if (presence_only and low > 0) or (not presence_only and low >= bar):
            return Check("subject", label, PASS, f"{low:g} ECTS found, needs {need_txt}", required=req, achieved=low)
        shortfall = round(max(0.0, bar - low), 2) if not presence_only else need
        detail = f"{low:g} ECTS found, needs {need_txt}" + ("" if presence_only else f" -- short by {shortfall:g} ECTS")
        if unmeasurable:
            detail += ("; part of this requirement is a category our taxonomy does not measure ("
                       + ", ".join(c.split(".")[-1] for c in unmeasurable) + "), counted as 0")
        return Check("subject", label, FAIL, detail, required=req, achieved=low, shortfall=shortfall)

    def _english_requirement(self, program: dict) -> Optional[str]:
        """The English score the student needs to apply -- information, not a matching check."""
        eng = program.get("language_english") or {}
        parts = []
        if eng.get("ielts_min"):
            parts.append(f"IELTS {eng['ielts_min']:g}")
        if eng.get("toefl_ibt_min"):
            parts.append(f"TOEFL iBT {eng['toefl_ibt_min']:g}")
        level = eng.get("required_level")
        if not parts and isinstance(level, str) and level.upper()[:2] in CEFR_TO_IELTS:
            lv = level.upper()[:2]
            parts.append(f"{lv} level (about IELTS {CEFR_TO_IELTS[lv]:g} / TOEFL iBT {CEFR_TO_TOEFL_IBT[lv]})")
        if not parts:
            return None
        txt = "English: " + " or ".join(parts)
        if level and not txt.endswith(")"):
            txt += f" ({level})"
        exemptions = [str(e).lower() for e in (eng.get("allowed_exemptions") or [])]
        if eng.get("moi_not_accepted"):
            txt += " -- a medium-of-instruction letter is NOT accepted"
        elif any("english_medium" in e or "medium_of_instruction" in e for e in exemptions):
            txt += " -- an English-medium degree may be accepted instead"
        return txt

    def _also_required(self, program: dict, student: StudentProfile) -> list:
        out = []
        english = self._english_requirement(program)
        if english:
            out.append(english)
        aps = program.get("aps_certificate") or {}
        if student.country in (aps.get("required_for") or []):
            out.append("APS certificate (required for applicants from " + student.country + ")")
        for t in program.get("standardized_test_requirements") or []:
            if t.get("required") is False and not t.get("required_for"):
                continue
            txt = t.get("test", "Test")
            if t.get("min_quant_percentile"):
                txt += f" (quant ≥ {t['min_quant_percentile']}th percentile)"
            rf = t.get("required_for")
            if rf:
                if isinstance(rf, list) and student.country not in rf:
                    continue  # required only for other countries
                txt += " -- required for " + (", ".join(rf) if isinstance(rf, list) else str(rf))
            elif t.get("recommended"):
                txt += " (recommended)"
            out.append(txt)
        gre = program.get("gre")
        if gre:
            if isinstance(gre, dict):
                txt = "GRE"
                if gre.get("applies_to") or gre.get("required_for"):
                    txt += " (required for " + str(gre.get("applies_to") or gre.get("required_for")) + ")"
                out.append(txt)
            else:
                out.append("GRE")
        ger = program.get("language_german") or {}
        lvl = ger.get("required_level_at_application") or ger.get("required_level") or ger.get("required_level_at_enrollment")
        if ger.get("required") and lvl:
            out.append(f"German {lvl}" + (" by enrollment" if ger.get("required_level_at_enrollment") else ""))
        elif ger.get("required"):
            out.append("German language (level: see program)")
        exp = program.get("practical_experience_requirement") or {}
        if exp.get("required"):
            out.append("Work experience" + (f" ({exp['duration_years']} year)" if exp.get("duration_years") else ""))
        if program.get("final_scientific_work_requirement"):
            out.append("Bachelor thesis / scientific work (your final-year project usually counts)")
        return out

    # --- one program -------------------------------------------------------------------------

    def evaluate(self, program: dict, student: StudentProfile) -> ProgramResult:
        checks = [self._grade_check(program, student)]
        for item in (program.get("subject_credit_requirements") or {}).get("items", []):
            checks.append(self._subject_check(item, student))

        grade = checks[0]
        subjects = [c for c in checks if c.kind == "subject"]
        failed = [c for c in checks if c.status == FAIL]

        cond = program.get("conditional_admission") or {}
        only_subject_fails = failed and all(c.kind == "subject" for c in failed)
        total_short = round(sum(c.shortfall for c in failed), 2)
        cond_max = cond.get("max_ects")
        cond_possible = bool(cond.get("allowed")) and only_subject_fails and (
            cond_max is None or total_short <= float(cond_max))

        if not failed:
            verdict = "ELIGIBLE"
        elif cond_possible and grade.status == PASS:
            verdict = "CONDITIONAL"
        else:
            verdict = "NOT_ELIGIBLE"

        if verdict == "ELIGIBLE":
            summary = "Meets every checked requirement."
        elif verdict == "CONDITIONAL":
            how = str(cond.get("mechanism") or cond.get("note") or "").strip()
            summary = (f"Conditional: short by {total_short:g} ECTS in subject requirements. The program "
                       "allows conditional admission" + (f" (up to {cond_max:g} ECTS)" if cond_max else "")
                       + " -- the university decides which modules you must make up."
                       + (f" University's rule: {how}" if how else ""))
        else:
            summary = "Fails: " + "; ".join(f"{c.label} ({c.detail})" for c in failed)

        notes = []
        if not subjects:
            notes.append("This program lists no subject-credit requirements, so only the grade was checked.")
        sel = (program.get("subsequent_selection_criteria_display") or {})
        if sel.get("has_subsequent_hurdles"):
            notes.append("Further selection steps after the eligibility check (e.g. test, interview, ranking).")
        if cond.get("allowed") and verdict != "CONDITIONAL" and (cond.get("mechanism") or cond.get("note")):
            notes.append("Conditional admission exists: " + str(cond.get("mechanism") or cond.get("note"))[:200])
        sub_note = (program.get("subject_credit_requirements") or {}).get("note") or program.get("subject_credit_note")
        if sub_note:
            notes.append("Subject requirements: " + str(sub_note)[:220])

        # Some programs are stored as two admission routes (e.g. direct vs. with interview,
        # each with its own grade limit). The route is shown so the two entries are not confused.
        pid = str(program.get("id"))
        suffix = pid.rsplit("_", 1)[-1].upper() if "_" in pid else ""
        route = {"DIRECT": "direct admission", "CONDITIONAL": "conditional admission",
                 "INTERVIEW": "admission with interview", "T1": "track 1", "T2": "track 2"}.get(suffix)
        name = program.get("program", "") + (f" [{route}]" if route else "")
        return ProgramResult(
            program_id=pid, program=name,
            university=program.get("university", ""), verdict=verdict, summary=summary,
            checks=checks, also_required=self._also_required(program, student), notes=notes,
            grade_limit=(program.get("grade_requirement") or {}).get("value"),
        )

    # --- all programs ------------------------------------------------------------------------

    def match(self, student: StudentProfile) -> list:
        if student.field != self.field:
            raise ValueError(f"Student field '{student.field}' does not match engine field '{self.field}'.")
        results = [self.evaluate(p, student) for p in self.programs]

        def sort_key(r: ProgramResult):
            fails = sum(1 for c in r.checks if c.status == FAIL)
            short = sum(c.shortfall for c in r.checks if c.status == FAIL)
            margin = (r.grade_limit - student.german_grade) if isinstance(r.grade_limit, (int, float)) else 0.0
            subject_passes = sum(1 for c in r.checks if c.kind == "subject" and c.status == PASS)
            # Within a verdict: fewer/smaller gaps first, then programs where more was actually
            # verified (subject requirements passed), then the larger grade margin.
            return (VERDICT_ORDER.index(r.verdict), fails, short, -subject_passes, -margin, r.university)
        return sorted(results, key=sort_key)


def summarize(results: list) -> dict:
    counts = {v: 0 for v in VERDICT_ORDER}
    for r in results:
        counts[r.verdict] += 1
    return counts


def results_to_json(student: StudentProfile, results: list) -> dict:
    return {
        "student": {"name": student.name, "field": student.field, "german_grade": student.german_grade,
                    "not_counted_courses": student.excluded_courses},
        "summary": summarize(results),
        "programs": [asdict(r) for r in results],
    }
