"""31.10.2026: re-test only what changed + LLM usage logging (no LLM call in these tests)."""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import llm_utils                                                    # noqa: E402
from eval_selection import resolve_key, select_courses             # noqa: E402

COURSES = [{"id": "1", "title": "ENGINEERING WORKSHOP"}, {"id": "2", "title": "IoT Architectures and Protocols"},
           {"id": "3", "title": "Wireless Sensor Networks"}, {"id": "4", "title": "Thermodynamics"}]


def test_bare_key_name_found_in_gold():
    assert resolve_key("answer_key_cs.json").replace("\\", "/").endswith("tests/gold/answer_key_cs.json")


def test_only_keeps_matching_titles():
    assert [c["id"] for c in select_courses(COURSES, "workshop")] == ["1"]
    assert [c["id"] for c in select_courses(COURSES, "iot, sensor network")] == ["2", "3"]


def test_retest_keeps_given_ids():
    assert [c["id"] for c in select_courses(COURSES, None, {"3", "4"})] == ["3", "4"]


def test_usage_is_recorded_and_priced(monkeypatch):
    llm_utils.reset_usage()
    resp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=20000, completion_tokens=1000,
                                                 prompt_tokens_details=SimpleNamespace(cached_tokens=18000)))
    llm_utils._record_usage(resp, "m", "test", 1.5)
    for k, v in {"GPUR_PRICE_INPUT": "1", "GPUR_PRICE_CACHED": "0.1", "GPUR_PRICE_OUTPUT": "10"}.items():
        monkeypatch.setenv(k, v)
    s = llm_utils.usage_summary()
    assert (s["calls"], s["input_tokens"], s["cached_tokens"], s["output_tokens"]) == (1, 20000, 18000, 1000)
    assert s["euros"] == round((2000 * 1 + 18000 * 0.1 + 1000 * 10) / 1_000_000, 4)
    llm_utils.reset_usage()
