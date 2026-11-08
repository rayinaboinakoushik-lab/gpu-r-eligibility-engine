"""Step 2b: student checks the values read from the transcript (synthetic data only)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import confirm_extraction as ce                      # noqa: E402
from transcript_parser import ExtractedCourse, TranscriptExtractionResult   # noqa: E402


def memo(**over):
    courses = [ExtractedCourse(f"X-{i}", f"Course {i}", 3.0) for i in range(41)]   # 123 credits
    kw = dict(student_name="Test Student", institution="Test College", program="INFORMATION TECHNOLOGY",
              regulation="R18", entry_type="lateral_entry", courses=courses, stated_total_credits=123,
              stated_cgpa=7.0, min_credits_for_award=123, years_with_courses=3)
    kw.update(over)
    return TranscriptExtractionResult(**kw)


def scripted(*answers):
    it = iter(answers)
    return lambda prompt="": next(it)


def test_fine_accepts_values_read_from_the_memo():
    e = memo()
    values, courses = ce.confirm(ce.initial_values(e), e.courses, input_fn=scripted("fine"), print_fn=lambda *a: None)
    d = ce.degree_from_confirmed(values)
    assert values["credits_for_award"] == 123 and values["years_studied"] == 3
    assert d["ects_factor"] == 1.5 and d["ects_basis"] == "official"      # 60 x 3 / 123 = 1.4634 -> 1.5
    assert d["lateral_entry"] is True


def test_student_corrects_a_wrong_value():
    e = memo(years_with_courses=4)                                          # misread
    values, _ = ce.confirm(ce.initial_values(e), e.courses, input_fn=scripted("7", "3", "fine"), print_fn=lambda *a: None)
    assert values["years_studied"] == 3


def test_missing_value_must_be_entered_before_fine():
    e = memo(min_credits_for_award=None, stated_total_credits=None, years_with_courses=None)
    out = []
    values, _ = ce.confirm(ce.initial_values(e), e.courses,
                           input_fn=scripted("fine", "7", "3", "fine"), print_fn=out.append)
    assert values["years_studied"] == 3
    assert values["credits_for_award"] == 123                              # falls back to the course sum
    assert any("still missing" in o for o in out)


def test_course_credit_correction_and_checksum():
    e = memo()
    e.courses[0].credits = 30.0                                             # misread 3 as 30
    vals = ce.initial_values(e)
    assert "MISMATCH" in ce.checksum_line(vals, e.courses)
    _, courses = ce.confirm(vals, e.courses, input_fn=scripted("c1", "", "3", "fine"), print_fn=lambda *a: None)
    assert courses[0].credits == 3.0 and "MATCH" in ce.checksum_line(vals, courses)


def test_apply_to_extraction_writes_confirmed_values_back():
    e = memo()
    vals = ce.initial_values(e)
    vals["stated_cgpa"] = 6.98
    ce.apply_to_extraction(e, vals)
    assert e.stated_cgpa == 6.98


def test_gate_is_optional():
    assert ce.ask_gate(input_fn=scripted(""), print_fn=lambda *a: None) is None
    assert ce.ask_gate(input_fn=scripted("abc", "640"), print_fn=lambda *a: None) == 640
