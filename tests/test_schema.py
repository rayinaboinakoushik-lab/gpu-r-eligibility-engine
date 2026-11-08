"""The schema must accept every frozen record and reject typical real mistakes."""
import copy, json
from pathlib import Path

import pytest
from pydantic import ValidationError

from gpur.schema import Record

DATA = Path(__file__).resolve().parent.parent / "data" / "frozen"
RECS = [r for f in sorted(DATA.glob("GPU-R_*_FROZEN_*.json")) for r in json.loads(f.read_text(encoding="utf-8"))]


@pytest.mark.skipif(not RECS, reason="frozen data not present")
def test_all_frozen_records_load():
    for r in RECS:
        Record.model_validate(r)


def _one():
    if not RECS:
        pytest.skip("frozen data not present")
    return copy.deepcopy(next(r for r in RECS if r["id"] == "8911"))


@pytest.mark.parametrize("mutate, why", [
    (lambda r: r.update(gpa_rule_type="HARD_MAX_GRADE"), "hard grade without a value"),
    (lambda r: r["conditional_admission"].update(allowed=None), "conditions must be true/false"),
    (lambda r: r["language_english"].update(ielts_min=6.3), "IELTS not a half band"),
    (lambda r: r["subject_credit_requirements"]["items"][0].update(min_ects=None), "item without ECTS and not presence-only"),
    (lambda r: r.update(unexpected_key=1), "unknown key (typo)"),
    (lambda r: r["logistics"]["non_eu_deadlines"].update(winter=None), "intake without a deadline"),
    (lambda r: r["conditional_admission"].update(allowed="yes"), "conditions as text \"yes\" (must be true/false; found 27.10)"),
    (lambda r: r["subject_credit_requirements"]["items"][0].update(requires_subject_presence_only="false"), "presence flag as text"),
])
def test_validator_catches_real_errors(mutate, why):
    r = _one(); mutate(r)
    with pytest.raises(ValidationError):
        Record.model_validate(r)
