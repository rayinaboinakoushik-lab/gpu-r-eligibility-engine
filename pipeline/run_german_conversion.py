"""
Runs german_conversion.py against your real, already-verified data:
- CGPA 6.98, field "INFORMATION TECHNOLOGY" (confirmed via verify_grade_field.py)
- The atomic_profile from final_profile.json (native Indian credits)
- Your real cs_taxonomy.json

course_classifications is NOT passed here, because course_classifier.py
doesn't emit that per-course list yet -- so compute_aggregates() will use
the flagged, approximate fallback path and say so explicitly in the output.
That is expected and correct for this run, not a bug.

Run it in the same folder as your other scripts:
    python.exe run_german_conversion.py
"""

import json
from german_conversion import build_final_profile

# Real, already-verified values
CGPA = 6.98
DEGREE_FIELD = "INFORMATION TECHNOLOGY"

# From your real final_profile.json
ATOMIC_PROFILE_NATIVE = {
    "computer_science_informatics.computer_engineering": 25.0,
    "computer_science_informatics.algorithms_data_structures": 8.5,
    "mathematics_statistics.statistics_probability": 4,
    "computer_science_informatics.programming_practical_cs": 13.0,
    "mathematics_statistics.discrete_math_logic": 3,
    "business_economics_management.business_administration": 6,
    "computer_science_informatics.operating_systems": 7.5,
    "computer_science_informatics.databases_systems": 5.5,
    "computer_science_informatics.theoretical_cs": 10.5,
    "computer_science_informatics.software_engineering": 11.5,
    "computer_science_informatics.it_security": 4,
    "data_science.foundational_methods": 3,
    "computer_science_informatics.machine_learning_ai": 3,
    "other.thesis_scientific_work": 10,
    "computer_science_informatics.hci": 3,
}

EXCLUDED_COURSES = [
    {
        "course_id": "GNIT-44",
        "category": "computer_science_informatics.graphics_visual_computing",
        "confidence": "MEDIUM",
    }
]


def main():
    from paths import taxonomy_path
    with open(taxonomy_path("cs_taxonomy.json"), "r", encoding="utf-8") as f:
        taxonomy = json.load(f)

    profile = build_final_profile(
        degree_field=DEGREE_FIELD,
        cgpa=CGPA,
        atomic_profile_native=ATOMIC_PROFILE_NATIVE,
        taxonomy=taxonomy,
        course_classifications=None,   # not available yet -- fallback path expected
        excluded_courses=EXCLUDED_COURSES,
        grade_n_max=10.0,
        grade_n_min=4.0,               # flagged assumption -- confirm against JNTUH's own scale
        ects_ratio=1.5,
    )

    print("=== FINAL MATCHING-READY PROFILE ===")
    print("Degree field   :", profile.degree_field)
    print("German grade   :", profile.german_grade)
    print("\nAtomic profile (ECTS):")
    for cat, val in profile.atomic_profile_ects.items():
        print(f"  {cat}: {val}")

    print("\nAggregate profile (ECTS):")
    for agg, val in profile.aggregate_profile_ects.items():
        print(f"  {agg}: {val}")

    print("\nExcluded courses (pending review, not counted anywhere above):")
    for c in profile.excluded_courses:
        print(f"  {c}")

    print("\n=== WARNINGS (must be resolved before trusting this for a real decision) ===")
    for w in profile.warnings:
        print("-", w)


if __name__ == "__main__":
    main()
