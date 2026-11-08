"""
GPU-R evaluation log and report (31.10.2026). See tests/synthetic/EVAL_PLAN.md.

Every scored run appends ONE record to tests/synthetic/results/eval_log.jsonl: the sample, its version fingerprint,
the reading result, every course (printed title, label, answer, verdict, answer source, known to the course map?),
the verdict comparison and the AI cost. `report` turns all records into tests/synthetic/results/EVAL_REPORT.md:
targets, reading by layout, classification by category and by answer source, courses not counted, wrong answers,
title variation between universities, verdict differences, cost, and before/after by version.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "tests" / "synthetic" / "results"
LOG = RESULTS / "eval_log.jsonl"
REPORT = RESULTS / "EVAL_REPORT.md"
TARGETS = {"T3_courses_found": 0.99, "T4_credit_errors_per_memo": 1, "T5_wrong_share": 0.02, "T6_not_counted_share": 0.08}


# ------------------------------------------------------------------ record parts
def _sha(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:10]
    except OSError:
        return "missing"


def version_info(field: str) -> dict:
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True,
                                text=True, timeout=10).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    tax = REPO / "data" / "taxonomy"
    h = hashlib.sha256()
    for f in sorted(tax.glob("*_taxonomy.json")):          # one fingerprint for all fields' taxonomies
        h.update(f.read_bytes())
    parts = {"taxonomy": h.hexdigest()[:10], "field_taxonomy": _sha(tax / f"{field}_taxonomy.json"),
             "course_map": _sha(tax / "GPU-R_course_map.json"), "engine_config": _sha(REPO / "engine_kit" / "engine_config.json")}
    parts["version"] = "-".join([commit] + [parts[k][:6] for k in ("taxonomy", "course_map", "engine_config")])
    parts["commit"] = commit
    return parts


def answer_sources(checkpoint: dict, norm) -> dict:
    """printed title -> (source, confidence). Source: lab_rule / map / kb / llm, read from the checkpoint."""
    title_of = {c["course_id"]: c["title"] for c in checkpoint.get("all_courses_raw") or []}
    out = {}
    for c in (checkpoint.get("resolved") or []) + (checkpoint.get("flagged") or []):
        r = c.get("reasoning") or ""
        if c.get("lab_rule"):
            src = "lab_rule"
        elif "approved GPU-R course map" in r:
            src = "map"
        elif "REUSED FROM KNOWLEDGE BASE" in r:
            src = "kb"
        else:
            src = "llm"
        out[norm(title_of.get(c["course_id"], c["course_id"]))] = (src, c.get("confidence"))
    return out


def map_knows(titles: list, field: str) -> dict:
    """Is the printed title answered by the approved course map (no AI needed)?"""
    sys.path.insert(0, str(REPO / "pipeline"))
    import os
    import tempfile
    from knowledge_base import KnowledgeBase
    with tempfile.TemporaryDirectory() as tmp:
        kb = KnowledgeBase(path=os.path.join(tmp, "k.json"), use_approved_map=True)
        return {t: kb.lookup(t, field=field) is not None for t in titles}


def read_usage(session: str) -> dict:
    p = Path(f"usage_{session}.json")
    if not p.exists():
        return {"available": False}
    stages = json.loads(p.read_text(encoding="utf-8"))
    tot = {k: sum(s.get(k) or 0 for s in stages) for k in ("calls", "seconds", "input_tokens", "cached_tokens", "output_tokens")}
    eur = [s.get("euros") for s in stages]
    tot["euros"] = round(sum(e for e in eur if e is not None), 4) if any(e is not None for e in eur) else None
    return {"available": True, **tot, "stages": [s["stage"] for s in stages]}


def append(record: dict) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    record = {"logged_at": datetime.now().isoformat(timespec="seconds"), **record}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_log() -> list:
    if not LOG.exists():
        return []
    return [json.loads(line) for line in LOG.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------------ report
def _pct(a, b):
    return f"{100 * a / b:.1f} %" if b else "-"


def summarise(records: list) -> dict:
    scored = [c for r in records for c in r["courses"] if c["verdict"] not in ("unsure_gold", "not_read")]
    n = len(scored)
    v = Counter(c["verdict"] for c in scored)
    found = sum(r["reading"]["courses_found"][1] for r in records)
    total = sum(r["reading"]["courses_found"][0] for r in records)
    credit_err = [len(r["reading"]["credit_mismatch"]) for r in records]
    exact = sum(1 for r in records if r["reading"]["cgpa"][0] == r["reading"]["cgpa"][1]
                and r["reading"]["years"][0] == r["reading"]["years"][1] and r["reading"]["lateral"][0] == r["reading"]["lateral"][1])
    vd = [len(r["verdicts"]["different"]) for r in records if r.get("verdicts")]
    return {"samples": len(records), "scored": n, "correct": v["correct"], "wrong": v["wrong"], "not_counted": v["not_counted"],
            "found": found, "total": total, "credit_err_max": max(credit_err) if credit_err else 0,
            "header_exact": exact, "verdict_diff": sum(vd), "verdict_samples": len(vd)}


def _targets_table(s: dict) -> list:
    if not s["samples"]:
        return ["_no runs yet_"]
    rows = [
        ("T1 wrong verdicts", f"{s['verdict_diff']} in {s['verdict_samples']} samples", s["verdict_diff"] == 0),
        ("T2 CGPA, years, lateral entry", f"{s['header_exact']}/{s['samples']} memos exact", s["header_exact"] == s["samples"]),
        ("T3 courses found", f"{s['found']}/{s['total']} ({_pct(s['found'], s['total'])})", s["total"] and s["found"] / s["total"] >= TARGETS["T3_courses_found"]),
        ("T4 credit errors per memo", f"max {s['credit_err_max']}", s["credit_err_max"] <= TARGETS["T4_credit_errors_per_memo"]),
        ("T5 wrong classification", f"{s['wrong']}/{s['scored']} ({_pct(s['wrong'], s['scored'])})", s["scored"] and s["wrong"] / s["scored"] <= TARGETS["T5_wrong_share"]),
        ("T6 not counted", f"{s['not_counted']}/{s['scored']} ({_pct(s['not_counted'], s['scored'])})", s["scored"] and s["not_counted"] / s["scored"] <= TARGETS["T6_not_counted_share"]),
    ]
    out = ["| Target | Result | Met |", "|---|---|---|"]
    out += [f"| {a} | {b} | {'yes' if ok else '**no**'} |" for a, b, ok in rows]
    return out


def report(records: list | None = None) -> str:
    records = load_log() if records is None else records
    latest = {}
    for r in records:                                  # latest run per sample per version
        latest[(r["sample"], r["version"]["version"])] = r
    recs = list(latest.values())
    newest_version = recs[-1]["version"]["version"] if recs else None
    cur = [r for r in recs if r["version"]["version"] == newest_version]
    L = [f"# GPU-R evaluation report", "", f"Generated {datetime.now():%d.%m.%Y %H:%M} from {len(records)} logged runs. "
         f"Current version: `{newest_version}`. Plan and targets: `tests/synthetic/EVAL_PLAN.md`.", ""]
    for split in ("heldout", "dev"):
        part = [r for r in cur if r.get("split", "dev") == split]
        L += [f"## Targets — {split} set ({len(part)} samples, current version)", ""] + _targets_table(summarise(part)) + [""]

    L += ["## Samples (current version)", "", "| Sample | University | Field | Layout | Courses found | Credit errors | Correct | Wrong | Not counted | Unsure label | Verdicts same | AI calls | Tokens in/out |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in cur:
        c = Counter(x["verdict"] for x in r["courses"])
        vd = r.get("verdicts") or {}
        u = r.get("usage") or {}
        L.append(f"| {r['sample']} | {r['university']} | {r['field']} | {r['layout']}{' (abbrev.)' if r.get('abbreviated') else ''} | "
                 f"{r['reading']['courses_found'][1]}/{r['reading']['courses_found'][0]} | {len(r['reading']['credit_mismatch'])} | "
                 f"{c['correct']} | {c['wrong']} | {c['not_counted']} | {c['unsure_gold']} | "
                 f"{vd.get('same', '-')}/{vd.get('programmes', '-')} | {u.get('calls', '-')} | {u.get('input_tokens', '-')}/{u.get('output_tokens', '-')} |")
    L.append("")

    # reading by layout
    L += ["## Reading by layout", "", "| Layout | Memos | Courses found | Missing | Extra | Credit errors |", "|---|---|---|---|---|---|"]
    by_layout = defaultdict(list)
    for r in cur:
        by_layout[r["layout"] + (" abbrev." if r.get("abbreviated") else "")].append(r)
    for lay, rs in by_layout.items():
        f = sum(x["reading"]["courses_found"][1] for x in rs)
        t = sum(x["reading"]["courses_found"][0] for x in rs)
        L.append(f"| {lay} | {len(rs)} | {f}/{t} | {sum(len(x['reading']['missing']) for x in rs)} | "
                 f"{sum(len(x['reading']['extra']) for x in rs)} | {sum(len(x['reading']['credit_mismatch']) for x in rs)} |")
    misses = [(r["sample"], m) for r in cur for m in r["reading"]["missing"]]
    if misses:
        L += ["", "Missing courses: " + "; ".join(f"{s}: {m}" for s, m in misses)]
    L.append("")

    # classification by category
    cat = defaultdict(Counter)
    for r in cur:
        for c in r["courses"]:
            if c["verdict"] in ("unsure_gold", "not_read"):
                continue
            gold, got = set(c["gold"]), set(c["got"])
            for k in gold | got:
                if c["verdict"] == "correct":
                    cat[k]["correct"] += 1
                elif c["verdict"] == "not_counted":
                    if k in gold:
                        cat[k]["not_counted"] += 1
                else:
                    cat[k]["missed" if k in gold - got else "extra" if k in got - gold else "kept_in_wrong"] += 1
            if not gold and c["verdict"] == "correct":
                cat["(no category)"]["correct"] += 1
    L += ["## Classification by category (where to improve the taxonomy)", "",
          "missed = the label has it, the answer not; extra = the answer has it, the label not.", "",
          "| Category | Correct | Missed | Extra | Not counted | Error share |", "|---|---|---|---|---|---|"]
    for k, v in sorted(cat.items(), key=lambda kv: -(kv[1]["missed"] + kv[1]["extra"] + kv[1]["not_counted"])):
        tot = sum(v.values())
        err = v["missed"] + v["extra"] + v["not_counted"]
        L.append(f"| {k} | {v['correct']} | {v['missed']} | {v['extra']} | {v['not_counted']} | {_pct(err, tot)} |")
    L.append("")

    # by answer source
    src = defaultdict(Counter)
    for r in cur:
        for c in r["courses"]:
            if c["verdict"] not in ("unsure_gold", "not_read"):
                src[c.get("source") or "unknown"][c["verdict"]] += 1
    L += ["## Accuracy by answer source (how the course map, knowledge base, AI and lab rule perform)", "",
          "| Source | Courses | Correct | Wrong | Not counted |", "|---|---|---|---|---|"]
    for k, v in sorted(src.items()):
        n = sum(v.values())
        L.append(f"| {k} | {n} | {v['correct']} ({_pct(v['correct'], n)}) | {v['wrong']} | {v['not_counted']} |")
    L.append("")

    # map coverage = how titles change between universities
    L += ["## Course-map coverage by university (how much each university's titles differ from the map)", "",
          "| Sample | University | Titles known to the map | New titles |", "|---|---|---|---|"]
    for r in cur:
        known = sum(1 for c in r["courses"] if c.get("in_map"))
        L.append(f"| {r['sample']} | {r['university']} | {known}/{len(r['courses'])} ({_pct(known, len(r['courses']))}) | {len(r['courses']) - known} |")
    L.append("")

    # title variants of the same subject
    variants = defaultdict(set)
    for r in cur:
        for c in r["courses"]:
            if c["gold"]:
                variants[", ".join(sorted(x.split('.')[-1] for x in c["gold"]))].add(c["full_title"])
    L += ["## Same subject, different titles (candidates for course-map entries)", "",
          "| Label | Distinct titles | Examples |", "|---|---|---|"]
    for k, ts in sorted(variants.items(), key=lambda kv: -len(kv[1]))[:20]:
        L.append(f"| {k} | {len(ts)} | {'; '.join(sorted(ts)[:5])} |")
    L.append("")

    # not counted and wrong
    nc = [(r["sample"], c) for r in cur for c in r["courses"] if c["verdict"] == "not_counted"]
    L += ["## Not counted (AI unsure, no syllabus) — taxonomy or map gaps", ""]
    L += [f"- {s}: **{c['printed']}** (label: {', '.join(x.split('.')[-1] for x in c['gold']) or 'no category'}; source {c.get('source')})" for s, c in nc] or ["- none"]
    wr = [(r["sample"], c) for r in cur for c in r["courses"] if c["verdict"] == "wrong"]
    L += ["", "## Wrong answers (sure, but different from the label)", ""]
    L += [f"- {s}: **{c['printed']}** — label [{', '.join(x.split('.')[-1] for x in c['gold']) or 'none'}], "
          f"answer [{', '.join(x.split('.')[-1] for x in c['got']) or 'none'}], source {c.get('source')}" for s, c in wr] or ["- none"]
    L.append("")

    # verdicts
    L += ["## Verdict differences (pipeline vs. true values and labels)", "",
          "Neutral check: courses with an unsure label take the pipeline's own answer on the true side, and route answers are copied, so every difference comes from a reading or classification error.", ""]
    any_d = False
    for r in cur:
        for pid, d in (r.get("verdicts") or {}).get("different", {}).items():
            any_d = True
            L.append(f"- {r['sample']} / {pid}: true list {d['gold']}, pipeline list {d['pipeline']}")
    if not any_d:
        L.append("- none")
    L.append("")

    # versions
    byv = defaultdict(list)
    for r in recs:
        byv[r["version"]["version"]].append(r)
    L += ["## Before / after by version", "", "| Version | Samples | Correct | Wrong | Not counted | Courses found | Verdict differences |", "|---|---|---|---|---|---|---|"]
    for ver, rs in byv.items():
        s = summarise(rs)
        L.append(f"| `{ver}` | {s['samples']} | {_pct(s['correct'], s['scored'])} | {_pct(s['wrong'], s['scored'])} | "
                 f"{_pct(s['not_counted'], s['scored'])} | {_pct(s['found'], s['total'])} | {s['verdict_diff']} |")
    L.append("")
    text = "\n".join(L)
    RESULTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(text, encoding="utf-8")
    return text
