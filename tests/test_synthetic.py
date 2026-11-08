"""31.10.2026: synthetic test transcripts -- generator is deterministic and consistent; scorer catches errors."""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import synthetic_transcripts as S  # noqa: E402

SPECS = sorted((REPO / "tests" / "synthetic" / "specs").glob("*.json"))
DEGREE = {"cs": "computer_science", "eee": "electronics_communication", "mechanical": "mechanical_engineering",
          "civil": "civil_engineering"}


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


def truth_of(spec):
    t = S.truth_for(spec, S.assign_grades(spec))
    lab = REPO / "tests" / "synthetic" / "labels" / f"{spec['id']}.json"
    t["gold"] = load(lab)["labels"]
    return t


@pytest.mark.parametrize("p", SPECS, ids=lambda p: p.stem)
def test_spec_is_consistent(p):
    spec = load(p)
    t = truth_of(spec)
    ex = t["extraction"]
    assert ex["credits_registered"] == sum(c["credits"] for c in ex["courses"])
    if spec["credits_for_award_printed"]:
        assert spec["credits_for_award_printed"] == ex["credits_registered"]
    assert spec["pass_min"] <= ex["cgpa"] <= spec["grading"][0][1]
    assert set(t["gold"]) == {c["full_title"] for c in ex["courses"]}          # every course has a label (or null)
    assert t == truth_of(spec)                                            # deterministic


@pytest.mark.parametrize("p", SPECS, ids=lambda p: p.stem)
def test_labels_use_only_field_categories(p):
    spec = load(p)
    valid = set(load(REPO / "data" / "taxonomy" / f"{spec['field']}_taxonomy.json")["category_evidence_status"])
    for title, cats in load(REPO / "tests" / "synthetic" / "labels" / f"{spec['id']}.json")["labels"].items():
        assert cats is None or set(cats) <= valid, title


def fake_run(t, break_one=False):
    ex = t["extraction"]
    ck = {"cgpa": ex["cgpa"], "degree_years": ex["years_studied"], "lateral_entry": ex["entry_type"] == "lateral_entry",
          "all_courses_raw": [{"course_id": c["code"], "title": c["title"], "credits": c["credits"]} for c in ex["courses"]]}
    courses = [{"course_id": c["code"], "title": c["title"], "credits": c["credits"],
                "categories": t["gold"].get(c["full_title"]) or []} for c in ex["courses"]]
    if break_one:
        ck["all_courses_raw"] = ck["all_courses_raw"][1:]
        k = next(i for i, c in enumerate(ex["courses"]) if t["gold"].get(c["full_title"]))
        courses[k] = {**courses[k], "categories": []}
    pr = {"field": t["field"], "german_grade": 2.0, "ects_conversion": {"factor": 1.5, "memo_ects": 240},
          "courses": courses, "excluded_courses": [], "degree_field_id": DEGREE[t["field"]]}
    return ck, pr


@pytest.mark.parametrize("p", SPECS[:2], ids=lambda p: p.stem)
def test_scorer_perfect_run_scores_perfect(p):
    t = truth_of(load(p))
    ck, pr = fake_run(t)
    r = S.score(t, ck, pr)
    assert r["reading"]["courses_found"][0] == r["reading"]["courses_found"][1]
    assert not r["reading"]["missing"] and not r["reading"]["credit_mismatch"]
    assert r["classification"]["wrong"] == [] and r["classification"]["not_counted"] == []


def test_scorer_catches_a_missing_course_and_a_wrong_label():
    t = truth_of(load(SPECS[0]))
    ck, pr = fake_run(t, break_one=True)
    r = S.score(t, ck, pr)
    assert len(r["reading"]["missing"]) == 1
    assert len(r["classification"]["wrong"]) == 1


def test_abbreviated_titles_keep_a_link_to_the_full_title():
    spec = next(load(p) for p in SPECS if load(p).get("abbreviate"))
    ex = truth_of(spec)["extraction"]
    assert any(c["title"] != c["full_title"] for c in ex["courses"])
    assert all(len(c["title"]) <= 45 for c in ex["courses"])


def test_log_record_and_report(tmp_path, monkeypatch):
    """score -> one log record -> report with targets, categories and sources (no AI call, temp files only)."""
    import eval_log as E
    monkeypatch.setattr(E, "RESULTS", tmp_path)
    monkeypatch.setattr(E, "LOG", tmp_path / "eval_log.jsonl")
    monkeypatch.setattr(E, "REPORT", tmp_path / "EVAL_REPORT.md")
    t = truth_of(load(SPECS[0]))
    ck, pr = fake_run(t, break_one=True)
    ck["resolved"] = [{"course_id": c["course_id"], "confidence": "HIGH", "reasoning": "approved GPU-R course map"}
                      for c in ck["all_courses_raw"]]
    res = S.score(t, ck, pr)
    assert {c["source"] for c in res["courses"] if c["verdict"] != "not_read"} == {"map"}
    assert sum(c["verdict"] == "not_read" for c in res["courses"]) == 1
    E.append({"sample": t["id"], "session": "x", "split": "dev", "field": t["field"], "university": "U", "layout": "table",
              "abbreviated": False, "version": {"version": "v1"}, "usage": {"available": False},
              **{k: res[k] for k in res if k != "id"}})
    text = E.report()
    assert "Targets — dev set (1 samples" in text and "Accuracy by answer source" in text
    assert "| map |" in text and (tmp_path / "EVAL_REPORT.md").exists()


def test_batch_runner_answers_like_a_careful_student_and_stops_on_unknown_questions():
    import run_batch as RB
    spec = next(load(p) for p in SPECS if load(p)["id"].startswith("S01"))
    t = truth_of(spec)
    tee = RB.Tee(None)
    st = RB.Student(spec, t, Path("synthetic_out/S01.jpg"), tee)
    assert st.answer("Path to your transcript file (image or PDF): ").endswith("S01.jpg")
    assert st.answer("Minimum PASSING grade on your transcript's scale (Nmin) -- NOT zero [4.0]: ") == "4"
    # check screen shows a misread CGPA -> correct field 5 to the memo value, then accept
    tee.write("=== Please check what was read from your transcript ===\n  5. CGPA (as printed): 9.99\n"
              "  6. Entry type (regular / lateral_entry): regular\n  7. Years studied (years with courses on the memo): 4\n"
              "  8. Credits registered (as printed): 160\n  9. Credits required for the award of the degree (as printed): 160\n")
    assert st.answer('\nType "fine" if everything is correct, or the number to correct: ') == "5"
    assert st.answer("  New value for 'CGPA (as printed)': ") == str(t["extraction"]["cgpa"])
    assert st.answer('\nType "fine" if everything is correct, or the number to correct: ') == "fine"
    assert st.corrections == [{"field": 5, "shown": "9.99", "corrected_to": t["extraction"]["cgpa"]}]
    assert st.answer("Your GATE score, or press Enter to skip: ") == ""
    assert st.answer("Do you have at least 10 subject/thesis points as the programme requires? (y/n) ") == "n"
    with pytest.raises(RB.UnknownQuestion):
        st.answer("What is your favourite colour? ")
