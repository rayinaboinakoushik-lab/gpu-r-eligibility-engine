# Gold answer keys (human-reviewed correct categories per course)

`answer_key_<field>.json` (relabelled 30.10.2026) use the approved 66-category taxonomy, each limited to its field file
(`data/taxonomy/<field>_taxonomy.json`). Each course keeps `old_expected` (the old label) and `relabel_source`:
- `course map (...)`: from `data/taxonomy/GPU-R_course_map.json` (545 JNTUH titles, approved 27.10.2026)
- `hand-checked 27.10`: the CS classification review of 27.10.2026
- `manual: ...`: titles not in the course map, decided by the taxonomy rules (reviewed by Koushik)
- `dropped (not in the <field> field file)`: categories the field's classifier cannot output

Measure (from `pipeline/`, uses the OpenAI key in `.env`; never touches the real knowledge base):
    py eval_classifier.py --key ../tests/gold/answer_key_cs.json

`OLD_answer_key_*.json` (before 27.10.2026, old categories) are kept for reference only.
