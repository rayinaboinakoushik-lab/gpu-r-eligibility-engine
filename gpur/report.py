"""
Eligibility report: the engine's results as text (console) and Markdown (file the student keeps).
Every result shows its checks, so a student can see WHY, not only the list.
"""
from __future__ import annotations

from collections import Counter

from gpur.engine import LIST_NAMES

ICON = {"PASS": "✓", "FAIL": "✗"}
LIST_HELP = {
    1: "You meet every published requirement and there is no selection step.",
    2: "You meet every published requirement; the university then ranks or selects applicants.",
    3: "A subject gap the regulation allows to close with conditions (Auflagen) after admission.",
    4: "A requirement is not met, or the gap is larger than the regulation allows.",
}


def _check_line(c: dict, max_courses: int | None = None) -> str:
    if c["kind"] == "subject":
        if c.get("presence_only"):
            need = "must be covered"
        else:
            need = f"{c['achieved']:g} of {c['required']:g} ECTS"
        names = c.get("courses") or []
        if max_courses is not None and len(names) > max_courses:
            names = names[:max_courses] + [f"+{len(c['courses']) - max_courses} more"]
        used = f"  [{', '.join(names)}]" if names else ""
        return f"{ICON[c['status']]} {c['label']}: {need}{used}"
    if c["kind"] == "grade":
        lim = f" (limit {c['required']:.2f})" if c.get("required") is not None else f" ({c.get('detail', '')})"
        return f"{ICON[c['status']]} German grade {c['achieved']:.2f}{lim}"
    if c["kind"] == "total":
        return f"{ICON[c['status']]} Degree total {c['achieved']:g} of {c['required']:g} ECTS"
    if c["kind"] == "degree":
        return f"{ICON[c['status']]} Degree field: {c.get('detail', '')}"
    return f"{ICON[c['status']]} {c['label']}"


def summary(results: list) -> Counter:
    return Counter(r["list"] for r in results)


def to_text(student: dict, results: list, warnings: list, full: bool = False) -> str:
    counts = summary(results)
    out = [f"=== GPU-R eligibility | {student['name']} | field {student['field']} | degree {student['degree_field']} "
           f"| German grade {student['german_grade']:.2f} | degree {student['total_ects']:g} ECTS ===",
           f"{len(results)} programmes checked: " + ", ".join(f"{LIST_NAMES[k]} {counts.get(k, 0)}" for k in (1, 2, 3, 4))]
    for lst in (1, 2, 3, 4):
        group = [r for r in results if r["list"] == lst]
        if not group:
            continue
        out.append(f"\n--- List {lst}: {LIST_NAMES[lst]} ({len(group)}) --- {LIST_HELP[lst]}")
        for r in group:
            gap = f" | gap {r['real_gap']:g} ECTS" if lst == 3 else ""
            out.append(f"\n• {r['program']} -- {r['university']} [{r['program_id']}]{gap}")
            if lst == 4 and not full:
                out.append("    " + "; ".join(r["reasons"]))
                continue
            for n in r["important_notes"]:
                out.append(f"    ! {n}")
            for c in r["checks"]:
                out.append("    " + _check_line(c, max_courses=None if full else 6))
            for s in r["skipped_routes"]:
                out.append(f"    ? route {s['id']} not checked: needs {s['needs']}" + (f" ({s['why']})" if s.get("why") else ""))
            if lst in (2, 3) and r.get("selection_step"):       # 29.10.2026: also shown for bridging (list 3)
                out.append("    + Selection step: the university also ranks or selects applicants")
                for n in r.get("selection_notes", []):
                    out.append(f"        - {n}")
            for a in r["also_required"]:
                out.append(f"    + also needed: {a}")
    if student.get("excluded_courses"):
        out.append("\nNot counted (no reliable classification; send the syllabus to include them):")
        for e in student["excluded_courses"]:
            out.append(f"  - {e.get('title') or e.get('course_id')}")
    if warnings:
        out.append("\nWarnings:")
        out.extend(f"  - {w}" for w in warnings)
    return "\n".join(out)


def to_markdown(student: dict, results: list, warnings: list) -> str:
    counts = summary(results)
    md = [f"# Eligibility report: {student['name']}", "",
          f"Field **{student['field']}** · degree **{student['degree_field']}** · German grade **{student['german_grade']:.2f}** · "
          f"degree **{student['total_ects']:g} ECTS** · {len(student['courses'])} courses counted", "",
          "| List | Meaning | Programmes |", "|---|---|---|"]
    for k in (1, 2, 3, 4):
        md.append(f"| {k} | {LIST_NAMES[k]} | {counts.get(k, 0)} |")
    for lst in (1, 2, 3, 4):
        group = [r for r in results if r["list"] == lst]
        if not group:
            continue
        md += ["", f"## List {lst}: {LIST_NAMES[lst]} ({len(group)})", "", LIST_HELP[lst]]
        for r in group:
            gap = f" — gap {r['real_gap']:g} ECTS" if lst == 3 else ""
            md += ["", f"### {r['program']} — {r['university']}{gap}"]
            if r["reasons"]:
                md.append("**Why:** " + "; ".join(r["reasons"]))
            md += [f"> {n}" for n in r["important_notes"]]
            md += [f"- {_check_line(c)}" for c in r["checks"]]
            md += [f"- ? route {s['id']} not checked: needs {s['needs']}" + (f" ({s['why']})" if s.get("why") else "")
                   for s in r["skipped_routes"]]
            if lst in (2, 3) and r.get("selection_step"):
                md.append("- **Selection step:** the university also ranks or selects applicants")
                md += [f"  - {n}" for n in r.get("selection_notes", [])]
            if r["also_required"]:
                md.append("- Also needed: " + "; ".join(r["also_required"]))
    if student.get("excluded_courses"):
        md += ["", "## Not counted", ""] + [f"- {e.get('title') or e.get('course_id')}" for e in student["excluded_courses"]]
    if warnings:
        md += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]
    md += ["", "_Deterministic check against the official regulations stored in GPU-R. "
           "The university's decision is final._"]
    return "\n".join(md)
