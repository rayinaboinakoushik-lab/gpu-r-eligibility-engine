"""
GPU-R web API (Day 7, 04.11.2026). A thin door in front of pipeline/service.py: every step calls the same
functions as the terminal scripts, so the API never decides differently from what we tested.

Run locally (repo folder):   py -m uvicorn api.main:app --reload        -> docs page: http://127.0.0.1:8000/docs

Environment (never in code or git):
  OPENAI_API_KEY     the provider key (read by the pipeline)
  GPUR_ACCESS_KEY    required: every request except /health must send it as header  X-Access-Key
  GPUR_DATA_DIR      optional: where sessions are kept (default: <repo>/api_data, gitignored)

Website: GET /  (web/index.html, the student pages; Day 8, 05.11.2026); GET /demo = stored sample result, no key;
GET /stats = anonymous run counts (07.11.2026)

Flow (one session = one student):
  POST /sessions                      transcript + Nmax/Nmin -> reading in the background
  GET  /sessions/{id}                 status; when "awaiting_confirmation": the check-screen values + courses
  POST /sessions/{id}/confirm         corrected values, field (cs/eee/mechanical/civil), GATE -> classification
  POST /sessions/{id}/syllabus        excerpt PDF, or skip -> final profile
  POST /sessions/{id}/eligibility     degree field + route answers -> the four lists (no AI)
  GET  /sessions/{id}/report          the report as Markdown
  DELETE /sessions/{id}               removes everything stored for the session

Privacy: the uploaded transcript and syllabus files are deleted right after they are read; only the
extracted course list, values and results are kept, until the session is deleted.
Limits of this skeleton (known, on purpose): sessions are files on the server (a free host may wipe them on
restart), background work runs inside the API process, one AI step runs at a time.
"""
from __future__ import annotations

import hmac
import json
import os
import shutil
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO / "pipeline"), str(REPO)]

try:                                            # local runs read .env (never committed); a server uses its settings
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
except ImportError:
    pass

import service                                  # noqa: E402
from checkpoint import load_checkpoint          # noqa: E402
from confirm_extraction import FIELDS as VALUE_FIELDS   # noqa: E402
from file_intake import DOMAIN_OPTIONS, prepare_uploaded_bytes   # noqa: E402
from knowledge_base import KnowledgeBase        # noqa: E402
import llm_utils                                # noqa: E402
import run_ledger                               # noqa: E402  07.11.2026: every run counts (anonymous)

app = FastAPI(title="GPU-R API", version="0.1.0",
              description="Eligibility of Indian bachelor graduates for German master's programmes. "
                          "Every request except /health needs the header X-Access-Key.")

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
PIPELINE_LOCK = threading.Lock()      # one AI step at a time: the knowledge base and usage log are shared files


def data_dir() -> Path:
    d = Path(os.environ.get("GPUR_DATA_DIR") or REPO / "api_data")
    d.mkdir(parents=True, exist_ok=True)
    return d


KB_SEED = REPO / "data" / "knowledge" / "kb_seed.json"


def kb_path() -> Path:
    """The server's knowledge base. It starts from the reviewed seed in the repo (05.11.2026, Koushik: only
    confirmed entries) and then learns as usual; a free host that wipes files on restart starts from the seed again."""
    p = data_dir() / "verified_knowledge_base.json"
    if not p.exists() and KB_SEED.exists():
        shutil.copyfile(KB_SEED, p)
    return p


# ------------------------------------------------------------------------------------------- access
def require_key(x_access_key: Optional[str] = Header(default=None)) -> None:
    expected = os.environ.get("GPUR_ACCESS_KEY")
    if not expected:
        raise HTTPException(503, "server not configured: set GPUR_ACCESS_KEY")
    if not x_access_key or not hmac.compare_digest(x_access_key, expected):
        raise HTTPException(401, "missing or wrong X-Access-Key")


# ------------------------------------------------------------------------------------------- storage
class Store:
    """Sessions as folders of JSON files. The one place to change when sessions move to a database."""

    @staticmethod
    def folder(sid: str) -> Path:
        if not sid.startswith("run_") or not sid[4:].isalnum():
            raise HTTPException(404, "no such session")
        return data_dir() / sid

    @classmethod
    def load(cls, sid: str) -> dict:
        p = cls.folder(sid) / "session.json"
        if not p.exists():
            raise HTTPException(404, "no such session")
        return json.loads(p.read_text(encoding="utf-8"))

    @classmethod
    def save(cls, s: dict) -> None:
        f = cls.folder(s["session_id"])
        f.mkdir(parents=True, exist_ok=True)
        s["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        tmp = f / "session.json.tmp"
        tmp.write_text(json.dumps(s, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f / "session.json")

    @classmethod
    def delete(cls, sid: str) -> None:
        f = cls.folder(sid)
        if not f.exists():
            raise HTTPException(404, "no such session")
        shutil.rmtree(f)


def _ledger(s: dict, status: str) -> None:
    """07.11.2026: one anonymous row per finished or failed website run (see pipeline/run_ledger.py)."""
    res = s.get("results") or {}
    run_ledger.record({
        "source": "website", "status": status,
        "failed_step": s.get("status") if status == "failed" else None,
        "field": s.get("field"), "degree_field_id": s.get("degree_field_id"),
        "n_courses": len((s.get("extraction") or {}).get("courses") or []) or None,
        "n_not_counted": len(s.get("not_counted") or []),
        "n_syllabus_resolved": len(s.get("syllabus_resolved") or []),
        "list_counts": res.get("counts"),
        **run_ledger.usage_totals(s.get("usage") or []),
    }, default_file=data_dir() / "runs_ledger.jsonl")


def _fail(s: dict, e: Exception) -> None:
    _ledger(s, "failed")
    s["status"] = "failed"
    s["error"] = str(e) if isinstance(e, service.ServiceError) else f"{type(e).__name__}: {e}"
    if not isinstance(e, service.ServiceError):
        traceback.print_exc()
    Store.save(s)


def _usage(s: dict, step: str) -> None:
    s.setdefault("usage", []).append({"step": step, **llm_utils.usage_summary()})


def _require_status(s: dict, *allowed: str) -> None:
    if s["status"] not in allowed:
        raise HTTPException(409, f"session is '{s['status']}', this step needs: {', '.join(allowed)}")


# ------------------------------------------------------------------------------------------- background jobs
def job_read(sid: str, upload: Path) -> None:
    s = Store.load(sid)
    try:
        with PIPELINE_LOCK:
            llm_utils.reset_usage()
            extraction, values = service.read_transcript(upload.read_bytes(), s["n_max"], s["n_min"],
                                                         filename=s["filename"])
            _usage(s, "reading")
        s.update(status="awaiting_confirmation", values=values, extraction=service.extraction_to_dict(extraction))
        Store.save(s)
    except Exception as e:      # noqa: BLE001 -- every failure is shown to the student as a failed session
        _fail(s, e)
    finally:
        upload.unlink(missing_ok=True)          # privacy: the transcript file is not kept


def job_classify(sid: str) -> None:
    s = Store.load(sid)
    try:
        extraction = service.extraction_from_dict(s["extraction"])
        with PIPELINE_LOCK:
            llm_utils.reset_usage()
            cp = service.classify_and_save(sid, extraction, s["values"], s["field"], s["n_max"], s["n_min"],
                                           gate_score=s.get("gate_score"),
                                           checkpoint_path=str(Store.folder(sid) / "checkpoint.json"),
                                           kb=KnowledgeBase(str(kb_path())))
            _usage(s, "classification")
        s.update(status="awaiting_syllabus" if cp.flagged else "building_profile")
        Store.save(s)
        if not cp.flagged:
            job_profile(sid, None)
    except Exception as e:      # noqa: BLE001
        _fail(s, e)


def job_profile(sid: str, excerpt: Optional[Path]) -> None:
    s = Store.load(sid)
    try:
        cp = load_checkpoint(sid, path=str(Store.folder(sid) / "checkpoint.json"))
        ef = prepare_uploaded_bytes(excerpt.read_bytes(), filename="syllabus.pdf") if excerpt else None
        with PIPELINE_LOCK:
            llm_utils.reset_usage()
            out = service.build_profile(cp, excerpt_file=ef, kb=KnowledgeBase(str(kb_path())))
            _usage(s, "syllabus" if ef else "profile")
        (Store.folder(sid) / "profile.json").write_text(json.dumps(out["profile"], indent=2), encoding="utf-8")
        s.update(status="awaiting_eligibility", syllabus_resolved=out["newly_resolved"],
                 not_counted=[{"title": e.get("title", ""), "reason": e.get("reasoning", "")} for e in out["excluded"]])
        Store.save(s)
    except Exception as e:      # noqa: BLE001
        _fail(s, e)
    finally:
        if excerpt:
            excerpt.unlink(missing_ok=True)     # privacy: the syllabus file is not kept


# ------------------------------------------------------------------------------------------- request models
class ConfirmRequest(BaseModel):
    field: str = Field(description="cs, eee, mechanical or civil (the closest field)")
    values: dict = Field(default_factory=dict, description="only the check-screen values you correct, e.g. {\"stated_cgpa\": 7.4}")
    course_corrections: list = Field(default_factory=list, description="[{\"index\": 12, \"title\": \"...\", \"credits\": 3}]")
    gate_score: Optional[float] = Field(default=None, ge=0, le=1000)


class EligibilityRequest(BaseModel):
    degree_field_id: Optional[str] = Field(default=None, description="from GET /sessions/{id} degree.options; empty = our guess")
    confirmations: dict = Field(default_factory=dict, description="answers to pending_confirmations, e.g. {\"water_thesis\": true}")


def degree_examples() -> dict:
    """degree field id -> its first example degree (data/taxonomy/degree_fields.json), e.g. 'B.Tech Information
    Technology (IT)'. Read from the same file the engine uses, so the website never keeps its own copy."""
    raw = json.loads((REPO / "data" / "taxonomy" / "degree_fields.json").read_text(encoding="utf-8"))
    return {k: (v.get("aliases") or [k])[0] for k, v in raw["degree_fields"].items()}


# ------------------------------------------------------------------------------------------- website
WEB_DIR = REPO / "web"


@app.get("/", include_in_schema=False)
def website() -> FileResponse:
    """05.11.2026 (Day 8): the student website, one page that calls the endpoints below (no extra server)."""
    return FileResponse(WEB_DIR / "index.html", media_type="text/html")


DEMO_FILE = REPO / "data" / "demo" / "demo_s18.json"


@app.get("/demo", include_in_schema=False)
def demo() -> FileResponse:
    """05.11.2026: a stored sample result (fictional student S18, real online run) for visitors without an access
    code. Read-only: no AI, no session, nothing is computed or kept."""
    if not DEMO_FILE.exists():
        raise HTTPException(404, "no demo result on this server")
    return FileResponse(DEMO_FILE, media_type="application/json")


if (WEB_DIR / "fonts").is_dir():                # self-hosted fonts: no request to a font service (privacy)
    app.mount("/fonts", StaticFiles(directory=WEB_DIR / "fonts"), name="fonts")


# ------------------------------------------------------------------------------------------- endpoints
@app.get("/stats")
def stats() -> dict:
    """07.11.2026: anonymous run counts (no key needed; holds no personal data)."""
    try:
        return run_ledger.summary(default_file=data_dir() / "runs_ledger.jsonl")
    except Exception as e:      # noqa: BLE001
        raise HTTPException(503, f"run counts unavailable: {type(e).__name__}")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.post("/sessions", status_code=202, dependencies=[Depends(require_key)])
async def create_session(background: BackgroundTasks, file: UploadFile = File(...),
                         n_max: float = Form(..., gt=0), n_min: float = Form(..., ge=0)) -> dict:
    if n_max <= n_min:
        raise HTTPException(422, "n_max must be greater than n_min (the minimum PASSING grade, not zero)")
    data = await file.read()
    if not data:
        raise HTTPException(422, "the file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file larger than 15 MB")
    if not prepare_uploaded_bytes(data, file.filename).readable:
        raise HTTPException(415, "not a readable image or PDF")
    sid = service.new_session_id()
    s = {"session_id": sid, "status": "reading", "n_max": n_max, "n_min": n_min, "filename": file.filename,
         "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    Store.save(s)
    upload = Store.folder(sid) / "upload.bin"
    upload.write_bytes(data)
    background.add_task(job_read, sid, upload)
    return {"session_id": sid, "status": "reading"}


@app.get("/sessions/{sid}", dependencies=[Depends(require_key)])
def get_session(sid: str) -> dict:
    s = Store.load(sid)
    view = {k: s.get(k) for k in ("session_id", "status", "error", "created_at", "updated_at", "field", "usage")}
    if s.get("values") is not None:
        view["check_screen"] = {
            "values": s["values"], "missing": service.missing_values(s["values"]),
            "labels": {k: label for k, label, _ in VALUE_FIELDS},
            "courses": [{"index": i, "title": c["title"], "credits": c["credits"], "grade": c.get("grade_letter")}
                        for i, c in enumerate(s["extraction"]["courses"], 1)],
            "field_options": [{"id": k, "label": label} for k, label in DOMAIN_OPTIONS],
        }
    cpf = Store.folder(sid) / "checkpoint.json"
    if cpf.exists():
        cp = load_checkpoint(sid, path=str(cpf))
        view["classification"] = {"resolved": len(cp.resolved), "needs_syllabus": [
            {"title": f.get("title", ""), "why": f.get("reasoning", "")} for f in cp.flagged]}
        if s["status"] == "awaiting_syllabus":
            view["classification"]["student_prompt"] = cp.student_prompt
    pf = Store.folder(sid) / "profile.json"
    if pf.exists():
        profile = json.loads(pf.read_text(encoding="utf-8"))
        view["profile"] = {"german_grade": profile["german_grade"], "ects": profile["ects_conversion"]["memo_ects"],
                           "not_counted": s.get("not_counted", []), "warnings": profile["warnings"]}
        view["degree"] = service.degree_options(profile)
        view["degree"]["examples"] = degree_examples()          # 05.11.2026: readable choices for the website
        view["pending_confirmations"] = service.pending_confirmations(profile)
    if s.get("results"):
        view["results"] = s["results"]
    return view


@app.post("/sessions/{sid}/confirm", status_code=202, dependencies=[Depends(require_key)])
def confirm(sid: str, req: ConfirmRequest, background: BackgroundTasks) -> dict:
    s = Store.load(sid)
    _require_status(s, "awaiting_confirmation")
    if req.field not in {k for k, _ in DOMAIN_OPTIONS}:
        raise HTTPException(422, f"field must be one of {[k for k, _ in DOMAIN_OPTIONS]}")
    allowed = {k: kind for k, _, kind in VALUE_FIELDS}
    values = dict(s["values"])
    for k, v in req.values.items():
        if k not in allowed:
            raise HTTPException(422, f"unknown value '{k}'; allowed: {sorted(allowed)}")
        if allowed[k] == "entry" and v not in ("regular", "lateral_entry"):
            raise HTTPException(422, "entry_type must be 'regular' or 'lateral_entry'")
        if allowed[k] == "number":
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise HTTPException(422, f"'{k}' must be a number")
            if v <= 0:
                raise HTTPException(422, f"'{k}' must be greater than 0")
            if k == "years_studied" and v.is_integer():
                v = int(v)                      # as the terminal check screen stores it
        values[k] = v
    if service.missing_values(values):
        raise HTTPException(422, "still missing: " + ", ".join(service.missing_values(values)))
    extraction = service.extraction_from_dict(s["extraction"])
    try:
        service.apply_course_corrections(extraction, req.course_corrections)
    except (service.ServiceError, KeyError, ValueError, TypeError) as e:
        raise HTTPException(422, f"course correction: {e}")
    s.update(status="classifying", values=values, field=req.field, gate_score=req.gate_score,
             corrections={"values": req.values, "courses": req.course_corrections},
             extraction=service.extraction_to_dict(extraction))
    Store.save(s)
    background.add_task(job_classify, sid)
    return {"session_id": sid, "status": "classifying"}


@app.post("/sessions/{sid}/syllabus", status_code=202, dependencies=[Depends(require_key)])
async def syllabus(sid: str, background: BackgroundTasks, file: Optional[UploadFile] = File(default=None),
                   skip: bool = Form(default=False)) -> dict:
    s = Store.load(sid)
    _require_status(s, "awaiting_syllabus")
    if (file is None) == (not skip):
        raise HTTPException(422, "send either a syllabus PDF (file) or skip=true")
    excerpt = None
    if file is not None:
        data = await file.read()
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "file larger than 15 MB")
        if not prepare_uploaded_bytes(data, file.filename).readable:
            raise HTTPException(415, "not a readable PDF or image")
        excerpt = Store.folder(sid) / "syllabus.bin"
        excerpt.write_bytes(data)
    s.update(status="building_profile")
    Store.save(s)
    background.add_task(job_profile, sid, excerpt)
    return {"session_id": sid, "status": "building_profile"}


@app.post("/sessions/{sid}/eligibility", dependencies=[Depends(require_key)])
def eligibility(sid: str, req: EligibilityRequest) -> dict:
    s = Store.load(sid)
    _require_status(s, "awaiting_eligibility", "done")
    pf = Store.folder(sid) / "profile.json"
    profile = json.loads(pf.read_text(encoding="utf-8"))
    deg = service.degree_options(profile)
    chosen = req.degree_field_id or deg["guess"]
    if chosen not in deg["options"]:
        raise HTTPException(422, f"degree_field_id must be one of {deg['options']}")
    profile["degree_field_id"] = chosen
    pf.write_text(json.dumps(profile, indent=2), encoding="utf-8")
    try:
        out = service.check_eligibility(profile, confirmations={k: bool(v) for k, v in req.confirmations.items()})
    except service.ServiceError as e:
        raise HTTPException(422, str(e))
    (Store.folder(sid) / "report.md").write_text(out["markdown"], encoding="utf-8")
    lists = {str(n): [r for r in out["results"] if r["list"] == n] for n in (1, 2, 3, 4)}
    first_time = s["status"] == "awaiting_eligibility"
    s.update(status="done", degree_field_id=chosen,
             results={"counts": {k: len(v) for k, v in lists.items()}, "lists": lists, "warnings": out["warnings"]})
    Store.save(s)
    if first_time:                              # a changed degree choice on the same session is not a new run
        _ledger(s, "done")
    return {"session_id": sid, "status": "done", "results": s["results"]}


@app.get("/sessions/{sid}/report", response_class=PlainTextResponse, dependencies=[Depends(require_key)])
def report_md(sid: str) -> str:
    Store.load(sid)
    p = Store.folder(sid) / "report.md"
    if not p.exists():
        raise HTTPException(409, "no report yet: run the eligibility step first")
    return p.read_text(encoding="utf-8")


@app.delete("/sessions/{sid}", dependencies=[Depends(require_key)])
def delete_session(sid: str) -> dict:
    Store.delete(sid)
    return {"session_id": sid, "deleted": True}
