"""Koushik rule 30.10.2026: where the regulation says a committee decides whether the degree is comparable,
the student is eligible WITH a following step (list 2, never list 1). Synthetic student only."""
from gpur import engine

STUDENT = {"degree_field": "electrical_electronic_engineering", "degree_field_id": "electrical_electronic_engineering",
           "german_grade": 1.5, "total_ects": 240, "courses": [], "excluded_courses": [], "gate_score": None}


def test_committee_record_is_list2_with_step():
    fd = engine.load_field("eee")
    r = engine.evaluate_record(fd.records["4103"], dict(STUDENT), fd)
    assert r["list"] == 2 and r["selection_step"] is True
    assert r["selection_notes"][0].startswith("A committee checks whether your degree is comparable")


def test_record_without_committee_rule_unchanged():
    fd = engine.load_field("eee")
    assert "5625" not in fd.config["committee_check"]
    r = engine.evaluate_record(fd.records["5625"], dict(STUDENT), fd)
    assert not any(n.startswith("A committee checks") for n in r["selection_notes"])


def test_committee_rule_only_applies_in_its_own_field():
    fd = engine.load_field("cs")
    for rid, rule in fd.config["committee_check"].items():
        if rid.startswith("_") or rule["field"] == "cs":
            continue
        rec = {"id": rid}
        assert engine._committee_note(rec, fd) is None
