"""Profile -> student -> engine -> report. Synthetic student only (no personal data in the repo)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from gpur import engine, profile as prof, report

REPO = Path(__file__).resolve().parents[1]
CS = "computer_science_informatics."
M = "mathematics_statistics."


def make_profile(**over):
    p = {
        "name": "Test Student", "field": "cs", "degree_field": "B.Tech Information Technology",
        "degree_field_id": "information_technology", "german_grade": 1.9, "country": "India",
        "ects_conversion": {"factor": 1.5, "basis": "official", "degree_years": 4, "lateral_entry": False,
                            "program_total_credits": 160, "memo_credits": 160, "memo_ects": 240},
        "courses": [
            {"course_id": "c1", "title": "Programming in C", "ects": 6, "categories": ["programming_practical_cs"]},
            {"course_id": "c2", "title": "Data Structures", "ects": 6, "categories": [CS + "algorithms_data_structures"]},
            {"course_id": "c3", "title": "Mathematics I", "ects": 6, "categories": [M + "calculus_analysis"]},
            {"course_id": "c4", "title": "English", "ects": 3, "categories": []},
        ],
        "excluded_courses": [{"course_id": "c9", "title": "Elective X"}],
    }
    p.update(over)
    return p


@pytest.mark.parametrize("text,expected", [
    ("B.Tech Information Technology", "information_technology"),
    ("Bachelor of Technology in Computer Science and Engineering", "computer_science"),
    ("B.Tech CSE (AI & ML)", "cse_specialisations"),
    ("Electronics and Communication Engineering", "electronics_communication"),
    ("Electrical and Electronics Engineering", "electrical_electronic_engineering"),
    ("B.Tech Mechatronics", "mechanical_related"),
    ("Civil Engineering", "civil_engineering"),
    ("Bachelor of Arts in History", None),
])
def test_degree_guess(text, expected):
    assert prof.guess_degree_field(text) == expected


def test_build_student_short_names_total_and_skips():
    s, warnings = prof.build_student(make_profile())
    assert s["total_ects"] == 240                                  # 160 memo credits x 1.5
    assert [c["id"] for c in s["courses"]] == ["c1", "c2", "c3"]   # course without categories counts nowhere
    assert s["courses"][0]["categories"] == [CS + "programming_practical_cs"]   # short name -> full id
    assert warnings == []


def test_sum_category_on_course_is_ignored_with_warning():
    p = make_profile()
    p["courses"][0]["categories"] = ["programming_practical_cs", CS + "general_cs"]
    s, warnings = prof.build_student(p)
    assert s["courses"][0]["categories"] == [CS + "programming_practical_cs"]
    assert any("general_cs" in w for w in warnings)


def test_unknown_category_stops():
    p = make_profile()
    p["courses"][0]["categories"] = ["web_development"]
    with pytest.raises(engine.EngineError):
        prof.build_student(p)


def test_old_profile_without_courses_is_refused():
    p = make_profile()
    del p["courses"]
    with pytest.raises(engine.EngineError, match="course list"):
        prof.build_student(p)


def test_estimated_ects_warns():
    p = make_profile(ects_conversion={"factor": 1.6, "basis": "approximate", "degree_years": 4, "memo_credits": 150})
    _, warnings = prof.build_student(p)
    assert any("estimates" in w for w in warnings)


def test_whole_field_runs_and_report_renders():
    s, w = prof.build_student(make_profile())
    fd = engine.load_field("cs")
    results = engine.evaluate_field(s, fd)
    assert len(results) == 103                                      # 116 records, route groups collapsed
    assert all(r["list"] in (1, 2, 3, 4) for r in results)
    assert [r["list"] for r in results] == sorted(r["list"] for r in results)
    txt, md = report.to_text(s, results, w), report.to_markdown(s, results, w)
    assert "programmes checked" in txt and "Elective X" in txt
    assert md.startswith("# Eligibility report") and "| 4 | not eligible |" in md


def test_cli_end_to_end(tmp_path):
    path = tmp_path / "final_matching_profile_test.json"
    path.write_text(json.dumps(make_profile()), encoding="utf-8")
    run = subprocess.run([sys.executable, str(REPO / "pipeline" / "run_eligibility.py"), str(path), "--no-questions"],
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stdout + run.stderr
    assert (tmp_path / "eligibility_test.json").exists() and (tmp_path / "eligibility_test.md").exists()
    data = json.loads((tmp_path / "eligibility_test.json").read_text(encoding="utf-8"))
    assert len(data["results"]) == 103 and "courses" not in data["student"]


def test_lateral_entry_counts_memo_credits_only():
    """As before (audit 06.10): lateral entry = credits on the memo x factor, never the nominal degree."""
    p = make_profile(ects_conversion={"factor": 1.5, "basis": "official", "degree_years": 4, "lateral_entry": True,
                                      "program_total_credits": 160, "memo_credits": 123})
    s, _ = prof.build_student(p)
    assert s["total_ects"] == 184.5 and s["lateral_entry"] is True


def test_three_year_degree_factor():
    """3 years, 160 credits -> 60 x 3 / 160 = 1.125, rounded up to 1 decimal = 1.2 (Koushik 28.10.2026)."""
    import importlib, sys as _s
    _s.path.insert(0, str(REPO / "pipeline"))
    gc = importlib.import_module("german_conversion")
    f = gc.compute_ects_factor(3, False, 160, 160)
    assert f.factor == 1.2
    assert gc.compute_ects_factor(4, True, 123, 160).factor == 1.5          # exact 1.5 stays 1.5
    assert gc.compute_ects_factor(3, True, 123, 123).factor == 1.5          # memo values: 1.4634 -> 1.5
    assert gc.compute_ects_factor(4, False, 180, 180).factor == 1.4         # 1.333 -> 1.4


def test_degree_total_never_decides_the_verdict():
    """Koushik 29.10.2026: minimum total ECTS is a note, never a check (programmes also admit 180 ECTS)."""
    fd = engine.load_field("cs")
    rec = dict(next(r for r in fd.records.values() if r.get("minimum_total_ects")))
    rec["minimum_total_ects"] = 210
    s = {"degree_field": "computer_science", "german_grade": 1.0, "total_ects": 184.5, "courses": [], "country": "India"}
    r = engine.evaluate_record(rec, s, fd)
    assert not any(c["kind"] == "total" for c in r["checks"])
    assert not any("total" in x for x in r["reasons"])
    assert any("Degree total" in a and "210" in a for a in r["also_required"])
    s["total_ects"] = 240
    r = engine.evaluate_record(rec, s, fd)
    assert not any("Degree total" in a for a in r["also_required"])


def test_bridging_with_selection_shows_selection_step():
    """29.10.2026: a list-3 programme that also has a selection step says so in the report."""
    fd = engine.load_field("cs")
    rec = fd.records["8935"]                       # Hannover CS: conditions allowed + ranking by grade
    s = {"degree_field": "computer_science", "german_grade": 2.0, "total_ects": 240, "ects_factor": 1.5,
         "country": "India", "courses": [], "excluded_courses": []}
    r = engine.evaluate_record(rec, s, fd)
    assert r["selection_step"] is True and r["selection_notes"]
    r = dict(r, list=3)
    txt = report.to_text({**s, "name": "T", "field": "cs"}, [r], [])
    assert "Selection step" in txt
