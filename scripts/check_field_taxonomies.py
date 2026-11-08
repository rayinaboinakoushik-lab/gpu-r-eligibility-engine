"""Checks the four field taxonomies against the frozen records and the master taxonomy.
Fails (exit 1) if a record uses a name its field file does not know, if a field file has an ID that is not in
the master, if an _implies rule points outside its file, or if a sum lists a part the file does not have."""
import json, glob, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TAX = ROOT / "data" / "taxonomy"; FROZEN = ROOT / "data" / "frozen"
FIELDS = {"cs": "computer_science", "eee": "electrical_electronic_engineering",
          "mechanical": "mechanical_engineering", "civil": "civil_engineering"}
master = json.loads((TAX / "GPU-R_taxonomy_master.json").read_text(encoding="utf-8"))
mnames = set(master["category_evidence_status"]) | set(master["aggregate_categories"]) | set(master["contextual_categories"])
errors = []
for key, fld in FIELDS.items():
    t = json.loads((TAX / f"{key}_taxonomy.json").read_text(encoding="utf-8"))
    atoms = set(t["category_evidence_status"])
    sums = {**t["aggregate_categories"], **t["contextual_categories"]}
    known = atoms | set(sums)
    for n in known - mnames:
        errors.append(f"{key}: {n} is not in the master taxonomy")
    for a, bs in t.get("_implies", {}).items():
        for b in [a, *bs]:
            if b not in atoms:
                errors.append(f"{key}: _implies uses {b}, not an atomic category of this file")
    for s, v in sums.items():
        for p in v["formula_components"]:
            if p not in known:
                errors.append(f"{key}: sum {s} lists {p}, not in this file")
    recs = json.loads(next(FROZEN.glob(f"GPU-R_{fld}_FROZEN_*.json")).read_text(encoding="utf-8"))
    for r in recs:
        for it in r["subject_credit_requirements"]["items"]:
            for c in [it["canonical_category"], *it["covered_categories"]]:
                if c not in known:
                    errors.append(f"{key}: record {r['id']} uses {c}, unknown to {key}_taxonomy.json")
    print(f"{key}: {len(atoms)} categories, {len(sums)} sums, {len(recs)} records checked")
deg = json.loads((TAX / "degree_fields.json").read_text(encoding="utf-8"))["degree_fields"]
for key, fld in FIELDS.items():
    recs = json.loads(next(FROZEN.glob(f"GPU-R_{fld}_FROZEN_*.json")).read_text(encoding="utf-8"))
    for r in recs:
        for p in r["accepted_degree_fields"].get("primary_fields", []):
            if p not in deg:
                errors.append(f"{key}: record {r['id']} accepts degree field {p}, unknown to degree_fields.json")
for k, v in deg.items():
    for t in v.get("counts_as", []):
        if t not in deg:
            errors.append(f"degree_fields: {k} counts_as {t}, which is not a degree field")
print(f"degree fields: {len(deg)} known")
if errors:
    print("\n".join(errors)); sys.exit(1)
print("field taxonomies: 0 errors")
