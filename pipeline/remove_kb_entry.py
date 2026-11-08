"""
Removes wrong answers from the knowledge base, so the next student with that title is
classified fresh (by the LLM, or by their syllabus).

Usage:
    py remove_kb_entry.py <field> "<course title>" ["<course title>" ...]
    py remove_kb_entry.py eee "Robotics" "Elements of Electronics and Communications Engineering"
"""

import json
import sys
from pathlib import Path

from knowledge_base import normalize_course_signature

KB_PATH = Path("verified_knowledge_base.json")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    field, titles = sys.argv[1].strip().lower(), sys.argv[2:]
    if not KB_PATH.exists():
        print(f"No knowledge base file ({KB_PATH}) -- nothing to remove.")
        return
    with open(KB_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    for title in titles:
        target = normalize_course_signature(title, field)
        keys = [k for k, v in raw.items()
                if normalize_course_signature(v.get("title", ""), v.get("field", "cs")) == target]
        if not keys:
            print(f"  not found: {field} / {title}")
        for k in keys:
            v = raw.pop(k)
            print(f"  removed:   {field} / {v.get('title')} -> {v.get('categories')}")
    with open(KB_PATH, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)


if __name__ == "__main__":
    main()
