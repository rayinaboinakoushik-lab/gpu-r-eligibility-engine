"""
The ONE place that connects the engine tests to the engine (gpur/engine.py).

evaluate() returns a plain dict per PROGRAMME (route groups collapsed):
{
  "program_id":      "4594",                 # base id of the route group, or the record id
  "list":            1 | 2 | 3 | 4,          # 1 eligible, no selection step, 2 eligible with selection criteria,
                                             # 3 bridging possible, 4 not eligible
  "route_used":      "4594_A" or None,
  "skipped_routes":  [{"id": "4594_B", "needs": "gate_score"}],
  "checks":          [{"label": "...", "kind": "grade"|"subject"|"degree"|"total"|"exclusion",
                       "status": "PASS"|"FAIL", "achieved": float|None, "shortfall": float}],
                     # subject checks in the record's item order
  "real_gap":        float,                  # nested-safe gap used for conditions
  "reasons":         ["..."],                # why list 4 (exclusion / degree / grade / cap / ...)
  "important_notes": ["IMPORTANT: ..."],
  "also_required":   ["APS certificate ...", "English: ...", ...],
}
Tests use the approved field taxonomies (data/taxonomy/) and the engine config of this kit.
"""
import json
from pathlib import Path

from gpur import engine

KIT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEST_TAXONOMY = FIXTURES / "test_taxonomy_all.json"   # kept for reference; the engine uses the approved field files
CONFIG = KIT / "engine_config.json"

_CACHE = {}


def evaluate(field: str, program_id: str, student: dict, records_override: list | None = None) -> dict:
    """field: cs | eee | mechanical | civil. program_id: a record id or a route-group base id.
    records_override: records to use instead of the frozen file (synthetic tests)."""
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    if records_override is not None:
        fd = engine.load_field(field, config=config, records_override=records_override)
    else:
        if field not in _CACHE:
            _CACHE[field] = engine.load_field(field, config=config)
        fd = _CACHE[field]
    return engine.evaluate_program(program_id, student, fd)
