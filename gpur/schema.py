"""
GPU-R record format v2 and student profile as typed Pydantic models (draft, 26.10.2026).

- Every frozen record must load into `Record` without error (CI checks this).
- Category names are NOT hard-coded here: `check_categories()` validates them against the
  taxonomy file in use, so the schema survives the taxonomy v3 rename unchanged.
- Key order (the v2 contract) is checked by scripts/validate_records.py, not by Pydantic.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

Semester = Literal["winter", "summer"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")      # an unknown key = an error (catches typos)
    # record flags use StrictBool: text such as "yes" is an error, never silently read as true (found 27.10.2026)


# ----------------------------------------------------------------------------- record parts
class AdmissionRegulation(Strict):
    url: Optional[str]
    title: str
    version: str


class OfficialSources(Strict):
    program_page: Optional[str]
    admission_regulation: AdmissionRegulation


class AcceptedDegreeFields(Strict):
    primary_fields: list[str] = Field(min_length=1)
    note: str = ""


class GradeRequirement(Strict):
    value: Optional[float] = Field(default=None, ge=1.0, le=4.0)   # German scale, lower is better
    note: str = ""


class SubjectItem(Strict):
    raw_label: str = Field(min_length=1)
    canonical_category: str
    covered_categories: list[str]
    min_ects: Optional[float] = Field(default=None, ge=0)
    requires_subject_presence_only: StrictBool

    @model_validator(mode="after")
    def ects_or_presence(self):
        if not self.requires_subject_presence_only and not self.min_ects:
            raise ValueError(f"item '{self.raw_label[:60]}' has no ECTS and is not presence-only")
        if self.canonical_category in self.covered_categories:
            raise ValueError(f"item '{self.raw_label[:60]}' repeats its main category in covered_categories")
        return self

    def categories(self) -> list[str]:
        return [self.canonical_category, *self.covered_categories]


class SubjectCreditRequirements(Strict):
    items: list[SubjectItem]
    note: str = ""


class ConditionalAdmission(Strict):
    allowed: StrictBool                       # never null (audit fix 24.10)
    max_ects: Optional[float] = Field(default=None, ge=0)
    mechanism: str = ""

    @model_validator(mode="after")
    def cap_only_if_allowed(self):
        if not self.allowed and self.max_ects:
            raise ValueError("max_ects set although conditions are not allowed")
        return self


class SelectionDisplay(Strict):
    has_subsequent_hurdles: StrictBool
    descriptive_notes: list[str]

    def important_notes(self) -> list[str]:
        return [n for n in self.descriptive_notes if n.startswith("IMPORTANT")]


class LanguageEnglish(Strict):
    ielts_min: Optional[float] = Field(default=None, ge=3.0, le=9.0)
    toefl_ibt_min: Optional[int] = Field(default=None, ge=30, le=120)
    pte_min: Optional[int] = Field(default=None, ge=10, le=90)
    required_level: Optional[str] = None
    allowed_exemptions: list[str] = []
    moi_not_accepted: Optional[StrictBool] = None
    due: Optional[str] = None
    note: Optional[str] = None

    @field_validator("ielts_min")
    @classmethod
    def half_band(cls, v):
        if v is not None and (v * 2) % 1:
            raise ValueError(f"IELTS {v} is not a half band")
        return v


class LanguageGerman(Strict):
    required: StrictBool
    required_level: Optional[str] = None
    due: Optional[str] = None


class StandardizedTest(Strict):
    test: str
    required_for: Optional[str] = None
    details: Optional[str] = None
    min_score: Optional[str | float] = None    # 2 older records use min_score/status
    status: Optional[str] = None


class ApsCertificate(Strict):
    required_for: list[str]
    note: str = ""


class PracticalExperience(Strict):
    required: StrictBool
    duration_years: Optional[float] = None
    duration_weeks: Optional[float] = None
    note: Optional[str] = None


class AdmissionType(Strict):
    restricted: Optional[StrictBool]
    numerus_clausus: Optional[StrictBool]


class NonEuDeadlines(Strict):
    winter: Optional[str]
    summer: Optional[str]


class Logistics(Strict):
    intake_semesters: list[Semester] = Field(min_length=1)
    non_eu_deadlines: NonEuDeadlines

    @model_validator(mode="after")
    def deadline_per_intake(self):
        for s in self.intake_semesters:
            if not getattr(self.non_eu_deadlines, s):
                raise ValueError(f"intake '{s}' has no non-EU deadline text")
        return self


class RegulationWatch(Strict):
    regulations_page: Optional[str]
    documents_seen: list[str]


# ----------------------------------------------------------------------------- the record
class Record(Strict):
    id: str
    program: str
    university: str
    domain: str = Field(alias="_domain")
    official_sources: OfficialSources
    accepted_degree_fields: AcceptedDegreeFields
    gpa_rule_type: Literal["HARD_MAX_GRADE", "NO_GRADE_THRESHOLD"]
    grade_requirement: GradeRequirement
    subject_credit_requirements: SubjectCreditRequirements
    conditional_admission: ConditionalAdmission
    subsequent_selection_criteria_display: SelectionDisplay
    minimum_total_ects: Optional[int] = Field(default=None, ge=90, le=300)
    language_english: LanguageEnglish
    language_german: LanguageGerman
    standardized_test_requirements: list[StandardizedTest]
    aps_certificate: Optional[ApsCertificate]
    practical_experience_requirement: Optional[PracticalExperience]
    final_scientific_work_requirement: Optional[StrictBool]
    other_requirements: list[str]
    admission_type: AdmissionType
    logistics: Logistics
    regulation_watch: RegulationWatch
    last_checked: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    last_updated: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def grade_rule_matches_value(self):
        v = self.grade_requirement.value
        if self.gpa_rule_type == "HARD_MAX_GRADE" and v is None:
            raise ValueError("HARD_MAX_GRADE without a grade value")
        if self.gpa_rule_type == "NO_GRADE_THRESHOLD" and v is not None:
            raise ValueError("NO_GRADE_THRESHOLD but a grade value is set")
        return self

    def categories(self) -> set[str]:
        return {c for it in self.subject_credit_requirements.items for c in it.categories()}


# ----------------------------------------------------------------------------- student profile
class Course(Strict):
    id: str
    title: str
    ects: float = Field(gt=0)
    categories: list[str] = []
    status: Optional[str] = None            # SUPPORTED_BY_TITLE / VERIFIED / ...


class Confirmations(BaseModel):
    model_config = ConfigDict(extra="allow")   # new gates can add flags
    gate_score: Optional[int] = None
    water_thesis: Optional[bool] = None
    module_average_confirmed: Optional[bool] = None
    subject_points_confirmed: Optional[bool] = None


class StudentProfile(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    field: Literal["cs", "eee", "mechanical", "civil"]
    degree_field: str
    degree_subfield: Optional[str] = None
    german_grade: float = Field(ge=1.0, le=5.0)
    total_ects: float = Field(gt=0)
    country: str = "India"
    courses: list[Course]
    confirmations: Confirmations = Confirmations()
    excluded_courses: list = []


# ----------------------------------------------------------------------------- helpers
def check_categories(records: list[Record], taxonomy: dict) -> dict[str, list[str]]:
    """Return {unknown_category: [record ids]} against a taxonomy file (atomic + pools)."""
    known = set(taxonomy.get("category_evidence_status", {}))
    known |= set(taxonomy.get("aggregate_categories", {})) | set(taxonomy.get("contextual_categories", {}))
    unknown: dict[str, list[str]] = {}
    for r in records:
        for c in r.categories():
            if c not in known:
                unknown.setdefault(c, []).append(r.id)
    return unknown
