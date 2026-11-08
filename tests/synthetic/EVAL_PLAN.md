# GPU-R evaluation plan (fixed 31.10.2026, before any run)

Purpose: measure how well GPU-R reads Indian transcripts, classifies their courses and decides eligibility, find out
**where** it fails and **why**, fix the biggest real causes first, and prove each fix with a before/after score.

## 1. Test data

| Set | Size | Use |
|---|---|---|
| Synthetic **dev** samples | about 35 | find problems, try fixes |
| Synthetic **held-out** samples | about 15 | measured once per frozen version, **never looked at while fixing** |
| Real transcripts | 5 (Koushik, Student C, Student D + 2) | final confirmation on real scans |

Every synthetic sample is built from an official curriculum (course titles, credits, semesters, totals as printed;
electives only from the listed options). Each spec records its source, how it was checked, the grading source
and anything omitted (`provenance`). Every image is marked SYNTHETIC TEST DOCUMENT, fictional student, no logo,
seal or signature.

Held-out rule: in every new batch of 10, 3 samples are marked `"split": "heldout"` **before** the batch is run
for the first time. The pilot (S01-S05) is dev.

## 2. Answer labels

- Course-map titles take the map's categories; all other courses are labelled by the taxonomy rules.
- A course whose content cannot be judged from its title gets `null` (unsure) and is not scored.
- Koushik labels a subset of about 10 samples **without seeing Claude's labels** (`labels_blind/`). Agreement
  between the two is reported; disagreements are settled with the syllabus. This measures the label quality itself.

## 3. Targets (fixed now; a version passes only if it meets all on the held-out set)

| # | Measure | Target |
|---|---|---|
| T1 | Wrong verdicts caused by reading or classification | **0** |
| T2 | CGPA, years studied, lateral entry read correctly | 100 % |
| T3 | Courses found on the memo | ≥ 99 % |
| T4 | Courses with wrong credits | ≤ 1 per memo |
| T5 | Wrong classification (sure but different from the label) | ≤ 2 % of scored courses |
| T6 | Not counted (unsure, no syllabus) | ≤ 8 % of scored courses |

Cost (AI calls, tokens, time per student) is reported, not targeted.

## 4. Versions

Every scored run records the git commit and the fingerprints of the taxonomy files, the course map and the engine
config. The report groups results by version, so every change shows its before/after effect. A change is kept
only if it improves the dev score without making any held-out measure worse.

## 5. What the log answers

Reading (by layout and university), classification by category, accuracy by answer source (course map /
knowledge base / AI / lab rule), courses the AI cannot place (taxonomy or map gaps), how titles vary between
universities, which errors change a verdict, and cost per student.
