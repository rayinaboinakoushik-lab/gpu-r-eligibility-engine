"""The relabelled answer keys (30.10.2026) only use categories the field's classifier can output."""
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("field", ["cs", "eee", "mechanical", "civil"])
def test_key_categories_exist_in_field_file(field):
    key = json.loads((REPO / "tests" / "gold" / f"answer_key_{field}.json").read_text(encoding="utf-8"))
    atomic = set(json.loads((REPO / "data" / "taxonomy" / f"{field}_taxonomy.json").read_text(encoding="utf-8"))["category_evidence_status"])
    assert key["field"] == field
    bad = {c["title"]: [x for x in c["expected"] if x not in atomic] for c in key["courses"] if any(x not in atomic for x in c["expected"])}
    assert not bad, bad
    ids = [c["id"] for c in key["courses"]]
    assert len(ids) == len(set(ids))
