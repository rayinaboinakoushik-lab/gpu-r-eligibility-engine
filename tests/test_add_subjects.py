"""Koushik 30.10.2026: 10473 (FH Westküste) item 0 also counts ICT core: computer engineering + computer networks."""
from gpur import engine

CS = "computer_science_informatics."


def test_10473_counts_ict_core_not_general_cs():
    fd = engine.load_field("eee")
    t = engine.target_set(fd.records["10473"]["subject_credit_requirements"]["items"][0], fd, "10473", 0)
    assert CS + "computer_engineering" in t and CS + "computer_networks" in t
    assert "electrical_electronic_engineering.electronics" in t
    for c in ("programming_practical_cs", "operating_systems", "machine_learning_ai", "databases_systems"):
        assert CS + c not in t


def test_other_records_unchanged():
    fd = engine.load_field("eee")
    rid = next(r for r in fd.records if r != "10473" and fd.records[r]["subject_credit_requirements"]["items"])
    item = fd.records[rid]["subject_credit_requirements"]["items"][0]
    base = set().union(*(engine.expand(c, fd) for c in engine.item_categories(item)))
    assert engine.target_set(item, fd, rid, 0) == base - set(
        fd.config.get("separate_subjects", {}).get(rid, {}).get("0", []))
