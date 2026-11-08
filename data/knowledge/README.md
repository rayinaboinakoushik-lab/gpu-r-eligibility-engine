# Knowledge-base seed (05.11.2026, extended the same day)

`kb_seed.json` is the starting knowledge base of the web API (`api/main.py` copies it in when the server has none).
It holds **only confirmed** saved answers from the local knowledge base (course title -> categories, AI reasoning;
no names, grades or other personal data):

| Confirmed by | Entries |
|---|---|
| same categories as the evaluation answer labels | 525 |
| shortened memo titles matched to their full title's label | 31 |
| projects, following taxonomy rule 2 (no category; CS: thesis_scientific_work) | 20 |
| syllabus / approved-map review 05.11.2026 (23 as answered, 7 corrected) | 30 |
| **total** | **606** |

Review of 05.11.2026 (Koushik approved; evidence in the review log): 23 answers confirmed as saved; 7 corrected
(Antennas & Microwave Engineering + communications; Pulse & Digital Circuits and PDC Lab electronics only; Applied
Mechanics Lab mechanics only; Statistical Signal Analysis statistics only; Matrix Computation linear algebra +
numerics; Digital Image & Video Processing DSP only). Their reasoning starts with "Reviewed 05.11.2026".

Left out (they stay in the local knowledge base only, or are asked as a syllabus): Material Testing Laboratory
(civil), Metrology & QC + Lab, Materials Handling, Water Supply and Plumbing, Computer Aided Design and Drafting
(civil), and the numerical-methods labs (open rule question: the lab rule gives them their maths theory course's
categories, the taxonomy text says maths labs count as programming practice). Each addition is a reviewed change
to this file.
