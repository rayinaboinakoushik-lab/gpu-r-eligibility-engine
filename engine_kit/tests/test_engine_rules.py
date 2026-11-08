"""
GPU-R engine rule tests — one test per rule of 'GPU-R Matching Engine Spec v1' (26.10.2026).
Run:  pytest -q engine_kit/tests
Engine tests skip until gpur_adapter.evaluate() is wired; config tests run now.
Expected values are worked out by hand from the frozen records of 24.10.2026.
"""
import json
from pathlib import Path

import pytest

import gpur_adapter as A

M = "mathematics_statistics."; C = "computer_science_informatics."; P = "physics_natural_sciences."
CE = "civil_engineering."; ME = "mechanical_manufacturing_engineering."; EE = "electrical_electronic_engineering."
FROZEN = next((p for p in (A.KIT.parent / "data" / "frozen", A.KIT.parent / "frozen_2026-10-24") if p.exists()), A.KIT.parent / "data" / "frozen")


def student(field, degree_field, courses, grade=2.0, **extra):
    s = {"name": "t", "field": field, "degree_field": degree_field, "degree_subfield": extra.pop("sub", None),
         "german_grade": grade, "total_ects": extra.pop("total_ects", 240), "country": "India",
         "confirmations": extra.pop("confirmations", {}), "excluded_courses": [],
         "courses": [{"id": f"c{i}", "title": t, "ects": e, "categories": cats} for i, (t, e, cats) in enumerate(courses)]}
    s.update(extra)
    return s


def run(field, pid, s, records=None):
    try:
        return A.evaluate(field, pid, s, records_override=records)
    except NotImplementedError:
        pytest.skip("gpur_adapter.evaluate() not wired yet")


def subj(res):
    return [c for c in res["checks"] if c["kind"] == "subject"]


# ---------------------------------------------------------------- counting rules
def test_C1_add_up_8911():
    """8911 needs 40 from maths+mechanics+physics+CS: 20+10+5+5 = 40 -> pass (today's engine: fail)."""
    s = student("civil", "civil_engineering", [
        ("Calculus", 10, [M + "calculus_analysis"]), ("Linear Algebra", 5, [M + "linear_algebra"]),
        ("Statistics", 5, [M + "statistics_probability"]), ("Engineering Mechanics", 10, [CE + "structural_mechanics"]),
        ("Physics", 5, [P + "general_physics"]), ("Programming", 5, [C + "programming_practical_cs"])])
    r = run("civil", "8911", s)
    assert all(c["status"] == "PASS" for c in subj(r))
    assert subj(r)[0]["achieved"] == 40
    assert r["list"] == 2          # online aptitude test follows -> selection criteria


def test_C2_nested_gap_8911():
    """Maths 15 (no statistics): 40 total passes, maths 20 short 5, statistics short 5; real gap 5, not 10."""
    s = student("civil", "civil_engineering", [
        ("Calculus", 10, [M + "calculus_analysis"]), ("Linear Algebra", 5, [M + "linear_algebra"]),
        ("Engineering Mechanics", 10, [CE + "structural_mechanics"]), ("Physics", 5, [P + "general_physics"]),
        ("Programming", 10, [C + "programming_practical_cs"])])
    r = run("civil", "8911", s)
    sc = subj(r)
    assert sc[0]["status"] == "PASS" and sc[0]["achieved"] == 40
    assert sc[1]["status"] == "FAIL" and sc[1]["shortfall"] == 5      # maths 20
    assert sc[4]["status"] == "FAIL" and sc[4]["shortfall"] == 5      # statistics 5
    assert r["real_gap"] == 5
    assert r["list"] == 4          # 8911 allows no conditions


def test_C3_named_twice_4124A():
    """WATENV names fluid mechanics in natural sciences 18 AND water 30 -> one 6-ECTS course counts in both."""
    s = student("civil", "civil_engineering", [
        ("Calculus", 12, [M + "calculus_analysis"]), ("Statistics", 6, [M + "statistics_probability"]),
        ("Programming", 12, [C + "programming_practical_cs"]), ("Physics", 12, [P + "general_physics"]),
        ("Fluid Mechanics", 6, [CE + "fluid_mechanics"]), ("Water Resources", 24, [CE + "water_engineering"])])
    r = run("civil", "4124_A", s)
    sc = subj(r)
    assert sc[2]["status"] == "PASS" and sc[2]["achieved"] == 18      # 12 physics + 6 fluid
    assert sc[3]["status"] == "PASS" and sc[3]["achieved"] == 30      # 24 water + 6 fluid


SYNTH_C4 = {"id": "synthetic_c4", "program": "Synthetic C4", "university": "Test", "_domain": "computer_science",
            "accepted_degree_fields": {"primary_fields": ["computer_science"]}, "gpa_rule_type": "NO_GRADE_THRESHOLD",
            "grade_requirement": {"value": None},
            "subject_credit_requirements": {"items": [
                {"raw_label": "maths 18", "canonical_category": M + "general_mathematics", "covered_categories": [], "min_ects": 18, "requires_subject_presence_only": False},
                {"raw_label": "theoretical CS 8", "canonical_category": C + "theoretical_cs", "covered_categories": [], "min_ects": 8, "requires_subject_presence_only": False}]},
            "conditional_admission": {"allowed": False, "max_ects": None, "mechanism": ""},
            "subsequent_selection_criteria_display": {"has_subsequent_hurdles": False, "descriptive_notes": []},
            "minimum_total_ects": None, "language_english": {}, "language_german": {"required": False},
            "standardized_test_requirements": [], "aps_certificate": None, "admission_type": {"restricted": False, "numerus_clausus": False}}


def test_C4_classified_twice_counts_once():
    """Discrete Mathematics 6 is maths AND theory by our classifier; the regulation links neither -> counts once.
    Both assignments leave shortfall 4; tie -> first item (maths). Maths 20 pass, theory 4 short 4."""
    s = student("cs", "computer_science", [
        ("Discrete Mathematics", 6, [M + "discrete_math_logic", C + "theoretical_cs"]),
        ("Calculus", 14, [M + "calculus_analysis"]), ("Automata Theory", 4, [C + "theoretical_cs"])])
    r = run("cs", "synthetic_c4", s, records=[SYNTH_C4])
    sc = subj(r)
    assert sc[0]["status"] == "PASS" and sc[0]["achieved"] == 20
    assert sc[1]["status"] == "FAIL" and sc[1]["shortfall"] == 4
    assert r["list"] == 4


# ---------------------------------------------------------------- routes and gates
EEE_4594 = [("Calculus", 9, [M + "calculus_analysis"]), ("Linear Algebra", 9, [M + "linear_algebra"]),
            ("Electromagnetic Fields", 6, [EE + "electromagnetic_field_theory"]), ("Programming", 6, [C + "programming_practical_cs"])]


def test_gated_route_closed_without_gate():
    r = run("eee", "4594", student("eee", "electrical_electronic_engineering", EEE_4594, grade=2.5))
    assert r["route_used"] == "4594_A"
    assert any(x["id"] == "4594_B" and x["needs"] == "gate_score" for x in r["skipped_routes"])
    assert r["list"] == 4          # route A: grade 2.5 > 1.9


def test_gated_route_open_with_gate():
    r = run("eee", "4594", student("eee", "electrical_electronic_engineering", EEE_4594, grade=2.5,
                                   confirmations={"gate_score": 520}))
    assert r["route_used"] == "4594_B"
    assert r["list"] in (1, 2)


# ---------------------------------------------------------------- exclusions, degree gate, caps
def test_exclusion_4202_india():
    r = run("mechanical", "4202", student("mechanical", "mechanical_engineering", [], grade=1.5))
    assert r["list"] == 4 and any("R16" in x or "equivalent" in x for x in r["reasons"])


def test_exclusion_10623_ece_not_shown():
    r = run("eee", "10623", student("eee", "electrical_electronic_engineering", [], grade=1.5, sub="electronics_communication"))
    assert r["list"] == 4


def test_degree_gate_3847_me_cs_degree():
    r = run("mechanical", "3847_me", student("mechanical", "computer_science", [], grade=1.5))
    assert r["list"] == 4 and any(c["kind"] == "degree" and c["status"] == "FAIL" for c in r["checks"])


def test_area_cap_6318_maths():
    """Maths 4 of 16, no statistics -> maths gap 12 > maths cap 10 (total gap 15 <= 20) -> not eligible."""
    s = student("civil", "civil_engineering", [
        ("Calculus", 4, [M + "calculus_analysis"]),
        ("Mechanics", 16, [CE + "structural_mechanics"]), ("Hydromechanics", 6, [CE + "fluid_mechanics"]),
        ("Water Engineering", 40, [CE + "water_engineering"]), ("Structural Engineering", 25, [CE + "structural_engineering"]),
        ("Programming", 6, [C + "programming_practical_cs"])])
    r = run("civil", "6318", s)
    assert r["real_gap"] == 15
    assert r["list"] == 4 and any("cap" in x.lower() for x in r["reasons"])


# ---------------------------------------------------------------- display
def test_important_note_first_9179():
    r = run("civil", "9179", student("civil", "civil_engineering", [], grade=2.0))
    assert r["important_notes"] and r["important_notes"][0].startswith("IMPORTANT") and "MOI" in r["important_notes"][0]


def test_aps_always_for_india():
    r = run("civil", "9179", student("civil", "civil_engineering", [], grade=2.0))   # record lists no APS country
    assert any("APS" in x for x in r["also_required"])


# ---------------------------------------------------------------- config (runs now)
def _records():
    out = {}
    for f in FROZEN.glob("GPU-R_*_FROZEN_*.json"):
        for r in json.loads(f.read_text(encoding="utf-8")):
            out[r["id"]] = r
    return out


def test_config_matches_frozen_records():
    if not FROZEN.exists():
        pytest.skip("frozen folder not found")
    cfg = json.loads(A.CONFIG.read_text(encoding="utf-8")); recs = _records()
    for rid in [k for k in cfg["gated_routes"] if not k.startswith("_")] + [k for k in cfg["exclusions"] if not k.startswith("_")]:
        assert rid in recs, rid
    for fld, groups in cfg["route_groups"].items():
        if fld.startswith("_"):
            continue
        for ids in groups.values():
            for i in ids:
                assert i in recs, i
    for rid, cap in cfg["area_caps"].items():
        if rid.startswith("_"):
            continue
        items = recs[rid]["subject_credit_requirements"]["items"]
        for area in cap["areas"]:
            for ix, start in zip(area["items"], area["label_starts"]):
                assert items[ix]["raw_label"].startswith(start), (rid, ix)


def test_frozen_files_match_manifest():
    import hashlib
    man = FROZEN / "MANIFEST.json"
    if not man.exists():
        pytest.skip("manifest not found")
    for entry in json.loads(man.read_text()):
        h = hashlib.sha256((FROZEN / entry["file"]).read_bytes()).hexdigest()
        assert h == entry["sha256"], entry["file"]


# ---------------------------------------------------------------- same-subject rules (taxonomy 65, 26.10.2026)
def test_S1_same_subject_counts_once_6318():
    """Engineering Mechanics carries BOTH mechanics names (rule S1). 6318 'Mechanik 16' lists both:
    the 6-ECTS course must count 6, never 12 (OR, not AND)."""
    s = student("civil", "civil_engineering", [
        ("Engineering Mechanics", 6, [CE + "structural_mechanics", ME + "mechanics_dynamics"])])
    r = run("civil", "6318", s)
    mech = subj(r)[3]
    assert mech["achieved"] == 6 and mech["shortfall"] == 10


# ---------------------------------------------------------------- tolerance rule (one area may be unmet), 27.10.2026
NES_ALL = [("Engineering Mathematics", 12, [M + "calculus_analysis"]), ("Digital Electronics", 6, [EE + "digital_systems"]),
           ("Electromagnetic Fields", 6, [EE + "electromagnetic_field_theory"]), ("Signals and Systems", 6, [EE + "signals_systems"]),
           ("VLSI Design", 6, [EE + "microelectronics_semiconductors"]), ("Java Programming", 6, [C + "programming_practical_cs"])]


def test_tud_nes_one_area_missing_is_eligible():
    """manual_tud_nes: at most ONE of six areas may be unmet -> missing only systems theory is still eligible."""
    s = student("eee", "electrical_electronic_engineering", [c for c in NES_ALL if c[0] != "Signals and Systems"])
    r = run("eee", "manual_tud_nes", s)
    assert r["list"] in (1, 2)


def test_tud_nes_two_areas_missing_not_eligible():
    """Missing fields AND systems theory (Koushik's case) -> not eligible; never 'bridging possible'."""
    s = student("eee", "electrical_electronic_engineering",
                [c for c in NES_ALL if c[0] not in ("Signals and Systems", "Electromagnetic Fields")])
    r = run("eee", "manual_tud_nes", s)
    assert r["list"] == 4


def test_tolerance_config_matches_record():
    if not FROZEN.exists():
        pytest.skip("frozen folder not found")
    cfg = json.loads(A.CONFIG.read_text(encoding="utf-8"))
    recs = _records()
    for rid, rule in cfg.get("max_unmet_presence_items", {}).items():
        if rid.startswith("_"):
            continue
        items = recs[rid]["subject_credit_requirements"]["items"]
        for ix, start in zip(rule["items"], rule["label_starts"]):
            assert items[ix]["raw_label"].startswith(start), (rid, ix)
            assert items[ix]["requires_subject_presence_only"], (rid, ix)
        assert recs[rid]["conditional_admission"]["allowed"] is False, rid


# ---------------------------------------------------------------- degree equivalences (data/taxonomy/degree_fields.json)
def test_degree_gate_it_counts_as_cs():
    """B.Tech IT counts as computer_science (approved 26.10.2026): the degree check passes on a CS record."""
    r = run("cs", "6937", student("cs", "information_technology", [], grade=2.0))
    assert any(c["kind"] == "degree" and c["status"] == "PASS" for c in r["checks"])


def test_degree_gate_ece_counts_as_eee_but_not_10623():
    r = run("eee", "8996", student("eee", "electronics_communication", [], grade=2.0))
    assert any(c["kind"] == "degree" and c["status"] == "PASS" for c in r["checks"])


def test_statistics_only_under_statistik_6318():
    """Koushik 27.10.2026: Mathematik 16 and Statistik 3 are separate parts of the 41. A statistics course fills
    Statistik (and the 41), never Mathematik. Calculus 13 + Statistics 6 -> Mathematik 13 of 16 (gap 3)."""
    s = student("civil", "civil_engineering", [
        ("Calculus", 13, [M + "calculus_analysis"]), ("Statistics", 6, [M + "statistics_probability"]),
        ("Mechanics", 16, [CE + "structural_mechanics"]), ("Hydromechanics", 6, [CE + "fluid_mechanics"]),
        ("Water Engineering", 40, [CE + "water_engineering"]), ("Structural Engineering", 25, [CE + "structural_engineering"]),
        ("Programming", 6, [C + "programming_practical_cs"])])
    r = run("civil", "6318", s)
    subj = [c for c in r["checks"] if c["kind"] == "subject"]
    assert subj[1]["achieved"] == 13 and subj[1]["shortfall"] == 3      # Mathematik: statistics not counted
    assert subj[2]["status"] == "PASS"                                   # Statistik
    assert subj[0]["achieved"] == 41                                     # the 41 counts everything once
    assert r["real_gap"] == 3 and r["list"] == 3


def test_statistics_of_which_mathematik_8911_still_nested():
    """8911 says 'Mathematik 20, of which Statistik 5': statistics counts in both (not in separate_subjects)."""
    cfg = json.loads(A.CONFIG.read_text(encoding="utf-8"))
    assert "8911" not in cfg["separate_subjects"]
