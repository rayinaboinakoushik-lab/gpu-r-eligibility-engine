"""Where the pipeline finds the approved data inside the gpu-r repo (added 27.10.2026)."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TAXONOMY_DIR = REPO / "data" / "taxonomy"     # cs / eee / mechanical / civil _taxonomy.json (approved 27.10.2026)
FROZEN_DIR = REPO / "data" / "frozen"         # frozen records + MANIFEST.json


def taxonomy_path(name_or_path: str) -> Path:
    """'cs_taxonomy.json' -> data/taxonomy/cs_taxonomy.json; an existing path is returned as it is."""
    p = Path(name_or_path)
    if p.exists():
        return p
    return TAXONOMY_DIR / p.name
