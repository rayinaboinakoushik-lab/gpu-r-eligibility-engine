"""
Copies reviewed answers from the seed (data/knowledge/kb_seed.json) into the local knowledge base, so a
corrected answer replaces the old saved one (05.11.2026). Only the titles you name are touched; a backup of the
local file is written first.

Usage (run from the repo folder, where the stage scripts keep verified_knowledge_base.json):
    py pipeline/sync_kb_from_seed.py <field> "<course title>" ["<course title>" ...]
    py pipeline/sync_kb_from_seed.py eee "Pulse & Digital Circuits" "PDC Lab"
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from knowledge_base import normalize_course_signature

KB_PATH = Path("verified_knowledge_base.json")
SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "kb_seed.json"


def sync(field: str, titles: list, kb_path: Path = KB_PATH, seed_path: Path = SEED_PATH) -> list:
    """Returns one line per title: what was replaced, added, or not found in the seed."""
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    by_sig = {normalize_course_signature(e["title"], e.get("field", "cs")): e for e in seed.values()}
    raw = json.loads(kb_path.read_text(encoding="utf-8")) if kb_path.exists() else {}
    if kb_path.exists():
        shutil.copy2(kb_path, kb_path.with_name(f"{kb_path.stem}_backup_{datetime.now():%Y%m%d_%H%M%S}.json"))
    out = []
    for title in titles:
        target = normalize_course_signature(title, field)
        new = by_sig.get(target)
        if new is None:
            out.append(f"  not in seed: {field} / {title}")
            continue
        old_keys = [k for k, v in raw.items()
                    if normalize_course_signature(v.get("title", ""), v.get("field", "cs")) == target]
        old = [raw.pop(k).get("categories") for k in old_keys]
        raw[new["signature"]] = dict(new)
        out.append(f"  {'replaced' if old else 'added'}:  {field} / {new['title']} {old[0] if old else ''} -> {new['categories']}")
    kb_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    for line in sync(sys.argv[1].strip().lower(), sys.argv[2:]):
        print(line)


if __name__ == "__main__":
    main()
