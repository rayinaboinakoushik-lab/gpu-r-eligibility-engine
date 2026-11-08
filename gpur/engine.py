"""
GPU-R matching engine (spec v1, decisions up to 27.10.2026).

Deterministic: no LLM. Input = one student's classified course list + one field's records.
Output = per programme one of four lists, with every check, gap and reason.

Reading order (each step is one section below):
  1. load_field()           frozen records (+ checksum check), field taxonomy, engine config, degree fields
  2. target sets            a requirement's categories expanded through the taxonomy sums
  3. count_subjects()       counting rules C1-C4 for all requirements of one record
  4. real_gap()             nested-safe gap (a gap inside a larger requirement is not counted twice)
  5. evaluate_record()      exclusion -> degree -> grade -> total credits -> subjects -> conditions -> list
  6. evaluate_program()     route groups: best route, gated routes only after confirmation
  7. evaluate_field()       every programme of the field for one student

Lists: 1 eligible, no selection step (named "strongly eligible" until 05.11.2026), 2 eligible with selection criteria, 3 bridging possible, 4 not eligible.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from dataclasses import dataclass, field as dc_field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FROZEN_DIR = REPO / "data" / "frozen"
TAXONOMY_DIR = REPO / "data" / "taxonomy"
CONFIG_PATH = REPO / "engine_kit" / "engine_config.json"

FIELD_RECORDS = {"cs": "computer_science", "eee": "electrical_electronic_engineering",
                 "mechanical": "mechanical_engineering", "civil": "civil_engineering"}
LIST_NAMES = {1: "eligible, no selection step", 2: "eligible with selection criteria", 3: "bridging possible", 4: "not eligible"}
MAX_EXACT_COMBINATIONS = 20000        # above this, C4 uses the greedy assignment (spec: "above 12 courses: greedy")


class EngineError(Exception):
    """Raised instead of guessing: unknown category, changed frozen file, missing programme."""


# ============================================================================ 1. loading
@dataclass
class FieldData:
    field: str
    records: dict                      # id -> record (dict, frozen format v2)
    taxonomy: dict                     # the field's taxonomy file
    config: dict                       # engine_config.json
    degree_fields: dict                # degree_fields.json -> "degree_fields"
    pools: dict = dc_field(default_factory=dict)      # sum id -> set of atomic parts
    atomic: set = dc_field(default_factory=set)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_field(field: str, frozen_dir: Path = FROZEN_DIR, taxonomy: dict | None = None,
               config: dict | None = None, verify_manifest: bool = True,
               records_override: list | None = None) -> FieldData:
    """Load everything the engine needs for one field. A changed frozen file stops the engine."""
    if field not in FIELD_RECORDS:
        raise EngineError(f"unknown field {field!r}; expected one of {list(FIELD_RECORDS)}")
    frozen_dir = Path(frozen_dir)
    if records_override is None:
        name = f"GPU-R_{FIELD_RECORDS[field]}_FROZEN_2026-10-24.json"
        path = frozen_dir / name
        if verify_manifest:
            manifest = json.loads((frozen_dir / "MANIFEST.json").read_text(encoding="utf-8"))
            expected = {e["file"]: e["sha256"] for e in manifest}
            if expected.get(name) != _sha256(path):
                raise EngineError(f"{name} differs from MANIFEST.json (file changed after the freeze)")
        records = json.loads(path.read_text(encoding="utf-8"))
    else:
        records = records_override
    if taxonomy is None:
        taxonomy = json.loads((TAXONOMY_DIR / f"{field}_taxonomy.json").read_text(encoding="utf-8"))
    if config is None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    degree_fields = json.loads((TAXONOMY_DIR / "degree_fields.json").read_text(encoding="utf-8"))["degree_fields"]
    fd = FieldData(field, {r["id"]: r for r in records}, taxonomy, config, degree_fields)
    for section in ("aggregate_categories", "contextual_categories"):
        for cid, info in (taxonomy.get(section) or {}).items():
            fd.pools[cid] = set(info.get("formula_components", []))
    fd.atomic = set(taxonomy["category_evidence_status"])
    _check_record_categories(fd)
    return fd


def _check_record_categories(fd: FieldData) -> None:
    """Every category a record uses must exist in the field taxonomy (never silently count 0)."""
    known = fd.atomic | set(fd.pools)
    for r in fd.records.values():
        for it in r["subject_credit_requirements"]["items"]:
            for c in [it["canonical_category"], *it["covered_categories"]]:
                if c not in known:
                    raise EngineError(f"record {r['id']} uses category {c}, unknown to the {fd.field} taxonomy")


# ============================================================================ 2. target sets
def expand(category: str, fd: FieldData) -> set:
    """A category plus, for a sum (general_cs, practical_cs ...), all its atomic parts."""
    out, todo = set(), [category]
    while todo:
        c = todo.pop()
        if c in out:
            continue
        out.add(c)
        todo.extend(fd.pools.get(c, ()))
    return {c for c in out if c not in fd.pools} | ({category} if category not in fd.pools else set())


def item_categories(item: dict) -> list:
    return list(dict.fromkeys([item["canonical_category"], *item["covered_categories"]]))


def target_set(item: dict, fd: FieldData, record_id: str | None = None, index: int | None = None) -> set:
    out = set()
    for c in item_categories(item):
        out |= expand(c, fd)
    add = fd.config.get("add_subjects", {}).get(record_id or "", {})          # e.g. ICT named in the rule text
    if add.get("field") in (None, fd.field):
        for c in add.get(str(index), []):
            out |= expand(c, fd)
    rule = fd.config.get("separate_subjects", {}).get(record_id or "", {})     # e.g. statistics not under Mathematik
    return out - set(rule.get(str(index), []))


def student_courses(student: dict, fd: FieldData) -> list:
    """The student's courses with the field's same-subject rules (_implies) applied; unknown ids stop the engine."""
    implies = fd.taxonomy.get("_implies", {})
    excluded = {e.get("course_id") if isinstance(e, dict) else e for e in student.get("excluded_courses") or []}
    out = []
    for c in student.get("courses", []):
        if c.get("id") in excluded:
            continue
        cats = list(dict.fromkeys(c.get("categories") or []))
        for x in list(cats):
            for y in implies.get(x, []):
                if y not in cats:
                    cats.append(y)
        for x in cats:
            if x not in fd.atomic:
                raise EngineError(f"course {c.get('title')!r} has category {x}, unknown to the {fd.field} taxonomy")
        out.append({"id": c["id"], "title": c.get("title", c["id"]), "ects": float(c.get("ects") or 0), "cats": set(cats)})
    return out


# ============================================================================ 3. counting C1-C4
def _nested(a: set, b: set) -> bool:
    """C2: one requirement's target set lies inside the other's."""
    return a <= b or b <= a


def _linked(i: int, j: int, course_cats: set, items: list, targets: list) -> bool:
    """Two requirements share a course when the regulation links them:
    C2 nesting, or C3 the course's category is written literally in both requirements."""
    if _nested(targets[i], targets[j]):
        return True
    literal_i, literal_j = set(item_categories(items[i])), set(item_categories(items[j]))
    return bool(course_cats & literal_i & literal_j)


def _options(matches: list, course_cats: set, items: list, targets: list) -> list:
    """All maximal groups of matching requirements that are pairwise linked.
    One group = the course counts in all of them (C1-C3). Several groups = ambiguous (C4): pick one."""
    groups = []
    for size in range(len(matches), 0, -1):
        for combo in itertools.combinations(matches, size):
            if any(set(combo) <= g for g in groups):
                continue
            if all(_linked(a, b, course_cats, items, targets) for a, b in itertools.combinations(combo, 2)):
                groups.append(set(combo))
    return sorted((sorted(g) for g in groups), key=lambda g: g)     # first-listed requirement first (tie rule)


def _totals(assign: dict, courses: list, n_items: int) -> list:
    tot = [0.0] * n_items
    for ci, group in assign.items():
        for i in group:
            tot[i] += courses[ci]["ects"]
    return tot


def _shortfall_sum(tot: list, items: list) -> float:
    s = 0.0
    for i, it in enumerate(items):
        if it["requires_subject_presence_only"]:
            s += 0.0 if tot[i] > 0 else 1.0          # an unmet presence item weighs like 1 ECTS in the search
        else:
            s += max(0.0, float(it["min_ects"] or 0) - tot[i])
    return s


def count_subjects(record: dict, courses: list, fd: FieldData) -> list:
    """Per requirement: achieved ECTS, shortfall, PASS/FAIL and the courses used (rules C1-C4)."""
    items = record["subject_credit_requirements"]["items"]
    targets = [target_set(it, fd, record["id"], i) for i, it in enumerate(items)]
    fixed, ambiguous = {}, []                         # course index -> requirement group
    for ci, c in enumerate(courses):
        matches = [i for i, t in enumerate(targets) if c["cats"] & t]
        if not matches:
            continue
        opts = _options(matches, c["cats"], items, targets)
        if len(opts) == 1:
            fixed[ci] = opts[0]
        else:
            ambiguous.append((ci, opts))
    best = dict(fixed)
    if ambiguous:
        n_comb = 1
        for _, opts in ambiguous:
            n_comb *= len(opts)
        if n_comb <= MAX_EXACT_COMBINATIONS:
            best_score = None
            for choice in itertools.product(*[opts for _, opts in ambiguous]):   # options are in item order
                trial = dict(fixed)
                for (ci, _), g in zip(ambiguous, choice):
                    trial[ci] = g
                score = _shortfall_sum(_totals(trial, courses, len(items)), items)
                if best_score is None or score < best_score - 1e-9:              # strict: ties keep the first
                    best_score, best = score, trial
        else:                                                                    # greedy: largest course first
            for ci, opts in sorted(ambiguous, key=lambda x: -courses[x[0]]["ects"]):
                tot = _totals(best, courses, len(items))
                gaps = [max(0.0, float(items[i]["min_ects"] or 0) - tot[i]) for i in range(len(items))]
                best[ci] = max(opts, key=lambda g: (sum(gaps[i] for i in g), -g[0]))
    tot = _totals(best, courses, len(items))
    checks = []
    for i, it in enumerate(items):
        used = [courses[ci]["title"] for ci, g in best.items() if i in g]
        if it["requires_subject_presence_only"]:
            ok = tot[i] > 0
            short = 0.0
            need = None
        else:
            need = float(it["min_ects"] or 0)
            ok = tot[i] >= need - 1e-9
            short = round(max(0.0, need - tot[i]), 2)
        checks.append({"label": it["raw_label"], "kind": "subject", "status": "PASS" if ok else "FAIL",
                       "required": need, "presence_only": it["requires_subject_presence_only"],
                       "achieved": round(tot[i], 2), "shortfall": short, "courses": used, "item": i})
    return checks


# ============================================================================ 4. real gap
def real_gap(record: dict, checks: list, fd: FieldData, item_ids: list | None = None) -> float:
    """Gap without double counting: a requirement's gap = max(own shortfall, sum of its nested parts' gaps).
    Only ECTS requirements count (presence items are handled by the conditions rule)."""
    items = record["subject_credit_requirements"]["items"]
    ids = [i for i in range(len(items)) if not items[i]["requires_subject_presence_only"]]
    if item_ids is not None:
        ids = [i for i in ids if i in item_ids]
    targets = {i: target_set(items[i], fd, record["id"], i) for i in ids}

    def is_inside(a, b):            # a nested in b (equal sets: the later one is inside the earlier one)
        return a != b and (targets[a] < targets[b] or (targets[a] == targets[b] and a > b))

    parent = {}
    for a in ids:
        outer = [b for b in ids if is_inside(a, b)]
        if outer:   # the closest enclosing requirement = the one that has no other enclosing one in between
            parent[a] = min(outer, key=lambda b: (len(targets[b]), -b))
    children = {i: [a for a, p in parent.items() if p == i] for i in ids}

    def gap(i):
        own = checks[i]["shortfall"]
        return max(own, sum(gap(c) for c in children[i]))

    return round(sum(gap(i) for i in ids if i not in parent), 2)


# ============================================================================ 5. one record
def _degree_matches(student: dict, record: dict, fd: FieldData) -> bool:
    primary = set(record["accepted_degree_fields"].get("primary_fields") or [])
    deg = student.get("degree_field")
    if deg in primary:
        return True
    return bool(set(fd.degree_fields.get(deg, {}).get("counts_as", [])) & primary)


def _exclusion(record_id: str, student: dict, fd: FieldData) -> str | None:
    rule = fd.config.get("exclusions", {}).get(record_id)
    if not rule or rule.get("field", fd.field) != fd.field:
        return None
    if "country" in rule and student.get("country", "India") == rule["country"]:
        return rule["reason"]
    only = rule.get("only_degree_subfields")
    if only is not None:
        sub = student.get("degree_subfield")
        if student.get("degree_field") == "electronics_communication" or (sub is not None and sub not in only):
            return rule["reason"]
    return None


def _important_notes(record: dict) -> list:
    notes = []
    for n in record.get("other_requirements") or []:
        if isinstance(n, str) and n.startswith("IMPORTANT"):
            notes.append(n)
    for n in (record.get("subsequent_selection_criteria_display") or {}).get("descriptive_notes") or []:
        if isinstance(n, str) and n.startswith("IMPORTANT") and n not in notes:
            notes.append(n)
    for block in ("grade_requirement", "language_english", "language_german"):
        n = (record.get(block) or {}).get("note")
        if isinstance(n, str) and n.startswith("IMPORTANT") and n not in notes:
            notes.append(n)
    return notes


def _also_required(record: dict, student: dict, fd: FieldData) -> list:
    out = []
    aps = fd.config.get("always_display", {})
    if student.get("country", "India") == aps.get("aps_for_country", "India"):
        out.append(aps.get("text", "APS certificate required for applicants from India"))
    eng = record.get("language_english") or {}
    parts = [f"IELTS {eng['ielts_min']}" if eng.get("ielts_min") else None,
             f"TOEFL iBT {eng['toefl_ibt_min']}" if eng.get("toefl_ibt_min") else None,
             eng.get("required_level")]
    parts = [p for p in parts if p]
    if parts:
        out.append("English: " + ", ".join(str(p) for p in parts) + (" (MOI not accepted)" if eng.get("moi_not_accepted") else ""))
    ger = record.get("language_german") or {}
    if ger.get("required"):
        lvl = ger.get("required_level_at_application") or ger.get("required_level") or ger.get("required_level_at_enrollment") or ""
        when = "at application" if ger.get("required_level_at_application") else ("by enrolment" if ger.get("required_level_at_enrollment") else "")
        out.append(f"German {lvl} {when}".strip())
    for t in record.get("standardized_test_requirements") or []:
        if t.get("required") or t.get("required_for") or t.get("recommended"):
            out.append(f"Test: {t.get('test', 'test')}" + (" (recommended)" if t.get("recommended") and not t.get("required") else ""))
    return out


def _committee_note(record: dict, fd: "FieldData | None"):
    """Koushik rule 30.10.2026: where the regulation says a committee decides whether the degree is
    comparable, the student is eligible WITH a following step (list 2, never list 1)."""
    if fd is None:
        return None
    rule = fd.config.get("committee_check", {}).get(record.get("id") or "")
    if not isinstance(rule, dict) or rule.get("field") not in (None, fd.field):
        return None
    return rule.get("note")


def _has_selection(record: dict, fd: "FieldData | None" = None) -> bool:
    sel = record.get("subsequent_selection_criteria_display") or {}
    adm = record.get("admission_type") or {}
    return (bool(sel.get("has_subsequent_hurdles")) or bool(adm.get("restricted")) or bool(adm.get("numerus_clausus"))
            or bool(_committee_note(record, fd)))


def evaluate_record(record: dict, student: dict, fd: FieldData) -> dict:
    """Gates in order: exclusion, degree, grade, total credits, subjects, conditions -> one of four lists."""
    rid = record["id"]
    res = {"program_id": rid, "record_id": rid, "program": record.get("program"), "university": record.get("university"),
           "list": None, "list_name": None, "route_used": None, "skipped_routes": [], "checks": [], "real_gap": 0.0,
           "reasons": [], "important_notes": _important_notes(record), "also_required": _also_required(record, student, fd),
           "unmet_areas": [], "selection_step": _has_selection(record, fd),
           "selection_notes": ([_committee_note(record, fd)] if _committee_note(record, fd) else []) + [n for n in (record.get("subsequent_selection_criteria_display") or {}).get("descriptive_notes") or []
                               if isinstance(n, str) and not n.startswith("IMPORTANT")]}

    def finish(lst):
        res["list"], res["list_name"] = lst, LIST_NAMES[lst]
        return res

    reason = _exclusion(rid, student, fd)                                   # gate 0: exclusions
    if reason:
        res["checks"].append({"label": "Programme exclusion", "kind": "exclusion", "status": "FAIL", "achieved": None, "shortfall": 0.0})
        res["reasons"].append(reason)
        return finish(4)

    deg_ok = _degree_matches(student, record, fd)                           # gate 1: degree field
    res["checks"].append({"label": "Degree field", "kind": "degree", "status": "PASS" if deg_ok else "FAIL",
                          "achieved": None, "shortfall": 0.0,
                          "detail": f"{student.get('degree_field')} vs accepted {record['accepted_degree_fields'].get('primary_fields')}"})
    hard_fail = [] if deg_ok else ["degree field not accepted"]

    rule, limit = record.get("gpa_rule_type"), (record.get("grade_requirement") or {}).get("value")   # gate 2: grade
    grade = float(student.get("german_grade"))
    if rule == "HARD_MAX_GRADE" and isinstance(limit, (int, float)):
        ok = grade <= float(limit) + 1e-9
        res["checks"].append({"label": "Minimum grade", "kind": "grade", "status": "PASS" if ok else "FAIL",
                              "achieved": grade, "required": float(limit), "shortfall": round(max(0.0, grade - float(limit)), 2)})
        if not ok:
            hard_fail.append(f"German grade {grade:.2f} is worse than the limit {float(limit):.2f}")
    else:
        res["checks"].append({"label": "Minimum grade", "kind": "grade", "status": "PASS", "achieved": grade, "shortfall": 0.0,
                              "detail": "no fixed grade limit"})

    need_total = record.get("minimum_total_ects")                           # degree total: NOTE ONLY
    if need_total:
        # Koushik (rule 2026, restated 29.10.2026): the programme's minimum total ECTS (e.g. 210) never decides the
        # verdict -- programmes also admit 180-ECTS degrees, with the missing ECTS made up after admission.
        have = float(student.get("total_ects") or 0)
        if have < float(need_total) - 1e-9:
            res["also_required"].append(
                f"Degree total: the programme asks for {float(need_total):g} ECTS and your degree shows {have:g} ECTS. "
                "Degrees with fewer ECTS are usually admitted with the missing ECTS made up after admission "
                "(internship or extra courses) -- see the programme note and the regulation.")

    courses = student_courses(student, fd)                                  # gate 4: subjects (C1-C4)
    subj = count_subjects(record, courses, fd)
    res["checks"].extend(subj)
    res["real_gap"] = real_gap(record, subj, fd)
    failed = [c for c in subj if c["status"] == "FAIL"]

    tol = fd.config.get("max_unmet_presence_items", {}).get(rid)            # tolerance rule (e.g. TU Dresden NES)
    if tol:
        unmet = [c for c in failed if c["item"] in tol["items"]]
        res["unmet_areas"] = [c["label"] for c in unmet]
        failed = [c for c in failed if c["item"] not in tol["items"]]
        if len(unmet) > tol["max"]:
            hard_fail.append(f"{len(unmet)} knowledge areas unmet; at most {tol['max']} may be unmet")

    if hard_fail:
        res["reasons"].extend(hard_fail)
        if failed:
            res["reasons"].append(f"{len(failed)} subject requirement(s) not met")
        return finish(4)
    if not failed:
        return finish(2 if _has_selection(record, fd) else 1)

    cond = record.get("conditional_admission") or {}                        # gate 5: conditions (Auflagen)
    if not cond.get("allowed"):
        res["reasons"].append(f"{len(failed)} subject requirement(s) not met and the programme allows no conditions")
        return finish(4)
    cap = cond.get("max_ects")
    if cap is not None and res["real_gap"] > float(cap) + 1e-9:
        res["reasons"].append(f"subject gap {res['real_gap']:g} ECTS is above the conditions cap of {float(cap):g}")
        return finish(4)
    caps = fd.config.get("area_caps", {}).get(rid)
    if caps:
        if res["real_gap"] > float(caps["total"]) + 1e-9:
            res["reasons"].append(f"subject gap {res['real_gap']:g} ECTS is above the total cap of {caps['total']:g}")
            return finish(4)
        for area in caps["areas"]:
            g = real_gap(record, subj, fd, item_ids=area["items"])
            if g > float(area["max"]) + 1e-9:
                res["reasons"].append(f"gap in {area['name']} is {g:g} ECTS, above its cap of {area['max']:g}")
                return finish(4)
    return finish(3)


# ============================================================================ 6. routes
def _route_members(program_id: str, fd: FieldData) -> list:
    groups = fd.config.get("route_groups", {}).get(fd.field, {})
    if program_id in groups:
        return groups[program_id]
    if program_id in fd.records:
        return [program_id]
    raise EngineError(f"programme {program_id!r} not found in the {fd.field} records")


def _route_open(rid: str, student: dict, fd: FieldData) -> tuple:
    gate = fd.config.get("gated_routes", {}).get(rid)
    if not gate:
        return True, None
    value = (student.get("confirmations") or {}).get(gate["needs"])
    if "min" in gate:
        return (value is not None and float(value) >= float(gate["min"])), gate["needs"]
    return (value == gate.get("equals", True)), gate["needs"]


def evaluate_program(program_id: str, student: dict, fd: FieldData) -> dict:
    """One result per programme: every open route evaluated, the best one shown (best list, then smallest gap)."""
    results, skipped = [], []
    for rid in _route_members(program_id, fd):
        ok, needs = _route_open(rid, student, fd)
        if not ok:
            skipped.append({"id": rid, "needs": needs, "why": fd.config["gated_routes"][rid].get("why", "")})
            continue
        results.append(evaluate_record(fd.records[rid], student, fd))
    if not results:
        raise EngineError(f"no open route for {program_id}; needs {skipped}")
    best = min(results, key=lambda r: (r["list"], r["real_gap"], sum(c["status"] == "FAIL" for c in r["checks"])))
    best = dict(best)
    best["program_id"] = program_id
    best["route_used"] = best["record_id"] if len(results) + len(skipped) > 1 else None
    best["skipped_routes"] = skipped
    return best


# ============================================================================ 7. whole field
def evaluate_field(student: dict, fd: FieldData) -> list:
    """Every programme of the student's field, route groups collapsed, sorted list 1 -> 4, then smallest gap."""
    groups = fd.config.get("route_groups", {}).get(fd.field, {})
    in_group = {m for ms in groups.values() for m in ms}
    ids = list(groups) + [rid for rid in fd.records if rid not in in_group]
    out = [evaluate_program(pid, student, fd) for pid in ids]
    return sorted(out, key=lambda r: (r["list"], r["real_gap"]))
