"""Knowledge base with the approved course map (30.10.2026). Uses a temporary file, never the real one."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from knowledge_base import KnowledgeBase   # noqa: E402

CS = "computer_science_informatics."


def kb(tmp_path, **kw):
    return KnowledgeBase(path=str(tmp_path / "kb.json"), **kw)


def test_approved_title_answered_from_map(tmp_path):
    hit = kb(tmp_path).lookup("ADVANCED OPERATING SYSTEMS", field="cs")
    assert hit is not None and hit.source == "approved_course_map" and hit.confidence == "HIGH"
    assert set(hit.categories) == {CS + "operating_systems", CS + "computer_engineering"}


def test_branch_filter(tmp_path):
    k = kb(tmp_path)
    assert k.lookup("Digital Image Processing", field="eee") is not None      # ECE title, EEE field covers ECE
    assert k.lookup("Digital Image Processing", field="civil") is None        # not a civil title


def test_categories_outside_field_file_are_dropped(tmp_path):
    hit = kb(tmp_path).lookup("Mechanics of Solids", field="mechanical")
    assert hit is not None and "civil_engineering.structural_mechanics" not in hit.categories


def test_generic_maths_never_from_map(tmp_path):
    assert kb(tmp_path).lookup("Mathematics - I", field="cs") is None


def test_learned_result_never_overrides_map(tmp_path):
    k = kb(tmp_path)
    k.record("Advanced Operating Systems", [CS + "operating_systems"], "HIGH", "llm", "title_only", field="cs")
    assert set(k.lookup("Advanced Operating Systems", field="cs").categories) == {CS + "operating_systems", CS + "computer_engineering"}


def test_unknown_title_uses_learned_entry_then_llm(tmp_path):
    k = kb(tmp_path)
    assert k.lookup("Quantum Machine Learning Foundations", field="cs") is None
    k.record("Quantum Machine Learning Foundations", [CS + "machine_learning_ai"], "HIGH", "llm", "title_only", field="cs")
    assert k.lookup("Quantum Machine Learning Foundations", field="cs").categories == [CS + "machine_learning_ai"]


def test_map_can_be_switched_off_for_evaluation(tmp_path):
    assert kb(tmp_path, use_approved_map=False).lookup("Advanced Operating Systems", field="cs") is None


def test_ampersand_and_and_are_the_same_title():
    """04.11.2026 batch 1 (S12): 'Structural Dynamics and Earthquake Engineering' must find the '&' map entry."""
    from knowledge_base import normalize_course_signature as sig, load_approved_map
    assert sig("Structural Dynamics & Earthquake Engineering", "civil") == sig("Structural Dynamics and Earthquake Engineering", "civil")
    assert sig("A&B", "cs") == sig("A and B", "cs") == sig("A / B", "cs") == "cs::A B"
    assert sig("CAD/CAM", "mechanical") == sig("CAD & CAM", "mechanical") == sig("CAD / CAM", "mechanical")
    e = load_approved_map("civil").get(sig("Structural Dynamics and Earthquake Engineering", "civil"))
    assert e is not None and e.categories == ["civil_engineering.structural_engineering"]


def test_sync_from_seed_replaces_only_named_titles(tmp_path):
    """05.11.2026: a reviewed seed answer replaces the old local one; other entries and the seed stay unchanged."""
    import json
    from sync_kb_from_seed import sync
    local = tmp_path / "verified_knowledge_base.json"
    old = {"eee::PULSE DIGITAL CIRCUITS": {"signature": "eee::PULSE DIGITAL CIRCUITS", "title": "Pulse & Digital Circuits",
           "categories": ["electrical_electronic_engineering.electronics", "electrical_electronic_engineering.digital_systems"],
           "confidence": "HIGH", "reasoning": "old", "evidence_quote": None, "source": "title_only", "verified_count": 1, "field": "eee"},
           "cs::OTHER": {"signature": "cs::OTHER", "title": "Other", "categories": [], "confidence": "HIGH", "reasoning": "x",
           "evidence_quote": None, "source": "title_only", "verified_count": 1, "field": "cs"}}
    local.write_text(json.dumps(old), encoding="utf-8")
    lines = sync("eee", ["Pulse & Digital Circuits", "No Such Course"], kb_path=local)
    raw = json.loads(local.read_text(encoding="utf-8"))
    assert raw["eee::PULSE DIGITAL CIRCUITS"]["categories"] == ["electrical_electronic_engineering.electronics"]
    assert raw["cs::OTHER"] == old["cs::OTHER"] and "not in seed" in lines[1]
    assert len(list(tmp_path.glob("verified_knowledge_base_backup_*.json"))) == 1
    k = KnowledgeBase(path=str(local), use_approved_map=False)
    assert k.lookup("Pulse & Digital Circuits", field="eee").categories == ["electrical_electronic_engineering.electronics"]
