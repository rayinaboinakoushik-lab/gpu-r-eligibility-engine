"""
Step 2b (28.10.2026): the student checks what was read from the transcript.

Rule (Koushik): the system reads everything it can, shows it, and WAITS. The student types "fine" to
continue, or corrects a value; the system then continues with the student's value. Nothing printed on the
transcript is asked blind.

Credit -> ECTS (option B, Koushik 28.10.2026): from the memo's own printed values,
    factor = 60 x years studied / credits required for the award of the degree
rounded UP to 1 decimal (german_conversion.compute_ects_factor). Lateral entry: years studied = years on
the memo (e.g. II-IV year = 3), credits = "minimum credits for award of degree" printed for that track.

Mandatory inputs asked separately (not here): Nmax, Nmin, related field (1-4).
Optional: GATE score (only University of Rostock route B uses it).
"""
from __future__ import annotations

from german_conversion import compute_ects_factor

# (key, label, kind) in the order shown to the student
FIELDS = [
    ("student_name", "Name", "text"),
    ("institution", "Institution", "text"),
    ("program", "Programme / branch", "text"),
    ("regulation", "Regulation", "text"),
    ("stated_cgpa", "CGPA (as printed)", "number"),
    ("entry_type", "Entry type (regular / lateral_entry)", "entry"),
    ("years_studied", "Years studied (years with courses on the memo)", "number"),
    ("credits_registered", "Credits registered (as printed)", "number"),
    ("credits_for_award", "Credits required for the award of the degree (as printed)", "number"),
]

GATE_PROGRAMMES = ("University of Rostock: Electrical Engineering (M.Sc.) and "
                   "Computational Science and Engineering (M.Sc.)")


def initial_values(extraction) -> dict:
    """Values read from the transcript, with plain fallbacks the student then confirms."""
    courses_sum = round(sum(c.credits or 0 for c in extraction.courses), 2)
    registered = extraction.stated_total_credits if extraction.stated_total_credits is not None else courses_sum
    award = getattr(extraction, "min_credits_for_award", None)
    years = getattr(extraction, "years_with_courses", None)
    return {
        "student_name": extraction.student_name,
        "institution": extraction.institution,
        "program": extraction.program,
        "regulation": extraction.regulation,
        "stated_cgpa": extraction.stated_cgpa,
        "entry_type": extraction.entry_type if extraction.entry_type in ("regular", "lateral_entry") else "regular",
        "years_studied": years,
        "credits_registered": registered,
        "credits_for_award": award if award is not None else registered,
    }


def checksum_line(values: dict, courses: list) -> str:
    s = round(sum(c.credits or 0 for c in courses), 2)
    reg = values.get("credits_registered")
    if reg is None:
        return f"Course credits add up to {s:g} (no printed total to compare)"
    ok = abs(s - float(reg)) < 0.01
    return (f"Course credits add up to {s:g} vs {float(reg):g} printed: "
            + ("MATCH" if ok else "MISMATCH -- check the courses below before typing fine"))


def render(values: dict, courses: list) -> str:
    out = ["", "=== Please check what was read from your transcript ===", ""]
    for i, (key, label, _) in enumerate(FIELDS, 1):
        v = values.get(key)
        out.append(f"  {i}. {label}: {'(not found -- please enter)' if v in (None, '', 'UNKNOWN') else v}")
    out += ["", f"  Courses ({len(courses)}):"]
    for i, c in enumerate(courses, 1):
        sem = f"  [{c.semester}]" if getattr(c, "semester", None) else ""
        out.append(f"    c{i:<3} {c.title}  -- {c.credits:g} credits{sem}")
    out += ["", "  " + checksum_line(values, courses)]
    return "\n".join(out)


def _missing(values: dict) -> list:
    need = ("stated_cgpa", "years_studied", "credits_for_award")
    return [k for k in need if values.get(k) in (None, "", "UNKNOWN")]


def _ask_value(kind: str, label: str, input_fn):
    while True:
        raw = input_fn(f"  New value for '{label}': ").strip()
        if kind == "text" and raw:
            return raw
        if kind == "entry" and raw.lower() in ("regular", "lateral_entry", "lateral", "l", "r"):
            return "lateral_entry" if raw.lower().startswith("l") else "regular"
        if kind == "number":
            try:
                v = float(raw)
                if v > 0:
                    return int(v) if v.is_integer() and label.startswith("Years") else v
            except ValueError:
                pass
        print("  Please enter a valid value." + (" (regular or lateral_entry)" if kind == "entry" else ""))


def confirm(values: dict, courses: list, input_fn=None, print_fn=None) -> tuple[dict, list]:
    """Shows everything, waits for 'fine'; otherwise takes the student's corrections. Returns (values, courses)."""
    input_fn, print_fn = input_fn or (lambda p="": input(p)), print_fn or print
    while True:
        print_fn(render(values, courses))
        missing = _missing(values)
        if missing:
            labels = {k: lab for k, lab, _ in FIELDS}
            print_fn("\n  Please enter the missing value(s): " + ", ".join(labels[m] for m in missing))
        raw = input_fn('\nType "fine" if everything is correct, or the number to correct '
                       '(1-9, or c<number> for a course, e.g. c12): ').strip().lower()
        if raw == "fine":
            if missing:
                print_fn("  Some required values are still missing (see above).")
                continue
            return values, courses
        if raw.isdigit() and 1 <= int(raw) <= len(FIELDS):
            key, label, kind = FIELDS[int(raw) - 1]
            values[key] = _ask_value(kind, label, input_fn)
            continue
        if raw.startswith("c") and raw[1:].isdigit() and 1 <= int(raw[1:]) <= len(courses):
            c = courses[int(raw[1:]) - 1]
            t = input_fn(f"  Title [{c.title}] (Enter keeps it): ").strip()
            if t:
                c.title = t
            while True:
                cr = input_fn(f"  Credits [{c.credits:g}] (Enter keeps it): ").strip()
                if not cr:
                    break
                try:
                    c.credits = float(cr)
                    break
                except ValueError:
                    print_fn("  Please enter a number.")
            continue
        print_fn('  Please type "fine", a number from 1 to 9, or c<number>.')


def apply_to_extraction(extraction, values: dict) -> None:
    """Writes the confirmed values back, so every later step uses the student's confirmed data."""
    for key in ("student_name", "institution", "program", "regulation", "stated_cgpa", "entry_type"):
        setattr(extraction, key, values[key])
    extraction.stated_total_credits = values["credits_registered"]


def degree_from_confirmed(values: dict) -> dict:
    """Checkpoint degree fields: factor = 60 x years studied / credits for award, rounded up to 1 decimal."""
    years = float(values["years_studied"])
    award = float(values["credits_for_award"])
    lateral = values["entry_type"] == "lateral_entry"
    e = compute_ects_factor(years, lateral, float(values["credits_registered"] or award), award)
    return {"degree_years": years, "lateral_entry": lateral, "program_total_credits": award,
            "ects_factor": e.factor, "ects_basis": e.basis, "ects_explanation": e.explanation}


def ask_gate(input_fn=None, print_fn=None):
    """Optional. Returns the score or None."""
    input_fn, print_fn = input_fn or (lambda p="": input(p)), print_fn or print
    print_fn("\nGATE score (optional): only used for " + GATE_PROGRAMMES +
             ", where GATE >= 500 replaces the 85% CGPA rule (route B).")
    while True:
        raw = input_fn("Your GATE score, or press Enter to skip: ").strip()
        if not raw:
            return None
        try:
            v = float(raw)
            if 0 <= v <= 1000:
                return v
        except ValueError:
            pass
        print_fn("  Please enter a score between 0 and 1000, or press Enter to skip.")
