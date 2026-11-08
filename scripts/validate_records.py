"""
Validate the frozen field files. Exit code 1 on any error (CI fails).
  python scripts/validate_records.py --data data/frozen --taxonomy data/taxonomy/test_taxonomy_all.json
Checks: MANIFEST checksums, v2 key order, Pydantic schema, duplicate ids, unknown categories.
"""
import argparse, hashlib, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pydantic import ValidationError                      # noqa: E402
from gpur.schema import Record, check_categories           # noqa: E402

ORDER = ["id", "program", "university", "_domain", "official_sources", "accepted_degree_fields", "gpa_rule_type",
         "grade_requirement", "subject_credit_requirements", "conditional_admission",
         "subsequent_selection_criteria_display", "minimum_total_ects", "language_english", "language_german",
         "standardized_test_requirements", "aps_certificate", "practical_experience_requirement",
         "final_scientific_work_requirement", "other_requirements", "admission_type", "logistics",
         "regulation_watch", "last_checked", "last_updated"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/frozen")
    ap.add_argument("--taxonomy", default=None, help="taxonomy JSON for the unknown-category check")
    a = ap.parse_args()
    data = Path(a.data); errors = []; records = []
    man = data / "MANIFEST.json"
    if man.exists():
        for e in json.loads(man.read_text()):
            if hashlib.sha256((data / e["file"]).read_bytes()).hexdigest() != e["sha256"]:
                errors.append(f"checksum differs: {e['file']} (file changed after the freeze)")
    files = sorted(data.glob("GPU-R_*_FROZEN_*.json"))
    if not files:
        errors.append(f"no frozen files in {data}")
    seen = {}
    for f in files:
        for raw in json.loads(f.read_text(encoding="utf-8")):
            rid = raw.get("id", "?")
            if list(raw) != ORDER:
                errors.append(f"{f.name} {rid}: key order differs from format v2")
            if rid in seen:
                errors.append(f"{rid}: duplicate id ({seen[rid]} and {f.name})")
            seen[rid] = f.name
            try:
                records.append(Record.model_validate(raw))
            except ValidationError as ex:
                for err in ex.errors():
                    errors.append(f"{f.name} {rid}: {'.'.join(map(str, err['loc']))}: {err['msg']}")
    if a.taxonomy:
        unknown = check_categories(records, json.loads(Path(a.taxonomy).read_text(encoding="utf-8")))
        for c, ids in unknown.items():
            errors.append(f"unknown category {c} in {len(ids)} records, e.g. {ids[:3]}")
    print(f"{len(records)} records loaded from {len(files)} files; {len(errors)} errors")
    for e in errors[:200]:
        print("  ERROR", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
