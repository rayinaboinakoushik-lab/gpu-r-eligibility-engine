# Rules vs RAG: disagreements to review by hand

Fill in the last column: AI error / engine-or-record error / ambiguous.

| # | Student | Programme | Engine notes | Rules | Variant | LLM | LLM reason | Verdict |
|---|---|---|---|---|---|---|---|---|
| 1 | test_cs | Computer Science (University of Siegen) | no | 3 | rag | 2 | The degree counts as computer science, no hard grade limit is specified, and the applicant meets the 18-ECTS specialization requirement, with an online test and interview following eligibility assessment. | |
| 2 | test_mechanical | Battery and Hydrogen Technology (M.Sc.) (Technische Universität Braunschweig) | no | 1 | rag | 2 | The mechanical engineering degree and all listed subject requirements are satisfied, no grade threshold applies, and grade-based ranking follows if applications exceed available places. | |
| 3 | test_eee | Mechatronics (M.Sc.) (University of Siegen) | no | 3 | rag | 2 | The applicant’s electrical engineering background meets the stated requirements, including 21 ECTS against the 10-ECTS subject minimum, and a selection step follows. | |
| 4 | test_eee | Master of Science in Computer Engineering (Paderborn University) | no | 3 | rag | 4 | The applicant's electrical_electronic_engineering bachelor's field is not in the accepted bachelor fields list, which contains only computer_science. | |
| 5 | test_eee | Systems Engineering (Saarland University) | no | 1 | rag | 3 | The electrical engineering degree and grade of 2.2 satisfy route 9723_A, but the engine notes identify a one-module gap that may be completed under conditions and does not count against the maximum bridging ECTS. | |
| 6 | test_civil | Air Transport and Logistics (M.Sc.) (Technische Universität Dresden) | no | 4 | rag | 2 | The civil engineering degree is accepted, the applicant meets the 40-ECTS combined requirement with 51 ECTS and the 20-ECTS mathematics requirement with 21 ECTS, and no grade threshold applies, but an aptitude test and potentially an interview follow. | |
| 7 | test_cs | High Integrity Systems (M.Sc.) (Frankfurt University of Applied Sciences) | no | 2 | oracle | 4 | The 2.5 grade exceeds the direct route’s 1.8 limit, and the alternative route requires evidence of a special qualification not shown in the applicant profile. | |
| 8 | test_cs | High Integrity Systems (M.Sc.) (Frankfurt University of Applied Sciences) | no | 2 | rag | 4 | The 2.5 grade exceeds the direct-route limit of 1.8, and the alternative route requires evidence of special qualifications not shown in the applicant profile. | |
| 9 | test_cs | Computer Science (University of Regensburg) | no | 3 | rag | 2 | The degree counts as computer science, the 2.5 grade meets the stated limit, and qualifying credits exceed 78 ECTS, but the applicant must proceed through the aptitude selection procedure. | |
