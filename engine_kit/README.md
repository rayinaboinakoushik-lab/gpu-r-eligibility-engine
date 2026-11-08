# GPU-R engine kit (26.10.2026)

Support files for upgrading `matching_engine.py` to **GPU-R Matching Engine Spec v1**. Koushik writes the engine core; this kit gives the config, tests and test students.

## Contents
| File | What it is |
|---|---|
| `engine_config.json` | Route groups, separate variants, gated routes (GATE ≥ 500, water thesis, module average, subject points), exclusions (4352, 4202, 10623), per-area condition caps (6318, 4881), APS-for-India rule, presence-gap rule |
| `tests/test_engine_rules.py` | 14 pytest tests: C1–C4 counting, gated routes, exclusions, degree gate, area cap, IMPORTANT notes, APS, config and manifest checks |
| `tests/gpur_adapter.py` | The ONE function to wire to your engine (`evaluate()`); the expected result shape is in its docstring |
| `tests/fixtures/test_taxonomy_all.json` | Test-only taxonomy: all 65 categories measurable, agreed pools (maths sum T2; general_cs / general_ee / general_mechanical = all sub-categories) |
| `tests/fixtures/student_civil.json`, `student_mechanical.json`, `student_eee.json` | Synthetic JNTUH-style students in the new profile shape (course list with categories) |
| `../frozen_2026-10-24/` | The four frozen field files + MANIFEST.json (sha256) |

## Run
```
cd engine_kit/tests
pytest -q -rs
```
Now: 2 config tests pass, 12 engine tests are skipped until `gpur_adapter.evaluate()` is wired. After wiring, every test must pass before release; any wrong pass blocks release.

## New student profile shape
`field`, `degree_field`, `degree_subfield`, `german_grade`, `total_ects`, `country`, `courses[]` (`id`, `title`, `ects`, `categories[]`), `confirmations` (`gate_score`, `water_thesis`, `module_average_confirmed`, `subject_points_confirmed`), `excluded_courses`.
