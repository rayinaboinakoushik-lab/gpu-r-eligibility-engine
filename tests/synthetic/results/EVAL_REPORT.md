# GPU-R evaluation report

Generated 04.11.2026 01:47 from 36 logged runs. Current version: `0bfa252-8b65b0-c846da-c6f7f8`. Plan and targets: `tests/synthetic/EVAL_PLAN.md`.

## Targets — heldout set (1 samples, current version)

| Target | Result | Met |
|---|---|---|
| T1 wrong verdicts | 0 in 1 samples | yes |
| T2 CGPA, years, lateral entry | 1/1 memos exact | yes |
| T3 courses found | 47/47 (100.0 %) | yes |
| T4 credit errors per memo | max 0 | yes |
| T5 wrong classification | 1/42 (2.4 %) | **no** |
| T6 not counted | 0/42 (0.0 %) | yes |

## Targets — dev set (2 samples, current version)

| Target | Result | Met |
|---|---|---|
| T1 wrong verdicts | 0 in 2 samples | yes |
| T2 CGPA, years, lateral entry | 2/2 memos exact | yes |
| T3 courses found | 135/135 (100.0 %) | yes |
| T4 credit errors per memo | max 0 | yes |
| T5 wrong classification | 0/103 (0.0 %) | yes |
| T6 not counted | 1/103 (1.0 %) | yes |

## Samples (current version)

| Sample | University | Field | Layout | Courses found | Credit errors | Correct | Wrong | Not counted | Unsure label | Verdicts same | AI calls | Tokens in/out |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S07_makaut_heritage_mech_lateral | Maulana Abul Kalam Azad University of Technology, West Bengal | mechanical | two_column (abbrev.) | 47/47 | 0 | 41 | 1 | 0 | 5 | 21/21 | 2 | 16438/3683 |
| S12_makaut_narula_civil | Maulana Abul Kalam Azad University of Technology, West Bengal | civil | table | 87/87 | 0 | 58 | 0 | 0 | 29 | 16/16 | 2 | 18063/3844 |
| S18_makaut_it | Maulana Abul Kalam Azad University of Technology, West Bengal | cs | two_column (abbrev.) | 48/48 | 0 | 44 | 0 | 1 | 3 | 103/103 | 2 | 15077/3391 |

## Reading by layout

| Layout | Memos | Courses found | Missing | Extra | Credit errors |
|---|---|---|---|---|---|
| two_column abbrev. | 2 | 95/95 | 0 | 0 | 0 |
| table | 1 | 87/87 | 0 | 0 | 0 |

## Classification by category (where to improve the taxonomy)

missed = the label has it, the answer not; extra = the answer has it, the label not.

| Category | Correct | Missed | Extra | Not counted | Error share |
|---|---|---|---|---|---|
| physics_natural_sciences.general_physics | 9 | 0 | 1 | 0 | 10.0 % |
| computer_science_informatics.programming_practical_cs | 7 | 0 | 0 | 1 | 12.5 % |
| mechanical_manufacturing_engineering.manufacturing_production | 4 | 0 | 0 | 0 | 0.0 % |
| mechanical_manufacturing_engineering.mechanics_dynamics | 11 | 0 | 0 | 0 | 0.0 % |
| mechanical_manufacturing_engineering.thermodynamics | 7 | 0 | 0 | 0 | 0.0 % |
| (no category) | 27 | 0 | 0 | 0 | 0.0 % |
| business_economics_management.business_administration | 8 | 0 | 0 | 0 | 0.0 % |
| chemistry_materials.materials_science | 4 | 0 | 0 | 0 | 0.0 % |
| mechanical_manufacturing_engineering.mechanics_fluid_dynamics | 5 | 0 | 0 | 0 | 0.0 % |
| mechanical_manufacturing_engineering.design_machine_elements | 5 | 0 | 0 | 0 | 0.0 % |
| electrical_electronic_engineering.circuit_theory | 4 | 0 | 0 | 0 | 0.0 % |
| electrical_electronic_engineering.electronics | 2 | 0 | 0 | 0 | 0.0 % |
| civil_engineering.construction_management | 3 | 0 | 0 | 0 | 0.0 % |
| physics_natural_sciences.chemistry | 4 | 0 | 0 | 0 | 0.0 % |
| electrical_electronic_engineering.measurement_instrumentation | 2 | 0 | 0 | 0 | 0.0 % |
| civil_engineering.geotechnics | 6 | 0 | 0 | 0 | 0.0 % |
| civil_engineering.structural_mechanics | 4 | 0 | 0 | 0 | 0.0 % |
| civil_engineering.environmental_engineering | 2 | 0 | 0 | 0 | 0.0 % |
| mathematics_statistics.optimization_numerics | 4 | 0 | 0 | 0 | 0.0 % |
| mathematics_statistics.calculus_analysis | 3 | 0 | 0 | 0 | 0.0 % |
| civil_engineering.transportation_engineering | 4 | 0 | 0 | 0 | 0.0 % |
| civil_engineering.surveying_geodesy | 4 | 0 | 0 | 0 | 0.0 % |
| civil_engineering.structural_engineering | 4 | 0 | 0 | 0 | 0.0 % |
| civil_engineering.water_engineering | 1 | 0 | 0 | 0 | 0.0 % |
| electrical_electronic_engineering.communications | 1 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.graphics_visual_computing | 1 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.computer_engineering | 4 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.computer_networks | 1 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.algorithms_data_structures | 2 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.databases_systems | 1 | 0 | 0 | 0 | 0.0 % |
| electrical_electronic_engineering.digital_systems | 1 | 0 | 0 | 0 | 0.0 % |
| electrical_electronic_engineering.digital_signal_processing | 1 | 0 | 0 | 0 | 0.0 % |
| mathematics_statistics.discrete_math_logic | 1 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.theoretical_cs | 1 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.it_security | 1 | 0 | 0 | 0 | 0.0 % |
| electrical_electronic_engineering.information_theory | 1 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.machine_learning_ai | 1 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.operating_systems | 1 | 0 | 0 | 0 | 0.0 % |
| other.thesis_scientific_work | 3 | 0 | 0 | 0 | 0.0 % |
| engineering.robotics | 1 | 0 | 0 | 0 | 0.0 % |
| electrical_electronic_engineering.signals_systems | 1 | 0 | 0 | 0 | 0.0 % |
| computer_science_informatics.software_engineering | 1 | 0 | 0 | 0 | 0.0 % |

## Accuracy by answer source (how the course map, knowledge base, AI and lab rule perform)

| Source | Courses | Correct | Wrong | Not counted |
|---|---|---|---|---|
| kb | 88 | 87 (98.9 %) | 1 | 0 |
| lab_rule | 16 | 16 (100.0 %) | 0 | 0 |
| llm | 3 | 2 (66.7 %) | 0 | 1 |
| map | 38 | 38 (100.0 %) | 0 | 0 |

## Course-map coverage by university (how much each university's titles differ from the map)

| Sample | University | Titles known to the map | New titles |
|---|---|---|---|
| S07_makaut_heritage_mech_lateral | Maulana Abul Kalam Azad University of Technology, West Bengal | 9/47 (19.1 %) | 38 |
| S12_makaut_narula_civil | Maulana Abul Kalam Azad University of Technology, West Bengal | 16/87 (18.4 %) | 71 |
| S18_makaut_it | Maulana Abul Kalam Azad University of Technology, West Bengal | 16/48 (33.3 %) | 32 |

## Same subject, different titles (candidates for course-map entries)

| Label | Distinct titles | Examples |
|---|---|---|
| mechanics_dynamics | 7 | Applied Mechanics Lab; Dynamics of Machines; Dynamics of Machines Lab; Finite Element Method; Finite Element Method Lab |
| business_administration | 7 | Economics For Engineers; Economics for Engineers; Industrial Engineering; Introduction to Industrial Management (Humanities III); Management 1 (Organizational Behaviour) |
| general_physics | 7 | Physics - I; Physics - II; Physics – II; Physics-I; Physics-I Lab |
| programming_practical_cs | 7 | Advanced Programming for Problem solving; IT Workshop (Sci Lab/R); Internet & Web Technology; Object Oriented Programming with Python; Programming for Problem Solving |
| geotechnics | 6 | Engineering Geology; Engineering Geology Lab; Foundation Engineering; Soil Mechanics; Soil Mechanics Lab-I |
| thermodynamics | 5 | Applied Thermodynamics & Heat Transfer Lab; Engineering Thermodynamics; Heat Transfer; Refrigeration & Air Conditioning; Refrigeration & Air Conditioning Lab |
| design_machine_elements | 5 | Engineering Graphics & Design; Machine Design- II; Machine Design-I; Machine Drawing-I; Machine Drawing-II |
| manufacturing_production | 4 | Advanced Manufacturing Lab; Machining & Machine Tools; Machining & Machine Tools Lab; Manufacturing Processes |
| transportation_engineering | 4 | Pavement Design; Traffic Engineering & Planning; Transportation Engineering; Transportation and Highway Engineering Lab |
| surveying_geodesy | 4 | Remote Sensing & GIS; Remote Sensing And GIS; Surveying; Surveying Practice |
| materials_science | 3 | Concrete Lab; Concrete Technology; Engineering Materials |
| mechanics_fluid_dynamics | 3 | Fluid Machinery; Fluid Mechanics & Hydraulic Machines Lab; Fluid Mechanics & Hydraulics |
| circuit_theory | 3 | Basic Electrical Engineering; Basic Electrical Engineering Lab; Basic Electrical Engineering Laboratory |
| chemistry | 3 | Chemistry I Lab; Chemistry-I; Chemistry-I Laboratory |
| structural_engineering | 3 | Structural Design – II; Structural Design-I; Structural Dynamics and Earthquake Engineering |
| thesis_scientific_work | 3 | Project-1; Project-II; Project-III |
| mechanics_fluid_dynamics, thermodynamics | 2 | Gas Dynamics and Jet Propulsion; Turbo Machinery |
| electronics | 2 | Basic Electronics Engineering; Basic Electronics Engineering Lab |
| construction_management | 2 | Construction Planning And Management; Quantity Surveying, Specifications and Valuation |
| measurement_instrumentation | 2 | Electrical And Electronics Measurement; Electrical and Electronic Measurement Laboratory |

## Not counted (AI unsure, no syllabus) — taxonomy or map gaps

- S18_makaut_it: **IT WORKSHOP (SCI LAB/R)** (label: programming_practical_cs; source llm)

## Wrong answers (sure, but different from the label)

- S07_makaut_heritage_mech_lateral: **APPLIED MECHANICS LAB** — label [mechanics_dynamics], answer [mechanics_dynamics, general_physics], source kb

## Verdict differences (pipeline vs. true values and labels)

Neutral check: courses with an unsure label take the pipeline's own answer on the true side, and route answers are copied, so every difference comes from a reading or classification error.

- none

## Before / after by version

| Version | Samples | Correct | Wrong | Not counted | Courses found | Verdict differences |
|---|---|---|---|---|---|---|
| `9ab5fe1-a65a09-213efc-c6f7f8` | 5 | 94.6 % | 1.8 % | 3.6 % | 100.0 % | 4 |
| `8fb0aa0-a65a09-213efc-c6f7f8` | 4 | 96.3 % | 1.4 % | 2.3 % | 100.0 % | 4 |
| `a245792-a65a09-d1a7c5-c6f7f8` | 1 | 94.1 % | 2.0 % | 3.9 % | 100.0 % | 0 |
| `b4bb757-a65a09-d1a7c5-c6f7f8` | 13 | 93.0 % | 1.9 % | 5.2 % | 100.0 % | 10 |
| `0bfa252-8b65b0-c846da-c6f7f8` | 3 | 98.6 % | 0.7 % | 0.7 % | 100.0 % | 0 |
