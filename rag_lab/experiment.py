"""
RAG lab, step 5: rules vs RAG on eligibility decisions.

Same students, same programmes, two deciders:
  RULES  the GPU-R engine (deterministic, tested) -> taken as the reference here
  LLM    gets the student profile + regulation text and must choose one of the four lists
Two LLM variants:
  oracle  ALL chunks of the right programme (perfect retrieval): measures the model's reasoning alone
  rag     only what retrieval finds for "admission requirements of <programme> at <university>": the realistic setup
Measured: agreement with the engine, decisions wrongly in the student's favour (looser),
stricter decisions, consistency over repeated runs, tokens, time.

Students: the four synthetic engine test students (engine_kit/tests/fixtures + a CS student built from the
hand-labelled CS answer key). Reference = the engine's verdict on the same structured data, so a difference
means the LLM read or applied the regulation differently, not that the input differed.

Run (asks before spending money):
  py -m rag_lab.experiment --sample 120 --repeat 20
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))

from rag_lab.chunking import load_records, record_chunks  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
LISTS = {1: "eligible, no selection step", 2: "eligible, with a selection step",
         3: "bridging possible (missing subjects closable as conditions within the regulation's cap)", 4: "not eligible"}

PROMPT_VERSION = 6   # 11.11.2026: v2 = same scope and policies as the engine; v3 = plus the engine's per-programme notes; v4 = item numbers, restricted admission, subfield; v5 = grade-rule type, accepted-fields list, routes, rule texts of engine notes; v6 = expanded subject areas per item, implied categories, course-sharing and gap rules, country
SYSTEM = """You decide the admission eligibility of an applicant for ONE German master's programme,
using ONLY the regulation text given. Choose exactly one list:
1 = eligible, all requirements met, no selection step after the requirements
2 = eligible, all requirements met, but a selection step follows (aptitude test, interview, ranking, numerus clausus)
3 = bridging possible: degree and grade are fine, but subject credits are missing and the regulation allows
    making them up as conditions (Auflagen), within its maximum
4 = not eligible

Judge ONLY these criteria (the same ones the rule engine checks):
a) degree field: is the applicant's bachelor field in the "Accepted bachelor fields" list? That list decides; use the
   "counts as" relation given for the applicant. Exclusions in the engine notes also make an applicant not eligible.
b) grade limit: apply it only when the grade rule is HARD_MAX_GRADE; NO_GRADE_THRESHOLD means no grade limit
c) subject credit minimums. The engine notes list, for every requirement item, exactly which subject areas count for it.
   Inside one requirement, count each course once. A course may count for TWO requirements only if one requirement's
   subject areas lie inside the other's, or the course's area is named in both; otherwise give it to one requirement
   (the one where it closes more of the gap).
d) if subject credits are missing: are conditions allowed, and is the gap within the stated maximum? For nested
   requirements, do not count the same missing credits twice.
e) is there a selection step after the requirements? Restricted admission or a numerus clausus also count as a selection step.
Do NOT judge language certificates, documents, deadlines, APS, standardized tests or practical experience:
assume the applicant will provide them.
A bachelor's total ECTS below the programme's minimum is NOT a reason for list 4: programmes admit shorter
degrees and require the missing credits later. Treat it as a note only.
If several admission routes are given, judge each and use the best one the applicant can take. Routes that need
extra evidence not shown in the applicant profile (e.g. a GATE score) do not apply.
German grades: 1.0 is best, 4.0 is the pass mark; a limit of 2.5 means 2.5 or better.
Return JSON: {"list": 1|2|3|4, "reason": "one sentence"}"""


def students() -> list[dict]:
    fx = REPO / "engine_kit" / "tests" / "fixtures"
    out = [json.loads((fx / f"student_{f}.json").read_text(encoding="utf-8")) for f in ("mechanical", "eee", "civil")]
    key = json.loads((REPO / "tests" / "gold" / "answer_key_cs.json").read_text(encoding="utf-8"))
    courses = [{"id": c["id"], "title": c["title"], "ects": round(float(c["credits"]) * 1.5, 2), "categories": c["expected"]}
               for c in key["courses"] if c["id"].startswith("GNIT-") and c.get("expected")]
    out.append({"name": "test_cs", "field": "cs", "degree_field": "information_technology", "degree_subfield": None,
                "german_grade": 2.5, "total_ects": 180.0, "lateral_entry": True, "ects_factor": 1.5,
                "country": "India", "courses": courses, "excluded_courses": [], "confirmations": {},
                "_note": "SYNTHETIC test student built from the hand-labelled CS answer key (credits x 1.5)"})
    return out


def engine_decisions(student: dict) -> list[dict]:
    from gpur import engine
    fd = engine.load_field(student["field"])
    groups = fd.config.get("route_groups", {}).get(student["field"], {})
    rows = []
    for r in engine.evaluate_field(student, fd):
        rows.append({"student": student["name"], "field": student["field"], "program_id": r["program_id"],
                     "record_ids": groups.get(r["program_id"], [r["program_id"]]),
                     "program": r["program"], "university": r["university"], "engine_list": r["list"]})
    return rows


def _degree_fields() -> dict:
    data = json.loads((REPO / "data" / "taxonomy" / "degree_fields.json").read_text(encoding="utf-8"))
    return data.get("degree_fields", data)


def profile_text(s: dict) -> str:
    """Courses with the categories the ENGINE uses (taxonomy implications applied), so both see the same input."""
    from gpur import engine
    fd = engine.load_field(s["field"])
    courses = [{"title": c["title"], "ects": c["ects"], "categories": sorted(c["cats"])} for c in engine.student_courses(s, fd)]
    totals: dict[str, float] = defaultdict(float)
    for c in courses:
        for cat in c["categories"]:
            totals[cat] += float(c["ects"])
    deg = _degree_fields().get(s["degree_field"], {})
    counts = deg.get("counts_as") or []
    deg_line = f"Degree field: {s['degree_field']}" + (f" (counts as: {', '.join(counts)})" if counts else "")
    lines = [deg_line, f"Degree subfield: {s.get('degree_subfield') or 'not specified'}", f"Country of the bachelor degree: {s.get('country', 'India')}", f"German grade: {s['german_grade']}",
             f"Total ECTS of the bachelor degree: {s['total_ects']}", "Courses (title | ECTS | subject areas):"]
    lines += [f"- {c['title']} | {c['ects']} | {', '.join(c['categories'])}" for c in courses]
    lines.append("ECTS per subject area (a course can count in several areas):")
    lines += [f"- {k}: {round(v, 2)}" for k, v in sorted(totals.items())]
    return "\n".join(lines)


_CONFIG_SECTIONS = ("exclusions", "gated_routes", "area_caps", "max_unmet_presence_items", "separate_subjects",
                    "committee_check", "add_subjects")


def engine_notes(record_ids: list[str]) -> list[str]:
    """Decisions recorded in engine_config.json for these records (from reading the regulations).
    Given to the LLM too, so both deciders know the same things (fairness review v3)."""
    cfg = json.loads((REPO / "engine_kit" / "engine_config.json").read_text(encoding="utf-8"))
    notes = []
    for sec in _CONFIG_SECTIONS:
        for rid in record_ids:
            entry = (cfg.get(sec) or {}).get(rid)
            if entry is not None:
                rule = (cfg.get(sec) or {}).get("_rule", "")
                notes.append(f"{sec.replace('_', ' ')} ({rid}): rule: {rule} | this programme: {json.dumps(entry, ensure_ascii=False)}")
    try:
        from gpur import engine
        by_id = {str(r["id"]): r for r in load_records()}
        for rid in record_ids:
            rec = by_id.get(rid)
            if not rec:
                continue
            fd = engine.load_field({"computer_science": "cs", "electrical_electronic_engineering": "eee",
                                    "mechanical_engineering": "mechanical", "civil_engineering": "civil"}[rec["_domain"]])
            for i, it in enumerate((rec.get("subject_credit_requirements") or {}).get("items") or []):
                notes.append(f"requirement item {i} ({rid}) counts courses in: {', '.join(sorted(engine.target_set(it, fd, rid, i)))}")
    except Exception as e:                       # noqa: BLE001 -- notes are a help, never a crash
        notes.append(f"(subject area list unavailable: {e})")
    general = [f"presence gap with conditions: {json.dumps(cfg.get('presence_gap_with_conditions'), ensure_ascii=False)}"]
    return notes + general


def with_notes(context: str, record_ids: list[str]) -> str:
    return context + "\n\nENGINE NOTES (decisions taken from the regulations; apply them):\n" + "\n".join(engine_notes(record_ids))


def uses_config(record_ids: list[str]) -> bool:
    """True if a programme-specific engine decision exists (not just the subject-area lists or the general rule)."""
    return any(not n.startswith(("presence gap", "requirement item", "(subject area")) for n in engine_notes(record_ids))


def oracle_context(record_ids: list[str], by_id: dict) -> str:
    parts = []
    for rid in record_ids:
        if rid not in by_id:
            continue
        head = f"=== Admission route {rid} ===\n" if len(record_ids) > 1 else ""
        parts.append(head + "\n\n".join(c["text"] for c in record_chunks(by_id[rid])))
    return "\n\n".join(parts)


def rag_context(row: dict, top_k: int = 8) -> str:
    from rag_lab.store import search
    q = f"Admission requirements of {row['program']} at {row['university']}: accepted degrees, grade, subject ECTS, conditional admission, selection"
    return "\n\n".join(h["text"] for h in search(q, top_k=top_k))


def llm_decide(client, model: str, profile: str, context: str) -> dict:
    """One decision. A failed or unusable answer becomes list None ("no answer"), never a crash of the whole run."""
    import llm_utils
    try:
        out = llm_utils.call_llm_json(client, model, [{"role": "system", "content": SYSTEM},
                                                      {"role": "user", "content": f"REGULATION TEXT:\n{context}\n\nAPPLICANT:\n{profile}"}],
                                      max_tokens=1500, what="RAG eligibility decision")
    except Exception as e:                       # noqa: BLE001 -- recorded as "no answer" and listed in the results
        return {"list": None, "reason": f"ERROR: {type(e).__name__}: {e}"[:300]}
    try:
        lst = int(out.get("list"))
    except (TypeError, ValueError):
        lst = None
    return {"list": lst if lst in LISTS else None, "reason": out.get("reason", "")}


def sample_rows(rows: list[dict], n: int, seed: int = 11) -> list[dict]:
    """Stratified by the engine's list, so all four outcomes are tested, not mostly 'not eligible'."""
    rng = random.Random(seed)
    by_list = defaultdict(list)
    for r in rows:
        by_list[r["engine_list"]].append(r)
    for v in by_list.values():
        rng.shuffle(v)
    picked, i = [], 0
    while len(picked) < min(n, len(rows)):
        for lst in sorted(by_list):
            if i < len(by_list[lst]) and len(picked) < n:
                picked.append(by_list[lst][i])
        i += 1
    return picked


def score(results: list[dict], key: str) -> dict:
    done = [r for r in results if r.get(key) is not None]
    if not done:
        return {"decisions": 0}
    agree = sum(1 for r in done if r[key] == r["engine_list"])
    looser = [r for r in done if r[key] < r["engine_list"]]        # a better list than the rules allow
    stricter = [r for r in done if r[key] > r["engine_list"]]
    return {"decisions": len(done), "no_answer": len(results) - len(done),
            "agreement": round(agree / len(done), 3) if done else None,
            "looser_in_students_favour": len(looser), "stricter": len(stricter),
            "looser_from_not_eligible": sum(1 for r in looser if r["engine_list"] == 4),
            "confusion": dict(Counter(f"rules {r['engine_list']} -> llm {r[key]}" for r in done))}


def safe_context(fn, *args) -> str | None:
    """A retrieval failure (e.g. a network timeout while embedding the question) becomes "no answer" for that case,
    never a crash of the whole run (11.11.2026)."""
    for attempt in range(3):
        try:
            return fn(*args)
        except Exception as e:                   # noqa: BLE001
            print(f"  retrieval failed ({type(e).__name__}), attempt {attempt + 1} of 3")
            time.sleep(5 * (attempt + 1))
    return None


def run(sample: int, repeat: int, variants: list[str], model: str, yes: bool, resume: bool = False) -> dict:
    import os
    from openai import OpenAI
    import llm_utils
    rows = [r for s in students() for r in engine_decisions(s)]
    picked = sample_rows(rows, sample)
    calls = len(picked) * len(variants) + min(repeat, len(picked)) * 2 * len(variants)
    print(f"{len(rows)} engine decisions available; testing {len(picked)} x {variants} + {min(repeat, len(picked))} repeated twice")
    print(f"About {calls} model calls with {model}. Rough input size: 4,000 tokens per call.")
    if not yes and input("Run it? (yes/no) ").strip().lower() != "yes":
        return {}
    by_id = {str(r["id"]): r for r in load_records()}
    studs = {s["name"]: s for s in students()}
    client = OpenAI()
    llm_utils.reset_usage() if hasattr(llm_utils, "reset_usage") else llm_utils.USAGE_LOG.clear()
    t0 = time.time()
    contexts = {}
    done_before = {}
    part = RESULTS / "rules_vs_rag_partial.json"
    if resume and part.exists():   # reuse saved answers of an interrupted run (same sample: same seed, same engine)
        for old in json.loads(part.read_text(encoding="utf-8")):
            if all(old.get(v) is not None for v in variants):
                done_before[(old["student"], old["program_id"], old["engine_list"])] = old
        print(f"Resuming: {len(done_before)} cases already answered are reused, not asked again")
    for i, r in enumerate(picked, 1):
        prof = profile_text(studs[r["student"]])
        old = done_before.get((r["student"], r["program_id"], r["engine_list"]))
        for v in variants:
            r["uses_engine_notes"] = uses_config(r["record_ids"])
            if old and i > repeat:          # reused answer; no context needed (not in the repeat subset)
                r[v], r[f"{v}_reason"] = old[v], old.get(f"{v}_reason", "")
                continue
            ctx = oracle_context(r["record_ids"], by_id) if v == "oracle" else safe_context(rag_context, r)
            if ctx is None:
                r[v], r[f"{v}_reason"] = None, "ERROR: retrieval failed 3 times"
                continue
            ctx = with_notes(ctx, r["record_ids"])
            contexts[(r["student"], r["program_id"], v)] = (prof, ctx)
            if old:                         # reused answer; context kept for the consistency repeats
                r[v], r[f"{v}_reason"] = old[v], old.get(f"{v}_reason", "")
                continue
            d = llm_decide(client, model, prof, ctx)
            r[v] = d["list"]
            r[f"{v}_reason"] = d["reason"]
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / "rules_vs_rag_partial.json").write_text(json.dumps(picked[:i], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{i}/{len(picked)}] {r['program'][:40]:40} rules {r['engine_list']} | " +
              " | ".join(f"{v} {r.get(v)}" for v in variants))
    consistency = {}
    for v in variants:
        same = 0
        subset = [r for r in picked[:repeat] if (r["student"], r["program_id"], v) in contexts]
        for r in subset:
            prof, ctx = contexts[(r["student"], r["program_id"], v)]
            again = [llm_decide(client, model, prof, ctx)["list"] for _ in range(2)]
            r[f"{v}_repeats"] = again
            same += all(a == r[v] for a in again)
        consistency[v] = round(same / len(subset), 3) if subset else None
    out = {"prompt_version": PROMPT_VERSION, "model": model, "seconds": round(time.time() - t0, 1), "usage": llm_utils.usage_summary(),
           "students": list(studs), "tested": len(picked),
           "engine_lists_tested": dict(Counter(r["engine_list"] for r in picked)),
           "scores": {v: score(picked, v) for v in variants},
           "scores_programmes_without_engine_notes": {v: score([r for r in picked if not r.get("uses_engine_notes")], v) for v in variants},
           "scores_programmes_with_engine_notes": {v: score([r for r in picked if r.get("uses_engine_notes")], v) for v in variants},
           "consistency_same_answer_3_of_3": consistency, "rows": picked}
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "rules_vs_rag.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    write_review(picked, variants)
    return out


def write_review(rows: list[dict], variants: list[str]) -> Path:
    """Every disagreement with the AI's reason, for MANUAL review: AI error, engine/record error, or ambiguous?"""
    lines = ["# Rules vs RAG: disagreements to review by hand", "",
             "Fill in the last column: AI error / engine-or-record error / ambiguous.", "",
             "| # | Student | Programme | Engine notes | Rules | Variant | LLM | LLM reason | Verdict |", "|---|---|---|---|---|---|---|---|---|"]
    n = 0
    for r in rows:
        for v in variants:
            if r.get(v) is not None and r[v] != r["engine_list"]:
                n += 1
                reason = str(r.get(f"{v}_reason", "")).replace("|", "/").replace("\n", " ")
                lines.append(f"| {n} | {r['student']} | {r['program']} ({r['university']}) | {'yes' if r.get('uses_engine_notes') else 'no'} | {r['engine_list']} | {v} | {r[v]} | {reason} | |")
    path = RESULTS / "rules_vs_rag_review.md"
    RESULTS.mkdir(exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=120)
    ap.add_argument("--repeat", type=int, default=20)
    ap.add_argument("--variants", default="oracle,rag")
    ap.add_argument("--model", default=os.environ.get("RAG_MODEL", "gpt-6-astra"))
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--resume", action="store_true", help="reuse the answers saved by an interrupted run")
    a = ap.parse_args()
    res = run(a.sample, a.repeat, a.variants.split(","), a.model, a.yes, a.resume)
    if res:
        print(json.dumps({k: v for k, v in res.items() if k != "rows"}, indent=2))
