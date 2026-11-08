# pipeline/ — transcript -> classified course list (from the PC project, 14.10.2026; adapted 27.10.2026)

Run every script from INSIDE this folder (`cd pipeline`), with OPENAI_API_KEY only in your environment / .env.

Changes on 27.10.2026:
- `paths.py` (new): the taxonomy is read from `../data/taxonomy/` (approved 27.10.2026). A bare name such as
  `cs_taxonomy.json` is looked up there, so the run scripts work unchanged.
- `course_classifier.py`: the prompt now also passes each category's `typical_topics` and the file's
  `_classification_rules` (reference only, never force, never invent, mixed courses ...).
- `matching_engine.py`: REFERENCE ONLY (old engine). The new engine follows the engine spec (Day 3).

NOT copied on purpose: old taxonomies and APPROVED_*.json (replaced by data/), the knowledge-base cache
(old categories; it rebuilds itself), student transcripts/profiles (personal data), backups, .env.
MISSING from the 14.10 zip: `transcript_parser.py` — copy it from your PC project into this folder.
