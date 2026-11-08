"""04.11.2026 (Day 7): the web API, with a fake AI (free, no key needed).

Checks every step, the access key, input checks, privacy (uploads are deleted after reading), and that the
API gives exactly the same profile and eligibility results as the terminal scripts for the same student."""
import builtins
import contextlib
import io
import json
import runpy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "pipeline"), str(REPO)]
fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient            # noqa: E402

import service                                       # noqa: E402
import synthetic_transcripts as ST                   # noqa: E402
from transcript_parser import ExtractedCourse, TranscriptExtractionResult   # noqa: E402

SAMPLE = "S07_makaut_heritage_mech_lateral"          # lateral entry, mechanical, has unsure courses
FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64       # passes the file check; the fake AI does not read it
KEY = "test-access-key"


def truth():
    spec = json.loads((ST.SPECS / f"{SAMPLE}.json").read_text(encoding="utf-8"))
    t = ST.truth_for(spec, ST.assign_grades(spec))
    t["gold"] = json.loads((ST.LABELS / f"{SAMPLE}.json").read_text(encoding="utf-8"))["labels"]
    return spec, t


@pytest.fixture
def fake_ai(monkeypatch):
    spec, t = truth()
    ex = t["extraction"]

    def fake_extract(prepared, *a, **k):
        cs = [ExtractedCourse(course_id=c["code"] or f"X-{i}", title=c["title"], credits=c["credits"],
                              grade_letter=c["grade"], semester=c["semester"]) for i, c in enumerate(ex["courses"])]
        return TranscriptExtractionResult(
            student_name="SAMPLE STUDENT", institution=ex["institution"], program=ex["programme"], regulation="R",
            entry_type=ex["entry_type"], courses=cs, stated_total_credits=ex["credits_registered"],
            stated_cgpa=ex["cgpa"], min_credits_for_award=ex["credits_for_award_printed"],
            years_with_courses=int(ex["years_studied"]))

    def fake_classify(courses, taxonomy, knowledge_base=None, **k):
        full = {c["title"]: c["full_title"] for c in ex["courses"]}
        out = []
        for c in courses:
            g = t["gold"].get(full.get(c.title, c.title))
            out.append({"course_id": c.course_id, "categories": g or [],
                        "confidence": "HIGH" if g is not None else "MEDIUM", "reasoning": "fake"})
        return out

    monkeypatch.setattr(service, "extract_transcript_openai", fake_extract)
    monkeypatch.setattr(service, "classify_courses_openai", fake_classify)
    return spec, t


@pytest.fixture
def client(tmp_path, monkeypatch, fake_ai):
    monkeypatch.setenv("GPUR_ACCESS_KEY", KEY)
    monkeypatch.setenv("GPUR_DATA_DIR", str(tmp_path / "api_data"))
    from api.main import app
    return TestClient(app)


H = {"X-Access-Key": KEY}


def run_api(client, spec):
    r = client.post("/sessions", files={"file": ("memo.png", FAKE_PNG, "image/png")},
                    data={"n_max": spec["grading"][0][1], "n_min": spec["pass_min"]}, headers=H)
    assert r.status_code == 202, r.text
    sid = r.json()["session_id"]
    s = client.get(f"/sessions/{sid}", headers=H).json()
    assert s["status"] == "awaiting_confirmation", s
    assert s["check_screen"]["values"]["entry_type"] == "lateral_entry" and s["check_screen"]["missing"] == []
    r = client.post(f"/sessions/{sid}/confirm", json={"field": spec["field"]}, headers=H)
    assert r.status_code == 202, r.text
    s = client.get(f"/sessions/{sid}", headers=H).json()
    assert s["status"] == "awaiting_syllabus" and s["classification"]["needs_syllabus"], s
    r = client.post(f"/sessions/{sid}/syllabus", data={"skip": "true"}, headers=H)
    assert r.status_code == 202, r.text
    s = client.get(f"/sessions/{sid}", headers=H).json()
    assert s["status"] == "awaiting_eligibility", s
    r = client.post(f"/sessions/{sid}/eligibility", json={"degree_field_id": spec["degree_field_id"]}, headers=H)
    assert r.status_code == 200, r.text
    return sid, r.json()


def test_health_needs_no_key(client):
    assert client.get("/health").json()["status"] == "ok"


def test_key_is_required(client):
    assert client.get("/sessions/run_abc", headers={"X-Access-Key": "wrong"}).status_code == 401
    assert client.post("/sessions", files={"file": ("m.png", FAKE_PNG)}, data={"n_max": 10, "n_min": 4}).status_code == 401


def test_full_flow_and_privacy(client, fake_ai, tmp_path):
    spec, _ = fake_ai
    sid, out = run_api(client, spec)
    folder = tmp_path / "api_data" / sid
    assert not (folder / "upload.bin").exists() and not (folder / "syllabus.bin").exists()   # files not kept
    assert sum(out["results"]["counts"].values()) > 0
    assert "#" in client.get(f"/sessions/{sid}/report", headers=H).text
    assert client.delete(f"/sessions/{sid}", headers=H).json()["deleted"] and not folder.exists()


def test_input_checks(client, fake_ai):
    spec, _ = fake_ai
    bad = client.post("/sessions", files={"file": ("m.txt", b"hello", "text/plain")}, data={"n_max": 10, "n_min": 4}, headers=H)
    assert bad.status_code == 415
    assert client.post("/sessions", files={"file": ("m.png", FAKE_PNG)}, data={"n_max": 4, "n_min": 10}, headers=H).status_code == 422
    sid = client.post("/sessions", files={"file": ("m.png", FAKE_PNG)}, data={"n_max": 10, "n_min": 4}, headers=H).json()["session_id"]
    assert client.post(f"/sessions/{sid}/confirm", json={"field": "biology"}, headers=H).status_code == 422
    assert client.post(f"/sessions/{sid}/confirm", json={"field": "cs", "values": {"stated_cgpa": -1}}, headers=H).status_code == 422
    assert client.post(f"/sessions/{sid}/syllabus", data={"skip": "true"}, headers=H).status_code == 409   # wrong order
    assert client.get("/sessions/run_doesnotexist", headers=H).status_code == 404


def test_api_matches_terminal_scripts(client, fake_ai, tmp_path, monkeypatch):
    """Same student, same fake AI: the API and the terminal scripts must give identical profile and results."""
    spec, t = fake_ai
    sid, _ = run_api(client, spec)
    api_profile = json.loads((tmp_path / "api_data" / sid / "profile.json").read_text(encoding="utf-8"))
    api_results = json.loads((tmp_path / "api_data" / sid / "session.json").read_text(encoding="utf-8"))["results"]

    import run_batch
    cli_dir = tmp_path / "cli"
    cli_dir.mkdir()
    monkeypatch.chdir(cli_dir)
    memo = cli_dir / "memo.png"
    memo.write_bytes(FAKE_PNG)
    tee = run_batch.Tee(sys.stdout)
    st = run_batch.Student(spec, t, memo, tee)
    run_batch.run_script("run_stage_1_to_3.py", [], st, tee)
    st.session = next(p.stem.replace("checkpoint_", "") for p in cli_dir.glob("checkpoint_*.json"))
    run_batch.run_script("run_stage_4_to_5.py", [], st, tee)
    run_batch.run_script("run_eligibility.py", [f"final_matching_profile_{st.session}.json"], st, tee)
    cli_profile = json.loads((cli_dir / f"final_matching_profile_{st.session}.json").read_text(encoding="utf-8"))
    cli_results = json.loads((cli_dir / f"eligibility_{st.session}.json").read_text(encoding="utf-8"))["results"]

    api_profile.pop("degree_field_id", None)
    cli_profile.pop("degree_field_id", None)
    api_profile["name"] = cli_profile["name"]          # the terminal check screen keeps the name as read
    assert api_profile == cli_profile
    api_lists = {r["program_id"]: r["list"] for n in api_results["lists"].values() for r in n}
    assert api_lists == {r["program_id"]: r["list"] for r in cli_results}


def test_knowledge_base_seed_is_clean_and_used(client, tmp_path):
    """05.11.2026: the server starts from the reviewed seed; the seed holds no personal data and loads cleanly."""
    from knowledge_base import KnowledgeBase
    seed = REPO / "data" / "knowledge" / "kb_seed.json"
    raw = json.loads(seed.read_text(encoding="utf-8"))
    assert len(raw) == 606
    allowed = {"signature", "title", "categories", "confidence", "reasoning", "evidence_quote", "source",
               "verified_count", "field"}
    assert all(set(e) <= allowed and e["confidence"] == "HIGH" for e in raw.values())
    from api.main import kb_path
    p = kb_path()
    assert p.exists() and len(KnowledgeBase(str(p))._entries) == 606


def test_website_is_served_without_key_and_without_outside_requests(client):
    """05.11.2026 (Day 8): GET / gives the student website; fonts come from this server, never a font service."""
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = r.text
    assert "Check my eligibility" in html and "X-Access-Key" in html
    assert "googleapis" not in html and "https://" not in html.split("<script>")[1]   # no outside calls in the code
    assert client.get("/fonts/schibsted-grotesk-latin-700-normal.woff2").status_code == 200


def test_degree_examples_come_from_the_degree_file():
    from api.main import degree_examples
    ex = degree_examples()
    raw = json.loads((REPO / "data" / "taxonomy" / "degree_fields.json").read_text(encoding="utf-8"))["degree_fields"]
    assert set(ex) == set(raw) and ex["information_technology"].startswith("B.Tech Information Technology")


def test_demo_result_needs_no_key_and_creates_nothing(client, tmp_path):
    """05.11.2026: GET /demo shows the stored S18 sample result without a key; it starts no session and no AI."""
    data = tmp_path / "api_data"
    before = set(data.glob("run_*")) if data.exists() else set()
    r = client.get("/demo")
    assert r.status_code == 200
    d = r.json()
    assert d["demo"] is True and d["status"] == "done" and "fictional" in d["student"]["name"]
    counts = d["results"]["counts"]
    assert sum(counts.values()) == 103 == sum(len(v) for v in d["results"]["lists"].values())
    assert all(counts[k] == len(d["results"]["lists"][k]) for k in counts)
    assert (set(data.glob("run_*")) if data.exists() else set()) == before
    assert client.get("/sessions/run_abc").status_code == 401      # everything else still needs the key


def test_every_run_is_counted_anonymously(client, fake_ai, tmp_path):
    """07.11.2026: one ledger row per finished run, only anonymous fields; a changed degree is not a new run;
    /stats needs no key."""
    import run_ledger
    spec, _ = fake_ai
    sid, out = run_api(client, spec)
    client.post(f"/sessions/{sid}/eligibility", json={"degree_field_id": spec["degree_field_id"]}, headers=H)  # same session again
    rows = run_ledger.rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["source"] == "website" and row["status"] == "done" and row["field"] == spec["field"]
    assert row["list_counts"] == out["results"]["counts"] and row["n_courses"] > 0
    assert set(row) <= run_ledger.ALLOWED
    text = json.dumps(row)
    assert "SAMPLE STUDENT" not in text and spec["institution"] not in text      # nothing personal
    st = client.get("/stats").json()
    assert st["runs"] == 1 and st["finished"] == 1 and st["by_source"] == {"website": 1}


def test_failed_run_is_counted_and_ledger_never_breaks_a_run(client, monkeypatch):
    import run_ledger

    def broken(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(service, "extract_transcript_openai", broken)
    sid = client.post("/sessions", files={"file": ("m.png", FAKE_PNG)}, data={"n_max": 10, "n_min": 4}, headers=H).json()["session_id"]
    assert client.get(f"/sessions/{sid}", headers=H).json()["status"] == "failed"
    rows = run_ledger.rows()
    assert len(rows) == 1 and rows[0]["status"] == "failed" and rows[0]["failed_step"] == "reading"
    monkeypatch.setenv("GPUR_LEDGER_FILE", "/nonexistent-dir/x/ledger.jsonl")   # storage broken
    assert run_ledger.record({"source": "website", "status": "done"}) is None   # reported, not raised
    with pytest.raises(ValueError):
        run_ledger._clean({"source": "elsewhere"})
