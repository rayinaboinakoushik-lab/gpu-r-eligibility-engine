"""
Synthetic test transcripts (31.10.2026).

Every sample is built from a REAL official curriculum (course titles, credits, semesters, totals --
source URLs are in each spec) but is clearly marked as test data: fictional student, no logo, no seal,
no signature, and "SYNTHETIC TEST DOCUMENT - NOT A REAL TRANSCRIPT" on every image.

    py tools/synthetic_transcripts.py make                     -> synthetic_out/<id>.jpg + <id>_truth.json
    py tools/synthetic_transcripts.py score <id> <session_id>  -> compares the pipeline run with the truth, adds it to the log
    py tools/synthetic_transcripts.py report                   -> tests/synthetic/results/EVAL_REPORT.md from the whole log
    py tools/synthetic_transcripts.py blind <id>               -> blank label sheet for a blind human check
    py tools/synthetic_transcripts.py agree <id> <sheet.csv>   -> agreement between the human sheet and the labels

The truth file holds what the memo really says (for the reading check) and the gold categories
(tests/synthetic/labels/<id>.json, for the classification check). The verdict check runs the same
deterministic engine on the gold profile and compares lists with the pipeline's eligibility file.
"""
from __future__ import annotations

import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_log import answer_sources, append, map_knows, read_usage, report, version_info  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SPECS = REPO / "tests" / "synthetic" / "specs"
LABELS = REPO / "tests" / "synthetic" / "labels"
OUT = REPO / "synthetic_out"
WATERMARK = "SYNTHETIC TEST DOCUMENT - NOT A REAL TRANSCRIPT"
ZERO_CREDIT_RESULT = "SATISFACTORY"


# ------------------------------------------------------------------ grades and truth
def assign_grades(spec: dict) -> list:
    """Deterministic grades (seeded) whose credit-weighted mean is close to target_cgpa."""
    rnd = random.Random(spec["seed"])
    scale = spec["grading"]                      # [[letter, points], ...] best first
    target = spec["target_cgpa"]
    rows = []
    for sem in spec["semesters"]:
        for c in sem["courses"]:
            if not c["credits"]:
                rows.append({**c, "semester": sem["name"], "grade": ZERO_CREDIT_RESULT, "points": None})
                continue
            want = min(scale[0][1], max(scale[-1][1], rnd.gauss(target, 1.0)))
            letter, pts = min(scale, key=lambda g: abs(g[1] - want))
            rows.append({**c, "semester": sem["name"], "grade": letter, "points": pts})
    return rows


_ABBR = [("ENGINEERING", "ENGG."), ("LABORATORY", "LAB"), ("MANAGEMENT", "MGMT."), ("COMMUNICATION", "COMM."),
         ("INTRODUCTION", "INTRO."), ("PROGRAMMING", "PROG."), ("APPLICATIONS", "APPLNS."), ("MICROCONTROLLERS", "MICROCONTR.")]


def printed_title(title: str, abbreviate: bool, width: int = 38) -> str:
    """How the memo prints the title: as is, or (abbreviate=True) upper case and shortened WORD BY WORD the way
    real memos do ('MANAGERIAL ECO. & FIN. ANALYSIS', 'FLUID MECHANICS & HYDRAULIC MACHIN. LAB'): 'AND' -> '&',
    usual short forms, then the longest words cut to 4-5 letters + '.'. No word is ever dropped."""
    if not abbreviate:
        return title
    t = " ".join(title.upper().replace(" AND ", " & ").split())
    for a, b in _ABBR:
        if len(t) <= width:
            break
        t = t.replace(a, b)
    words = t.split(" ")
    while len(" ".join(words)) > width:
        i = max(range(len(words)), key=lambda k: (len(words[k].rstrip(".")) if not words[k].endswith(".") else 0))
        w = words[i]
        if w.endswith(".") or len(w) <= 5:
            break
        words[i] = w[:5 if len(w) > 8 else 4] + "."
    return " ".join(words)


def cgpa(rows: list) -> float:
    cr = sum(r["credits"] for r in rows if r["points"] is not None)
    return round(sum(r["credits"] * r["points"] for r in rows if r["points"] is not None) / cr, 2)


def truth_for(spec: dict, rows: list) -> dict:
    registered = sum(r["credits"] for r in rows)
    return {
        "id": spec["id"], "field": spec["field"], "synthetic": True, "source": spec["source"],
        "university": spec["university"], "layout": spec.get("layout", "table"), "abbreviated": spec.get("abbreviate", False),
        "provenance": spec.get("provenance", {}),
        "extraction": {
            "institution": spec["institution"], "programme": spec["degree"], "cgpa": cgpa(rows),
            "entry_type": spec["entry"], "years_studied": spec["years"],
            "credits_registered": registered, "credits_for_award_printed": spec["credits_for_award_printed"],
            "n_max": spec["grading"][0][1], "n_min": spec["pass_min"],
            "courses": [{"code": r["code"], "title": printed_title(r["title"], spec.get("abbreviate", False)),
                         "full_title": r["title"], "credits": r["credits"], "semester": r["semester"],
                         "grade": r["grade"]} for r in rows],
        },
    }


# ------------------------------------------------------------------ image
def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    names = (["arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"])
    for n in names + ["/usr/share/fonts/truetype/dejavu/" + names[-1]]:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _header(d, W, spec, f, fb, fh):
    d.text((W // 2, 40), spec["university"].upper(), font=fh, fill=(20, 20, 60), anchor="mm")
    d.text((W // 2, 85), spec["institution"], font=f, fill=(20, 20, 20), anchor="mm")
    d.text((W // 2, 125), "CONSOLIDATED MARKS MEMO / GRADE SHEET" if spec.get("layout") == "two_column" else "MEMORANDUM OF GRADES",
           font=fb, fill=(0, 0, 0), anchor="mm")
    d.text((W // 2, 160), WATERMARK, font=fb, fill=(200, 0, 0), anchor="mm")
    scale = ", ".join(f"{g}={p}" for g, p in spec["grading"])
    meta = [f"Name: SAMPLE STUDENT {spec['id'][1:3]} (fictional)", f"Programme: {spec['degree']}",
            f"Regulation: {spec['regulation']}", f"Grade points: {scale}; minimum pass grade point {spec['pass_min']}"]
    if spec["entry"] == "lateral_entry":
        meta.append("LATERAL ENTRY - DIRECT ADMISSION INTO SECOND YEAR (III SEMESTER)")
    for i, m in enumerate(meta):
        d.text((80, 200 + i * 30), m, font=f, fill=(0, 0, 0))
    return 200 + len(meta) * 30 + 30


def _footer(d, y, spec, truth, fb):
    ex = truth["extraction"]
    foot = [f"Total Credits Registered: {ex['credits_registered']:g}"]
    if spec["credits_for_award_printed"]:
        foot.append(f"Credits required for the award of the degree: {spec['credits_for_award_printed']:g}")
    foot.append(f"CGPA: {ex['cgpa']:.2f}")
    for i, t in enumerate(foot):
        d.text((80, y + i * 32), t, font=fb, fill=(0, 0, 0))
    return y + len(foot) * 32


def render(spec: dict, rows: list, truth: dict, path: Path) -> None:
    """layout 'table': one column, semester blocks. layout 'two_column': odd and even semester of a year side by
    side (S.No, title, grade, credits), like many Indian consolidated memos."""
    from PIL import Image, ImageDraw, ImageFilter
    printed = [c["title"] for c in truth["extraction"]["courses"]]
    rows = [{**r, "shown": t} for r, t in zip(rows, printed)]
    W, row_h = 1700, 30
    img = Image.new("RGB", (W, 200 + (len(rows) + 4 * len(spec["semesters"]) + 30) * row_h), (250, 248, 240))
    d = ImageDraw.Draw(img)
    f, fb, fh, fs = _font(20), _font(20, True), _font(30, True), _font(17)
    y = _header(d, W, spec, f, fb, fh)
    sems = spec["semesters"]
    if spec.get("layout") == "two_column":
        half = (W - 140) // 2
        pairs = [sems[i:i + 2] for i in range(0, len(sems), 2)]
        for pair in pairs:
            d.rectangle((70, y, W - 70, y + row_h), fill=(225, 225, 235))
            d.text((W // 2, y + row_h // 2), " / ".join(f"SEMESTER {s['name']}" for s in pair), font=fb, fill=(20, 20, 90), anchor="mm")
            y += row_h + 6
            for k in range(2):
                x0 = 70 + k * half
                for x, h in ((x0 + 5, "S.No"), (x0 + 60, "COURSE TITLE"), (x0 + half - 170, "GRADE"), (x0 + half - 80, "CR")):
                    d.text((x, y), h, font=fs, fill=(0, 0, 0))
            y += row_h
            blocks = [[r for r in rows if r["semester"] == s["name"]] for s in pair]
            for i in range(max(len(b) for b in blocks)):
                for k, b in enumerate(blocks):
                    if i < len(b):
                        r, x0 = b[i], 70 + k * half
                        d.text((x0 + 5, y), str(i + 1), font=fs, fill=(0, 0, 0))
                        d.text((x0 + 60, y), r["shown"], font=fs, fill=(0, 0, 0))
                        d.text((x0 + half - 165, y), r["grade"] if r["points"] is not None else "CP", font=fs, fill=(0, 0, 0))
                        d.text((x0 + half - 75, y), f"{r['credits']:g}", font=fs, fill=(0, 0, 0))
                y += row_h
            d.line((W // 2, y - row_h * max(len(b) for b in blocks) - row_h, W // 2, y), fill=(120, 120, 120), width=1)
            y += row_h // 2
    else:
        cols = [(80, "Code"), (300, "Course Title"), (1250, "Credits"), (1390, "Grade"), (1520, "Pts")]
        for x, h in cols:
            d.text((x, y), h, font=fb, fill=(0, 0, 0))
        y += row_h
        d.line((70, y, W - 70, y), fill=(0, 0, 0), width=2)
        y += 8
        for sem in sems:
            d.text((80, y), f"SEMESTER {sem['name']}", font=fb, fill=(30, 30, 110))
            y += row_h
            for r in [r for r in rows if r["semester"] == sem["name"]]:
                vals = [r["code"], r["shown"], f"{r['credits']:g}", r["grade"], "" if r["points"] is None else str(r["points"])]
                for (x, _), v in zip(cols, vals):
                    d.text((x, y), v, font=fs if x == 300 and len(v) > 60 else f, fill=(0, 0, 0))
                y += row_h
            y += row_h // 2
    d.line((70, y, W - 70, y), fill=(0, 0, 0), width=2)
    y = _footer(d, y + 20, spec, truth, fb)
    H = y + 120
    img = img.crop((0, 0, W, H))
    d = ImageDraw.Draw(img)
    d.text((W // 2, H - 50), WATERMARK + "  -  NO SEAL, NO SIGNATURE", font=fb, fill=(200, 0, 0), anchor="mm")
    wm = Image.new("RGBA", img.size, (0, 0, 0, 0))
    wd = ImageDraw.Draw(wm)
    for k in range(0, H, 700):
        wd.text((W // 2, k + 300), "SYNTHETIC TEST DATA", font=_font(110, True), fill=(220, 0, 0, 38), anchor="mm")
    wm = wm.rotate(30, resample=Image.BICUBIC, center=(W // 2, H // 2))
    img = Image.alpha_composite(img.convert("RGBA"), wm).convert("RGB")
    rnd = random.Random(spec["seed"])               # light scan effects
    img = img.rotate(rnd.uniform(-0.8, 0.8), resample=Image.BICUBIC, expand=True, fillcolor=(235, 235, 230))
    img = img.filter(ImageFilter.GaussianBlur(0.5))
    img.save(path, "JPEG", quality=72)


def make(ids: list | None = None) -> list:
    OUT.mkdir(exist_ok=True)
    made = []
    for p in sorted(SPECS.glob("*.json")):
        spec = json.loads(p.read_text(encoding="utf-8"))
        if ids and spec["id"] not in ids:
            continue
        rows = assign_grades(spec)
        truth = truth_for(spec, rows)
        lab = LABELS / f"{spec['id']}.json"
        if lab.exists():
            truth["gold"] = json.loads(lab.read_text(encoding="utf-8"))["labels"]
        render(spec, rows, truth, OUT / f"{spec['id']}.jpg")
        (OUT / f"{spec['id']}_truth.json").write_text(json.dumps(truth, indent=1, ensure_ascii=False), encoding="utf-8")
        made.append(spec["id"])
        print(f"{spec['id']}: {len(rows)} courses, {truth['extraction']['credits_registered']:g} credits, "
              f"CGPA {truth['extraction']['cgpa']:.2f} -> {OUT / (spec['id'] + '.jpg')}")
    return made


# ------------------------------------------------------------------ scoring
def norm(t: str) -> str:
    t = (t or "").upper().replace("&", " AND ")
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9+# ]", " ", t)).strip()


def _short(cats) -> list:
    return sorted(c.split(".")[-1] for c in cats or [])


def score(truth: dict, checkpoint: dict, profile: dict, eligibility: dict | None = None) -> dict:
    """Reading, classification and verdict checks. Titles can repeat on a memo (e.g. a 0-credit course in two
    semesters), so courses are compared as multisets of (title, credits)."""
    from collections import Counter
    ex = truth["extraction"]
    got_raw = checkpoint.get("all_courses_raw") or []
    want_c = Counter(norm(c["title"]) for c in ex["courses"])
    got_c = Counter(norm(c["title"]) for c in got_raw)
    want_cr = Counter((norm(c["title"]), float(c["credits"])) for c in ex["courses"])
    got_cr = Counter((norm(c["title"]), float(c.get("credits") or 0)) for c in got_raw)
    found = sum((want_c & got_c).values())
    reading = {
        "cgpa": (ex["cgpa"], checkpoint.get("cgpa")),
        "years": (ex["years_studied"], checkpoint.get("degree_years")),
        "lateral": (ex["entry_type"] == "lateral_entry", checkpoint.get("lateral_entry")),
        "credits_total": (ex["credits_registered"], sum(float(c.get("credits") or 0) for c in got_raw)),
        "courses_found": (sum(want_c.values()), found),
        "missing": sorted((want_c - got_c).elements()),
        "extra": sorted((got_c - want_c).elements()),
        "credit_mismatch": sorted(t for t, _ in ((want_cr - got_cr).elements()) if t in got_c),
        "confirmed_values": checkpoint.get("confirmed_values") or {},
    }
    full_of = {norm(c["title"]): c.get("full_title", c["title"]) for c in ex["courses"]}
    gold_full = truth.get("gold") or {}
    gold = {t: gold_full.get(full_of[t]) for t in full_of}
    final = {norm(c["title"]): c.get("categories") or [] for c in profile.get("courses") or []}
    not_counted = {norm(c["title"]) for c in profile.get("excluded_courses") or []}
    cls = {"correct": [], "wrong": [], "not_counted": [], "unsure_gold": []}
    sources = answer_sources(checkpoint, norm)
    printed_of = {norm(c["title"]): c["title"] for c in ex["courses"]}
    courses = []
    for t in sorted(set(want_c)):
        if t not in got_c:
            verdict = "not_read"                   # a reading error, scored under reading, not classification
            cls.setdefault("not_read", []).append(t)
        elif gold.get(t) is None:
            verdict = "unsure_gold"
            cls["unsure_gold"].append(t)
        elif t in not_counted:
            verdict = "not_counted"
            cls["not_counted"].append(t)
        elif t in final and _short(final[t]) == _short(gold[t]):
            verdict = "correct"
            cls["correct"].append(t)
        else:
            verdict = "wrong"
            cls["wrong"].append({"title": t, "gold": _short(gold[t]), "got": _short(final.get(t))})
        src, conf = sources.get(t, (None, None))
        courses.append({"printed": printed_of[t], "full_title": full_of[t], "gold": gold.get(t) or [],
                        "got": final.get(t, []), "verdict": verdict, "source": src, "confidence": conf,
                        "read_ok": t in got_c})
    out = {"id": truth["id"], "reading": reading, "courses": courses,
           "classification": {k: (len(v) if k == "correct" else v) for k, v in cls.items()}}
    if eligibility is not None and truth.get("gold"):
        out["verdicts"] = verdict_check(truth, profile, eligibility)
    return out


def verdict_check(truth: dict, profile: dict, eligibility: dict) -> dict:
    """Same engine, gold categories + true memo values -> lists; compare with the pipeline's lists.
    Neutral on purpose (02.11.2026): a course with an UNSURE label takes the pipeline's own answer, and the
    answers given to route questions (confirmations, GATE) are copied -- so a difference can only come from a
    real reading or classification error, never from the label sheet or the questions."""
    sys.path.insert(0, str(REPO))
    from gpur import engine, profile as P
    gp = json.loads(json.dumps(profile))
    pipe = {norm(c["title"]): c.get("categories") or [] for c in profile.get("courses") or []}

    def cats(c):
        g = truth["gold"].get(c.get("full_title", c["title"]))
        return pipe.get(norm(c["title"]), []) if g is None else g
    gp["courses"] = [{"course_id": c["code"], "title": c["title"], "credits": c["credits"], "categories": cats(c)}
                     for c in truth["extraction"]["courses"]]
    gp["confirmations"] = dict((eligibility.get("student") or {}).get("confirmations") or profile.get("confirmations") or {})
    factor = gp["ects_conversion"]["factor"]
    for c in gp["courses"]:
        c["ects"] = round(float(c["credits"]) * factor, 2)
    gp["excluded_courses"] = []
    gp.setdefault("degree_field_id", eligibility["student"].get("degree_field"))
    s, _ = P.build_student(gp)
    fd = engine.load_field(truth["field"])
    gold_lists = {r["program_id"]: r["list"] for r in engine.evaluate_field(s, fd)}
    got_lists = {r["program_id"]: r["list"] for r in eligibility["results"]}
    diff = {k: {"gold": gold_lists.get(k), "pipeline": got_lists.get(k)} for k in set(gold_lists) | set(got_lists)
            if gold_lists.get(k) != got_lists.get(k)}
    return {"programmes": len(gold_lists), "same": len(gold_lists) - len(diff), "different": diff}


def main(argv: list) -> None:
    if not argv or argv[0] == "make":
        make(argv[1:] or None)
        return
    if argv[0] == "score":
        sid, session = argv[1], argv[2]
        truth = json.loads((OUT / f"{sid}_truth.json").read_text(encoding="utf-8"))
        ck = json.loads(Path(f"checkpoint_{session}.json").read_text(encoding="utf-8"))
        pr = json.loads(Path(f"final_matching_profile_{session}.json").read_text(encoding="utf-8"))
        el_p = Path(f"eligibility_{session}.json")
        el = json.loads(el_p.read_text(encoding="utf-8")) if el_p.exists() else None
        res = score(truth, ck, pr, el)
        corr_p = OUT / f"{sid}_corrections.json"
        corrections = json.loads(corr_p.read_text(encoding="utf-8")) if corr_p.exists() else None
        res["reading"]["check_screen_corrections"] = corrections
        for c in corrections or []:            # a value corrected on the check screen was READ wrong
            key = {5: "cgpa", 6: "lateral", 7: "years"}.get(c["field"])
            if key == "lateral":
                res["reading"][key] = (res["reading"][key][0], c["shown"] == "lateral_entry")
            elif key:
                try:
                    shown = float(c["shown"])
                except ValueError:
                    shown = c["shown"]
                res["reading"][key] = (res["reading"][key][0], shown)
        (OUT / f"{sid}_score.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
        r, c = res["reading"], res["classification"]
        print(f"== {sid}")
        print(f"Reading: CGPA {r['cgpa'][1]} (true {r['cgpa'][0]}), years {r['years'][1]} (true {r['years'][0]}), "
              f"lateral {r['lateral'][1]} (true {r['lateral'][0]}), courses {r['courses_found'][1]}/{r['courses_found'][0]}, "
              f"credits {r['credits_total'][1]:g} (true {r['credits_total'][0]:g}), credit mismatches {len(r['credit_mismatch'])}")
        if r.get("check_screen_corrections"):
            print("Check screen corrected: " + "; ".join(f"field {x['field']}: read {x['shown']!r}, memo says {x['corrected_to']}" for x in r["check_screen_corrections"]))
        print(f"Classification: correct {c['correct']}, wrong {len(c['wrong'])}, not counted {len(c['not_counted'])}, unsure gold (not scored) {len(c['unsure_gold'])}")
        for w in c["wrong"]:
            print(f"   WRONG {w['title']}: gold {w['gold']}, got {w['got']}")
        for t in c["not_counted"]:
            print(f"   not counted: {t}")
        if "verdicts" in res:
            v = res["verdicts"]
            print(f"Verdicts: {v['same']}/{v['programmes']} same as with the true values")
            for k, x in v["different"].items():
                print(f"   {k}: gold list {x['gold']}, pipeline list {x['pipeline']}")
        spec = json.loads((SPECS / f"{sid}.json").read_text(encoding="utf-8"))
        known = map_knows([c["printed"] for c in res["courses"]], truth["field"])
        for c in res["courses"]:
            c["in_map"] = known.get(c["printed"], False)
        append({"sample": sid, "session": session, "split": spec.get("split", "dev"), "field": truth["field"],
                "university": truth.get("university"), "layout": truth.get("layout"), "abbreviated": truth.get("abbreviated"),
                "version": version_info(truth["field"]), "usage": read_usage(session), **{k: res[k] for k in res if k != "id"}})
        u = read_usage(session)
        if u.get("available"):
            print(f"AI usage: {u['calls']} calls, {u['input_tokens']:,} tokens in, {u['output_tokens']:,} out, {u['seconds']} s")
        print(f"Saved {OUT / (sid + '_score.json')} and added the run to tests/synthetic/results/eval_log.jsonl")
        return
    if argv[0] == "blind":
        # sheet for Koushik's blind labels: titles only, no Claude labels
        import csv
        sid = argv[1]
        spec = json.loads((SPECS / f"{sid}.json").read_text(encoding="utf-8"))
        valid = sorted(c.split(".")[-1] for c in json.loads((REPO / "data" / "taxonomy" / f"{spec['field']}_taxonomy.json")
                                                             .read_text(encoding="utf-8"))["category_evidence_status"])
        out = OUT / f"blind_{sid}.csv"
        OUT.mkdir(exist_ok=True)
        with out.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["title", "credits", "your categories (short names, separated by ;  - leave empty for no category)", "unsure (y)"])
            seen = set()
            for sem in spec["semesters"]:
                for c in sem["courses"]:
                    if c["title"] not in seen:
                        seen.add(c["title"])
                        w.writerow([c["title"], c["credits"], "", ""])
        print(f"Wrote {out}. Categories allowed for this field: {', '.join(valid)}")
        return
    if argv[0] == "agree":
        # compare Koushik's filled sheet with Claude's labels
        import csv
        sid, sheet = argv[1], Path(argv[2])
        mine = json.loads((LABELS / f"{sid}.json").read_text(encoding="utf-8"))["labels"]
        same, diff, skipped = 0, [], 0
        with sheet.open(encoding="utf-8-sig") as f:
            r = csv.reader(f)
            next(r)
            for row in r:
                title, cats, unsure = row[0], row[2], (row[3] if len(row) > 3 else "")
                a = mine.get(title, "missing")
                if unsure.strip().lower().startswith("y") or a is None:
                    skipped += 1
                    continue
                theirs = sorted(x.strip() for x in cats.split(";") if x.strip())
                if theirs == _short(a):
                    same += 1
                else:
                    diff.append((title, theirs, _short(a)))
        n = same + len(diff)
        print(f"Agreement: {same}/{n} ({100 * same / n:.1f} %), {skipped} skipped (unsure on either side)" if n else "No comparable rows.")
        for t, k, c in diff:
            print(f"   {t}: Koushik {k}, Claude {c}")
        return
    if argv[0] == "report":
        report()
        print("Wrote tests/synthetic/results/EVAL_REPORT.md")
        return
    print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
