"""RAG lab: chunking and question generation (no API calls, no vector store)."""
from rag_lab.chunking import all_chunks, load_records, record_chunks
from rag_lab.eval_retrieval import NEGATIVES, make_questions


def test_every_record_has_core_chunks():
    records = load_records()
    assert len(records) == 228
    for rec in records:
        sections = {c["section"] for c in record_chunks(rec)}
        assert {"overview", "grade", "conditional_admission", "english", "accepted_degrees"} <= sections, rec["id"]


def test_chunk_ids_unique_and_headed():
    chunks = all_chunks()
    assert len({c["id"] for c in chunks}) == len(chunks)
    for c in chunks:
        assert c["text"].startswith(f"Programme: {c['program']} | University: {c['university']}")


def test_one_chunk_per_subject_requirement():
    rec = next(r for r in load_records() if (r.get("subject_credit_requirements") or {}).get("items"))
    n_items = len(rec["subject_credit_requirements"]["items"])
    assert sum(1 for c in record_chunks(rec) if c["section"] == "subject_requirement") == n_items


def test_questions_have_known_targets():
    qs = make_questions(60)
    assert len(qs) == 60
    ids = {str(r["id"]) for r in load_records()}
    assert all(q["record_id"] in ids for q in qs)
    assert len({q["section"] for q in qs}) >= 5
    assert make_questions(60) == qs          # deterministic: same seed, same questions
    assert len(NEGATIVES) >= 10


def _fake_embed(texts, client=None, batch=100):
    """Deterministic bag-of-words vectors: enough to test the wiring without an API key."""
    import hashlib
    import math
    out = []
    for t in texts:
        v = [0.0] * 256
        for w in t.lower().replace("|", " ").split():
            v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / n for x in v])
    return out


def test_index_and_search_wiring(monkeypatch):
    import pytest
    pytest.importorskip("qdrant_client")
    import rag_lab.store as store
    monkeypatch.setenv("QDRANT_URL", ":memory:")
    monkeypatch.setattr(store, "_MEMORY", None)
    monkeypatch.setattr(store, "embed", _fake_embed)
    rec = load_records()[0]
    chunks = record_chunks(rec) + record_chunks(load_records()[1])
    assert store.build_index(chunks) == len(chunks)
    assert store.build_index(chunks) == len(chunks)           # rebuilding replaces, no duplicates
    assert store.qdrant().count(store.COLLECTION).count == len(chunks)
    hits = store.search(f"IELTS English test {rec['program']} {rec['university']}", top_k=3)
    assert hits and hits[0]["record_id"] == str(rec["id"])
    assert all(0.0 <= h["score"] <= 1.0001 for h in hits)


def test_answer_says_not_found_below_threshold(monkeypatch):
    import rag_lab.answer as answer
    monkeypatch.setattr(answer, "search", lambda q, top_k=5: [{"score": 0.1, "program": "X", "university": "Y",
                                                               "section": "grade", "source_url": "", "text": "t"}])
    out = answer.ask("Who won the World Cup?")
    assert out["answer"] == answer.NOT_FOUND and out["sources"] == []


def test_experiment_reference_and_scoring(monkeypatch):
    """The engine reference covers all four lists; scoring counts looser/stricter correctly (fake LLM, no API)."""
    import rag_lab.experiment as ex
    rows = [r for s in ex.students() for r in ex.engine_decisions(s)]
    assert {r["engine_list"] for r in rows} == {1, 2, 3, 4}
    picked = ex.sample_rows(rows, 40)
    assert len(picked) == 40 and len({r["engine_list"] for r in picked}) == 4
    for r in picked:                       # fake decider: always says "eligible, no selection"
        r["oracle"] = 1
    s = ex.score(picked, "oracle")
    assert s["decisions"] == 40
    assert s["looser_in_students_favour"] == sum(1 for r in picked if r["engine_list"] > 1)
    assert s["stricter"] == 0


def test_experiment_prompt_matches_engine_scope():
    """Fairness review 11.11.2026: the LLM must judge the same criteria as the engine, no more."""
    import rag_lab.experiment as ex
    assert ex.PROMPT_VERSION == 6
    for must in ("Do NOT judge language certificates", "NOT a reason for list 4", "counts as", "GATE", "HARD_MAX_GRADE", "best one"):
        assert must in ex.SYSTEM
    cs = next(s for s in ex.students() if s["name"] == "test_cs")
    assert "information_technology (counts as: computer_science)" in ex.profile_text(cs)


def test_review_lists_only_disagreements(tmp_path, monkeypatch):
    import rag_lab.experiment as ex
    monkeypatch.setattr(ex, "RESULTS", tmp_path)
    rows = [{"student": "s", "program": "P", "university": "U", "engine_list": 2, "oracle": 2, "oracle_reason": "same"},
            {"student": "s", "program": "Q", "university": "U", "engine_list": 1, "oracle": 4, "oracle_reason": "grade too low"}]
    text = ex.write_review(rows, ["oracle"]).read_text(encoding="utf-8")
    assert "grade too low" in text and "| P (U)" not in text


def test_engine_notes_reach_the_llm():
    """v3: a programme with an engine exclusion carries that note into the LLM context."""
    import rag_lab.experiment as ex
    notes = ex.engine_notes(["4352"])
    assert any("exclusions (4352)" in n and "not equivalent" in n for n in notes)
    assert ex.uses_config(["4352"]) is True
    assert "ENGINE NOTES" in ex.with_notes("regulation text", ["4352"])


def test_multi_route_context_names_each_route():
    import rag_lab.experiment as ex
    from rag_lab.chunking import load_records
    by_id = {str(r["id"]): r for r in load_records()}
    ctx = ex.oracle_context(["3903_DIRECT", "3903_CONDITIONAL"], by_id)
    assert "=== Admission route 3903_DIRECT ===" in ctx and "=== Admission route 3903_CONDITIONAL ===" in ctx


def test_notes_list_expanded_subject_areas_and_profile_uses_engine_categories():
    import rag_lab.experiment as ex
    from rag_lab.chunking import load_records
    rec = next(r for r in load_records() if (r.get("subject_credit_requirements") or {}).get("items"))
    notes = ex.engine_notes([str(rec["id"])])
    assert any(n.startswith(f"requirement item 0 ({rec['id']}) counts courses in:") for n in notes)
    mech = next(s for s in ex.students() if s["name"] == "test_mechanical")
    assert "Country of the bachelor degree: India" in ex.profile_text(mech)


def test_failed_llm_call_is_no_answer_not_a_crash(monkeypatch):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
    import llm_utils
    import rag_lab.experiment as ex

    def boom(*a, **k):
        raise llm_utils.LLMResponseError("empty answer")
    monkeypatch.setattr(llm_utils, "call_llm_json", boom)
    out = ex.llm_decide(None, "m", "profile", "context")
    assert out["list"] is None and out["reason"].startswith("ERROR")
    monkeypatch.setattr(llm_utils, "call_llm_json", lambda *a, **k: {"list": "7", "reason": "x"})
    assert ex.llm_decide(None, "m", "p", "c")["list"] is None          # out-of-range list = no answer
