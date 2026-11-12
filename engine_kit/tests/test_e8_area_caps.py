"""E8 (11.11.2026, Koushik approved): per-area condition limits written in the regulations.
Expected values worked out by hand from the frozen records; boundary tests check both sides of each limit."""
import copy
import json
from pathlib import Path

from gpur import engine

M = "mathematics_statistics."; C = "computer_science_informatics."
FIX = Path(__file__).resolve().parent / "fixtures"


def cs_student(courses, excluded=None):
    return {"name": "t", "field": "cs", "degree_field": "computer_science", "degree_subfield": None,
            "german_grade": 2.0, "total_ects": 240, "country": "India", "confirmations": {},
            "excluded_courses": excluded or [],
            "courses": [{"id": f"c{i}", "title": t, "ects": e, "categories": cats} for i, (t, e, cats) in enumerate(courses)]}


def run(field, rid, student):
    fd = engine.load_field(field)
    return engine.evaluate_record(fd.records[rid], student, fd)


# ---------------------------------------------------------------- RWTH: maths gap at most 12 (SPO § 3 Abs. 2)
def test_rwth_3699_maths_gap_above_12_is_not_eligible():
    s = json.loads((FIX / "student_eee.json").read_text(encoding="utf-8"))   # maths gap 12.5
    r = run("eee", "3699", s)
    assert r["list"] == 4
    assert any("Höhere Mathematik is 12.5" in x for x in r["reasons"])


def test_rwth_3699_maths_gap_below_12_stays_bridging():
    s = json.loads((FIX / "student_eee.json").read_text(encoding="utf-8"))
    s["courses"].append({"id": "x1", "title": "Extra Calculus", "ects": 1, "categories": [M + "calculus_analysis"]})
    r = run("eee", "3699", s)                                                 # maths gap 11.5 <= 12
    assert r["list"] == 3


# ---------------------------------------------------------------- Oldenburg 9906: nested items (own_part_only)
BASE_CS = [("Algorithms", 5, [C + "algorithms_data_structures"]), ("Programming", 5, [C + "programming_practical_cs"])]


def test_oldenburg_only_statistics_missing_is_bridging():
    """Maths 15 without statistics: maths 20 is short 5, but only because statistics (bridgeable, max 5) is short 5."""
    s = cs_student([("Calculus", 10, [M + "calculus_analysis"]), ("Linear Algebra", 5, [M + "linear_algebra"])] + BASE_CS)
    r = run("cs", "9906", s)
    assert r["list"] == 3, r["reasons"]


def test_oldenburg_maths_short_beyond_its_parts_is_not_eligible():
    """Analysis/LA 10 and statistics 5 are met, maths is still short 5: that part cannot be bridged."""
    s = cs_student([("Calculus", 5, [M + "calculus_analysis"]), ("Linear Algebra", 5, [M + "linear_algebra"]),
                    ("Statistics", 5, [M + "statistics_probability"])] + BASE_CS)
    r = run("cs", "9906", s)
    assert r["list"] == 4
    assert any("mathematics 20" in x and "is 5 ECTS" in x for x in r["reasons"])
    assert not any("not counted yet" in x for x in r["reasons"])


def test_uncounted_course_note_on_area_cap():
    s = cs_student([("Calculus", 5, [M + "calculus_analysis"]), ("Linear Algebra", 5, [M + "linear_algebra"]),
                    ("Statistics", 5, [M + "statistics_probability"])] + BASE_CS,
                   excluded=[{"course_id": "e1", "title": "Mathematics-IA"}])
    r = run("cs", "9906", s)
    assert r["list"] == 4
    assert any("1 course(s) are not counted yet" in x for x in r["reasons"])


# ---------------------------------------------------------------- own_gap is opt-in: other areas are unchanged
def test_own_gap_equals_real_gap_without_nested_parts():
    fd = engine.load_field("eee")
    s = json.loads((FIX / "student_eee.json").read_text(encoding="utf-8"))
    rec = fd.records["3699"]
    checks = engine.count_subjects(rec, engine.student_courses(s, fd), fd)
    assert engine.own_gap(rec, checks, fd, [0]) == engine.real_gap(rec, checks, fd, item_ids=[0]) == 12.5


def test_e8_entries_cover_the_14_records():
    cfg = json.loads((FIX.parents[1] / "engine_config.json").read_text(encoding="utf-8"))["area_caps"]
    e8 = {"3698", "3699", "4811", "5226", "5227", "5228", "3827", "7657", "8353_BIS", "8353_DIS", "8353_SAR",
          "9906", "manual_rostock_csi", "manual_tubs_micro"}
    assert e8 <= set(cfg)
    assert cfg["5226"]["areas"][0]["max"] == 9 and cfg["3699"]["areas"][0]["max"] == 12
    assert [a["max"] for a in cfg["7657"]["areas"]] == [5] * 5 and cfg["7657"]["total"] == 20


# ---------------------------------------------------------------- Frankfurt UAS HIS 3903 (12.11.2026, Koushik approved)
def test_his_conditional_route_needs_special_qualification():
    """Grade 2.5 is only admitted with a proven special qualification (PO § 3 Abs. 5-6): gated, never open by default."""
    from rag_lab.experiment import students
    s = next(x for x in students() if x["name"] == "test_cs")              # grade 2.5, worse than the direct route's 1.8
    fd = engine.load_field("cs")
    closed = engine.evaluate_program("3903", s, fd)
    assert closed["list"] == 4
    assert any(k["id"] == "3903_CONDITIONAL" and k["needs"] == "special_qualification" for k in closed["skipped_routes"])
    s2 = {**s, "confirmations": {"special_qualification": True}}
    opened = engine.evaluate_program("3903", s2, fd)
    assert opened["list"] == 2 and opened["route_used"] == "3903_CONDITIONAL"
