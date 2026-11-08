"""
German conversion module -- everything that turns a raw, stabilized student
profile (native credits, raw CGPA, per-course classifications) into the
final, matching-engine-ready profile (German grade + ECTS credits).

Three concerns, kept in one file as requested, but still functionally
distinct inside it:

1. German grade conversion (Modified Bavarian Formula)
2. ECTS conversion (native credits -> ECTS)
3. Aggregate category computation (general_cs, practical_cs,
   general_mathematics -- union-of-unique-course-IDs, not sum)

Nothing in this file does classification or transcript parsing -- it only
converts values that are already resolved and stabilized.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# 1. German grade conversion -- Modified Bavarian Formula
# ---------------------------------------------------------------------------

@dataclass
class GermanGradeResult:
    source_cgpa: float
    n_max: float
    n_min: float
    german_grade: float
    note: str


def calculate_german_grade(cgpa: float, n_max: float = 10.0, n_min: float = 4.0) -> GermanGradeResult:
    """
    Modified Bavarian Formula: German = 1 + 3 * (Nmax - Nd) / (Nmax - Nmin)

    Nd   = the student's actual result (their stated CGPA)
    Nmax = best possible result on the ORIGINAL scale (10.0 for a 10-point
           CGPA system -- confirm this matches the actual transcript scale)
    Nmin = the MINIMUM PASSING grade on that scale -- NOT the scale's
           absolute floor (0). Using 0 silently inflates the German grade
           (makes it look better than it is) -- confirmed via research:
           most Indian 10-point engineering CGPA scales use Nmin=4.0, but
           some institutions use 5.0. This MUST be confirmed against the
           specific institution's own grading-scale documentation or grade
           card before the result is trusted for a real eligibility check --
           it is not safe to assume either value silently.

    Defaults here (Nmax=10.0, Nmin=4.0) are the most common convention, but
    are returned in the result object explicitly so nothing is hidden.
    """
    if n_max == n_min:
        raise ValueError("n_max and n_min cannot be equal -- division by zero.")

    german_grade = 1 + 3 * (n_max - cgpa) / (n_max - n_min)
    german_grade = round(german_grade, 2)

    return GermanGradeResult(
        source_cgpa=cgpa,
        n_max=n_max,
        n_min=n_min,
        german_grade=german_grade,
        note=(
            f"Computed with Nmax={n_max}, Nmin={n_min}. Nmin is the minimum "
            f"PASSING grade on the source scale, not the scale floor -- if "
            f"this institution's actual minimum passing CGPA differs from "
            f"{n_min}, this result is wrong and must be recomputed with the "
            f"correct value before being used in any eligibility gate."
        )
    )


# ---------------------------------------------------------------------------
# 2. ECTS conversion
# ---------------------------------------------------------------------------

@dataclass
class ECTSConversionResult:
    source_credits: float
    ects: float
    ratio_used: float
    note: str


def convert_credits_to_ects(indian_credits: float, ratio: float = 1.5) -> ECTSConversionResult:
    """
    Converts a single Indian-credit value to German ECTS.

    Default ratio (1.5) is the standard, widely-used conversion for 4-year
    Indian BTech programs (~160 total credits -> ~240 ECTS, matching a
    standard European 4-year bachelor's). This is an ASSUMPTION, not a
    universal rule -- always documented in the result, never silently
    applied.
    """
    ects = round(indian_credits * ratio, 2)
    return ECTSConversionResult(
        source_credits=indian_credits,
        ects=ects,
        ratio_used=ratio,
        note=(
            f"Converted using the standard {ratio}x ratio (1 Indian credit = "
            f"{ratio} ECTS). This is a widely-used default for 4-year Indian "
            f"BTech programs, not a universal or officially-mandated rule -- "
            f"verify against the specific receiving institution's own "
            f"conversion policy if precision matters for a real application."
        )
    )


def round_up_1_decimal(x: float) -> float:
    """Koushik 28.10.2026: the ECTS factor is rounded UP to 1 decimal (1.4634 -> 1.5, 1.125 -> 1.2, 1.5 stays 1.5)."""
    return math.ceil(round(x * 10, 9)) / 10


@dataclass
class ECTSFactor:
    factor: float              # ECTS per 1 native credit
    basis: str                 # "official" or "approximate"
    explanation: str


def compute_ects_factor(degree_years: float, lateral_entry: bool, memo_credits: float,
                        program_total_credits: Optional[float] = None) -> ECTSFactor:
    """
    The method German universities publish (TU Dresden "U = 60 x D / CS", Uni Mannheim
    "60 / (KP/J)", Uni Augsburg): 60 ECTS per year of the degree program, divided by the
    total credits of the WHOLE degree program.

    official     -- the program total from the student's regulations is known:
                    factor = 60 x degree_years / program_total_credits
                    (lateral entry included: the degree is still the full program).
    approximate  -- the program total is not known, so the memo total stands in for it:
                    regular:  60 x degree_years / memo_credits
                    lateral:  60 x (degree_years - 1) / memo_credits   (the memo has no year 1)
                    Wrong if the memo is incomplete (e.g. final semester missing).
    """
    if degree_years <= 0:
        raise ValueError("degree_years must be positive.")
    if program_total_credits:
        raw = 60 * degree_years / program_total_credits
        factor = round_up_1_decimal(raw)
        return ECTSFactor(factor, "official",
                          f"60 x {degree_years:g} years / {program_total_credits:g} program credits "
                          f"= {raw:.4f}, rounded up to {factor:.1f} ECTS per credit")
    years_on_memo = degree_years - 1 if lateral_entry else degree_years
    if years_on_memo <= 0 or not memo_credits:
        raise ValueError("Cannot estimate the ECTS factor: no program total and no memo credits.")
    raw = 60 * years_on_memo / memo_credits
    factor = round_up_1_decimal(raw)
    return ECTSFactor(factor, "approximate",
                      f"APPROXIMATE: program total credits not given, so 60 x {years_on_memo:g} years / "
                      f"{memo_credits:g} credits on the memo = {raw:.4f}, rounded up to {factor:.1f} ECTS per credit"
                      + (" (lateral entry: year 1 not on the memo)" if lateral_entry else "")
                      + ". Give the program total from the regulations for the official value.")


def convert_profile_to_ects(atomic_profile: dict, ratio: float = 1.5) -> dict:
    """
    Converts an entire atomic category profile (native credits) to ECTS,
    category by category. Returns {category_id: ects_value}.
    """
    return {cat: round(credits * ratio, 2) for cat, credits in atomic_profile.items()}


# ---------------------------------------------------------------------------
# 3. Aggregate category computation -- union of unique course IDs
# ---------------------------------------------------------------------------

def _course_categories(course: dict) -> set:
    """
    Normalizes a single course-classification record's flat `categories` list
    (as emitted by course_classifier.py -- no primary/secondary ranking, every
    match is equal and independent) into a set for the union computation
    below.
    """
    return set(c for c in course.get("categories", []) if c)


def compute_aggregates(taxonomy: dict, course_classifications: Optional[list] = None,
                        atomic_profile: Optional[dict] = None) -> dict:
    """
    Builds general_cs, practical_cs, general_mathematics, and any
    university-specific CONTEXTUAL pools (e.g. math_and_theoretical_cs_combined)
    from a student's coursework -- both aggregate_categories AND
    contextual_categories are computed, since the matching engine may need
    either depending on how a specific program phrases its requirement.

    CORRECT PATH -- pass course_classifications:
        A list of per-course classification dicts. Each course needs a
        "course_id", a "credits" value, and a flat "categories" list -- no
        primary/secondary ranking, every category a course genuinely belongs
        to is an equal, independent match (see _course_categories()).

        This path builds, for each aggregate/contextual category, the UNION
        of unique course_ids across all its component atomic categories,
        then sums each qualifying course's credits exactly ONCE -- even if
        that course is dual-mapped into two component categories of the same
        pool. This is the only correct way to compute a pooled total without
        double-counting a course that legitimately spans two of its parts.

    FALLBACK PATH -- atomic_profile only (no per-course data available):
        Sums each component category's total directly. This CAN
        double-count credits from any course that is dual-mapped across two
        component categories of the same pool, because the per-course detail
        needed to deduplicate has already been lost by the time an
        atomic_profile dict (category -> total credits) is built. This path
        exists only for backward compatibility and its result is explicitly
        flagged as approximate -- it should not be trusted for a real
        eligibility decision once course_classifications is available.
    """
    pool_defs = {}
    pool_defs.update(taxonomy.get("aggregate_categories", {}))
    pool_defs.update(taxonomy.get("contextual_categories", {}))
    results = {}

    if course_classifications is not None:
        for pool_id, pool_def in pool_defs.items():
            components = set(pool_def.get("formula_components", []))
            seen_course_ids = set()
            total = 0.0
            for course in course_classifications:
                if _course_categories(course) & components:  # course touches this pool
                    course_id = course["course_id"]
                    if course_id not in seen_course_ids:
                        seen_course_ids.add(course_id)
                        total += course.get("credits", 0)
            results[pool_id] = {
                "total": round(total, 2),
                "method": "union_of_unique_course_ids",
                "type": pool_def.get("type", "AGGREGATE"),
                "contributing_courses": sorted(seen_course_ids),
            }
        return results

    if atomic_profile is not None:
        for pool_id, pool_def in pool_defs.items():
            components = pool_def.get("formula_components", [])
            total = sum(atomic_profile.get(comp, 0) for comp in components)
            results[pool_id] = {
                "total": round(total, 2),
                "method": "SUM_OF_CATEGORIES_APPROXIMATE",
                "type": pool_def.get("type", "AGGREGATE"),
                "warning": (
                    "Computed by summing component category totals because "
                    "no per-course classification data was provided. This "
                    "can double-count a course that is genuinely dual-mapped "
                    "across two of this pool's component categories. "
                    "Do not use this value for a real eligibility check if "
                    "course_classifications is available instead."
                ),
            }
        return results

    raise ValueError("Must provide either course_classifications (preferred) or atomic_profile (fallback).")


# ---------------------------------------------------------------------------
# Final assembly -- the one object the matching engine actually reads
# ---------------------------------------------------------------------------

@dataclass
class FinalMatchingProfile:
    degree_field: str
    german_grade: float
    atomic_profile_ects: dict
    aggregate_profile_ects: dict
    excluded_courses: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def build_final_profile(degree_field: str, cgpa: float, atomic_profile_native: dict,
                         taxonomy: dict, course_classifications: Optional[list] = None,
                         excluded_courses: Optional[list] = None,
                         grade_n_max: float = 10.0, grade_n_min: float = 4.0,
                         ects_ratio: float = 1.5) -> FinalMatchingProfile:
    """
    Assembles the single, complete, matching-engine-ready profile.
    """
    warnings = []

    grade_result = calculate_german_grade(cgpa, n_max=grade_n_max, n_min=grade_n_min)
    warnings.append(grade_result.note)

    atomic_ects = convert_profile_to_ects(atomic_profile_native, ratio=ects_ratio)

    aggregates = compute_aggregates(
        taxonomy,
        course_classifications=course_classifications,
        atomic_profile=None if course_classifications is not None else atomic_profile_native,
    )
    aggregate_ects = {
        agg_id: convert_credits_to_ects(data["total"], ratio=ects_ratio).ects
        for agg_id, data in aggregates.items()
    }
    for agg_id, data in aggregates.items():
        if data["method"] != "union_of_unique_course_ids":
            warnings.append(f"Aggregate '{agg_id}': {data.get('warning', 'approximate method used')}")

    return FinalMatchingProfile(
        degree_field=degree_field,
        german_grade=grade_result.german_grade,
        atomic_profile_ects=atomic_ects,
        aggregate_profile_ects=aggregate_ects,
        excluded_courses=excluded_courses or [],
        warnings=warnings,
    )


if __name__ == "__main__":
    print("German conversion module loaded.")
    print("Use build_final_profile(...) to produce the matching-engine-ready profile.")
