"""Taxonomy rule 7 in code: a lab gets its theory course's categories (synthetic JNTUH-style titles)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from lab_rule import apply_lab_rule, lab_theory_matches   # noqa: E402

TITLES = {
    "1": "PRINCIPLES OF COMPILER CONSTRUCTION", "2": "COMPILER CONSTRUCTION LAB",
    "3": "OPERATING SYSTEMS", "4": "ADVANCED OPERATING SYSTEMS", "5": "OPERATING SYSTEMS LAB",
    "6": "DATA COMMUNICATION AND COMPUTER NETWORKS", "7": "WEB PROGRAMMING",
    "8": "COMPUTER NETWORKS AND WEB PROGRAMMING LAB",
    "9": "ANALOG AND DIGITAL ELECTRONICS", "10": "ANALOG AND DIGITAL ELECTRONICS LAB",
    "11": "IT WORKSHOP AND MICROPROCESSOR LAB", "12": "ADVANCED COMMUNICATION SKILLS LAB",
}
CATS = {
    "1": ["programming_practical_cs", "theoretical_cs"], "2": ["programming_practical_cs"],
    "3": ["operating_systems"], "4": ["operating_systems", "computer_engineering"], "5": ["operating_systems"],
    "6": ["computer_networks", "computer_engineering"], "7": ["programming_practical_cs"], "8": ["computer_networks"],
    "9": ["electronics", "digital_systems"], "10": ["electronics"],
    "11": ["computer_engineering"], "12": [],
}


def run():
    cl = [{"course_id": k, "categories": list(v), "confidence": "HIGH"} for k, v in CATS.items()]
    return {c["course_id"]: c for c in apply_lab_rule(cl, TITLES)}


def test_contained_title_gets_theory_categories():
    assert run()["2"]["categories"] == ["programming_practical_cs", "theoretical_cs"]


def test_exact_match_wins_over_contained():
    assert run()["5"]["categories"] == ["operating_systems"]          # not ADVANCED OPERATING SYSTEMS


def test_combined_lab_gets_union_of_both_theories():
    assert run()["8"]["categories"] == ["computer_networks", "computer_engineering", "programming_practical_cs"]


def test_exact_title_with_and_is_not_split():
    assert run()["10"]["categories"] == ["electronics", "digital_systems"]


def test_unmatched_labs_keep_classifier_result():
    r = run()
    assert r["11"]["categories"] == ["computer_engineering"] and "lab_rule" not in r["11"]
    assert r["12"]["categories"] == [] and "lab_rule" not in r["12"]


def test_theory_courses_unchanged():
    r = run()
    assert r["1"]["categories"] == CATS["1"] and r["4"]["categories"] == CATS["4"]


def test_ambiguous_containment_is_not_guessed():
    m = lab_theory_matches(["DATA SCIENCE I", "APPLIED DATA SCIENCE", "DATA LAB"])
    assert "DATA LAB" not in m


def test_unsure_lab_follows_sure_theory_courses():
    """31.10.2026: JNTUK memo -- METROLOGY & INSTRUMENTATION LAB was MEDIUM, both theory courses HIGH."""
    titles = {"1": "METROLOGY", "2": "INSTRUMENTATION & CONTROL SYSTEMS", "3": "METROLOGY & INSTRUMENTATION LAB",
              "4": "ELECTRICAL & ELECTRONICS ENGG. LAB"}
    cl = [{"course_id": "1", "categories": ["measurement_instrumentation", "manufacturing_production"], "confidence": "HIGH"},
          {"course_id": "2", "categories": ["measurement_instrumentation", "control_systems"], "confidence": "HIGH"},
          {"course_id": "3", "categories": [], "confidence": "MEDIUM"},
          {"course_id": "4", "categories": [], "confidence": "MEDIUM"}]
    r = {c["course_id"]: c for c in apply_lab_rule(cl, titles)}
    assert r["3"]["confidence"] == "HIGH"
    assert r["3"]["categories"] == ["measurement_instrumentation", "manufacturing_production", "control_systems"]
    assert r["4"]["confidence"] == "MEDIUM" and r["4"]["categories"] == []      # no theory on the memo: stays flagged


def test_unsure_lab_stays_flagged_when_theory_unsure():
    titles = {"1": "METROLOGY", "2": "METROLOGY LAB"}
    cl = [{"course_id": "1", "categories": ["measurement_instrumentation"], "confidence": "MEDIUM"},
          {"course_id": "2", "categories": [], "confidence": "MEDIUM"}]
    r = {c["course_id"]: c for c in apply_lab_rule(cl, titles)}
    assert r["2"]["confidence"] == "MEDIUM"


def test_skill_labs_are_never_matched():
    """04.11.2026 batch 1 (S18): LANGUAGE LABORATORY must not follow FORMAL LANGUAGE & AUTOMATA THEORY."""
    titles = ["FORMAL LANGUAGE & AUTOMATA THEORY", "LANGUAGE LABORATORY", "ENGLISH LANGUAGE LAB",
              "COMMUNICATION SKILLS LAB", "SOFT SKILLS LAB", "PROFESSIONAL ENGLISH", "COMMUNICATION SKILLS"]
    m = lab_theory_matches(titles)
    for lab in ["LANGUAGE LABORATORY", "ENGLISH LANGUAGE LAB", "COMMUNICATION SKILLS LAB", "SOFT SKILLS LAB"]:
        assert lab not in m


def test_subject_labs_with_skill_like_words_still_match():
    titles = ["C LANGUAGE PROGRAMMING", "C LANGUAGE LAB", "SCRIPTING LANGUAGES", "SCRIPTING LANGUAGES LAB",
              "ANALOG AND DIGITAL COMMUNICATION", "COMMUNICATION LAB", "ENGINEERING PHYSICS", "PHYSICS LAB"]
    m = lab_theory_matches(titles)
    assert m["C LANGUAGE LAB"] and m["SCRIPTING LANGUAGES LAB"] and m["COMMUNICATION LAB"] and m["PHYSICS LAB"]
