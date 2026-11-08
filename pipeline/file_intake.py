"""
Step 1 of the GPU-R pipeline: transcript upload + upfront student inputs.

Per the agreed, ordered plan:
  Step 1 (this file): transcript upload (system extracts courses/CGPA/field
          automatically downstream) + student provides domain and grading-
          scale bounds (Nmax/Nmin) up front.
  Step 2: classification (separate file/step -- not here)
  Step 3: student verification loop, excerpt PDF upload (separate, later --
          NOT part of this file; the full regulations document is never
          uploaded here at all, only a small excerpt, later, conditionally)
  Step 4: resolve + merge (separate step)
  Step 5: final profile assembly (separate step)

This file deliberately does NOT ask for or accept a regulations document.
That was the old design (TwoFileInput) and it's been retired -- the
regulations document, if it exists at all, stays entirely on the student's
own side and is never an input to this system. Only a small excerpt PDF
enters later, in Step 3, via a separate intake call.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal
import struct


DomainChoice = Literal["cs", "civil", "mechanical", "eee"]

# This is a CONTROLLED SELECTION, not a validation of the student's literal
# field name -- that distinction matters and was missed in an earlier pass.
#
# The system currently has exactly 4 domain data files (one course-
# classification taxonomy + one program-requirements database each, in
# principle -- only "cs" actually has both built right now). The student
# does NOT type their own field freely here. They pick the ONE closest
# match from this fixed list, and that single choice scopes the ENTIRE run:
#   - which taxonomy classifies their courses
#   - which program-requirements database the matching engine searches
# A Cyber Security or IT student picks "cs" -> everything downstream runs
# inside the CS file, and ONLY the CS file -- never civil, mechanical, or
# eee, no matter how the student's actual transcript program is titled.
# This is what makes the "never match IT against Mechanical" rule real: it
# isn't enforced by trying to compare field names for similarity, it's
# enforced by the student only ever being able to select one of these 4
# fixed, isolated scopes to begin with.
#
# DOMAIN_OPTIONS is the single source of truth for this list: the order and
# human-readable labels shown to the student. The console test tool renders
# it as a numbered menu today; the frontend will render the same list as a
# dropdown later -- neither should keep its own copy.
DOMAIN_OPTIONS = [
    ("cs", "Computer Science / Information Technology (incl. related: Cyber Security, Data Science, AI & ML, ...)"),
    ("eee", "Electrical / Electronics Engineering (incl. ECE, EEE, EE, ...)"),
    ("mechanical", "Mechanical Engineering (incl. Production, Automobile, Industrial, ...)"),
    ("civil", "Civil Engineering (incl. Structural, Transportation, Construction, ...)"),
]
VALID_DOMAINS = {key for key, _ in DOMAIN_OPTIONS}


# ---------------------------------------------------------------------------
# File type detection (magic bytes, not filename) -- unchanged from before,
# still correct and still needed regardless of the redesign above.
# ---------------------------------------------------------------------------

PDF_HEADER_SEARCH_LIMIT = 1024  # the PDF standard allows the "%PDF" header anywhere in the first 1024 bytes


def find_pdf_start(file_bytes: bytes) -> int:
    """Offset of the "%PDF" header, or -1. Some university portals add junk bytes before it."""
    return file_bytes.find(b"%PDF", 0, PDF_HEADER_SEARCH_LIMIT)


def detect_file_kind(file_bytes: bytes) -> str:
    if find_pdf_start(file_bytes) >= 0:
        return "pdf"
    if file_bytes.startswith(b"\xff\xd8\xff"):
        return "image"  # JPEG
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"  # PNG
    return "unknown"


def describe_unsupported(file_bytes: bytes) -> str:
    """Plain-language guess at what an unsupported file really is, so the student knows what to do."""
    head = file_bytes[:64]
    lower = head.lower()
    if not file_bytes:
        return "The file is empty (0 bytes) -- the download or copy probably failed."
    if lower.lstrip().startswith((b"<!doctype", b"<html", b"<?xml")):
        return ("The file is actually a web page (HTML), not a PDF -- usually a failed or expired download. "
                "Download the memo again from the university portal.")
    if head.startswith(b"PK\x03\x04"):
        return ("The file is a Word/Office document or a ZIP archive, not a PDF. "
                "Open it and save or export it as PDF, then try again.")
    if head[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        return ("The file is an iPhone photo (HEIC). Convert it to JPG or PDF "
                "(or set the camera to 'Most Compatible') and try again.")
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "The file is a WEBP image. Convert it to JPG, PNG or PDF and try again."
    if head.startswith((b"GIF87a", b"GIF89a", b"BM", b"II*\x00", b"MM\x00*")):
        return "The file is a GIF/BMP/TIFF image. Convert it to JPG, PNG or PDF and try again."
    return ("The file is not a PDF, JPG or PNG, whatever its name says. Open it to check it is the "
            "marks memo, then save it as PDF, JPG or PNG and try again.")


@dataclass
class PreparedFile:
    original_path: Optional[str]
    file_kind: str
    mime_type: str
    size_bytes: int
    base64_data: str
    readable: bool
    error: Optional[str] = None


def _mime_for_kind(file_kind: str, file_bytes: bytes) -> str:
    if file_kind == "pdf":
        return "application/pdf"
    if file_kind == "image":
        if file_bytes.startswith(b"\x89PNG"):
            return "image/png"
        return "image/jpeg"
    return "application/octet-stream"


def prepare_uploaded_bytes(file_bytes: bytes, filename: Optional[str] = None) -> PreparedFile:
    import base64
    kind = detect_file_kind(file_bytes)
    if kind == "unknown":
        return PreparedFile(
            original_path=filename, file_kind=kind, mime_type="application/octet-stream",
            size_bytes=len(file_bytes), base64_data="", readable=False,
            error=describe_unsupported(file_bytes),
        )
    if kind == "pdf":
        # Drop any junk bytes before "%PDF" so the LLM receives a clean PDF.
        file_bytes = file_bytes[find_pdf_start(file_bytes):]
    return PreparedFile(
        original_path=filename, file_kind=kind, mime_type=_mime_for_kind(kind, file_bytes),
        size_bytes=len(file_bytes), base64_data=base64.b64encode(file_bytes).decode("ascii"),
        readable=True,
    )


def prepare_file(path: str) -> PreparedFile:
    try:
        with open(path, "rb") as f:
            file_bytes = f.read()
    except OSError as e:
        return PreparedFile(
            original_path=path, file_kind="unknown", mime_type="application/octet-stream",
            size_bytes=0, base64_data="", readable=False, error=str(e)
        )
    return prepare_uploaded_bytes(file_bytes, filename=path)


# ---------------------------------------------------------------------------
# Step 1 -- the actual intake bundle: transcript + domain + grade-scale bounds
# ---------------------------------------------------------------------------

@dataclass
class GradeScaleInput:
    """
    Student-provided grading-scale bounds for the Modified Bavarian Formula.
    Never defaulted silently -- the student must state these, because they
    vary by institution and materially change the resulting German grade.
    """
    n_max: float          # best possible result on the student's own scale
    n_min: float          # MINIMUM PASSING grade on that scale (not the floor)
    scale_description: str  # e.g. "10-point CGPA, JNTUH" -- for audit/explainability


@dataclass
class StudentIntake:
    transcript: PreparedFile
    domain: DomainChoice
    grade_scale: GradeScaleInput
    warnings: list = field(default_factory=list)

    @property
    def ready_for_step2(self) -> bool:
        # Domain confirmation now happens AFTER extraction (see
        # run_stage_1_to_3.py), once we know the student's real detected
        # program -- so it is no longer required at this earlier gate.
        return self.transcript.readable


def build_student_intake(transcript_path_or_bytes, domain: str, n_max: float, n_min: float,
                          scale_description: str, filename: Optional[str] = None) -> StudentIntake:
    """
    The single Step-1 entry point. Takes:
      - the transcript (a local path for testing, or raw bytes for a real
        web upload -- both accepted, matching the existing dual-entry-point
        design)
      - domain: student-selected, one of "cs", "civil", "mechanical", "eee"
      - n_max / n_min: student-provided grading-scale bounds
      - scale_description: a short human label for what scale this is,
        kept for the final profile's audit trail

    Deliberately does NOT accept or ask for a regulations document -- see
    module docstring.
    """
    warnings = []

    if isinstance(transcript_path_or_bytes, (bytes, bytearray)):
        transcript = prepare_uploaded_bytes(bytes(transcript_path_or_bytes), filename=filename)
    else:
        transcript = prepare_file(transcript_path_or_bytes)

    if not transcript.readable:
        warnings.append(f"Transcript could not be read: {transcript.error}")

    domain_normalized = domain.strip().lower()
    # Empty domain is allowed to pass through here silently -- this function
    # is also called once early (Step 1) BEFORE extraction, with domain
    # deliberately left blank until the real confirmation step runs after
    # extraction (see run_stage_1_to_3.py). The actual selection is
    # validated against VALID_DOMAINS at that later, real confirmation
    # point -- not here.
    if domain_normalized and domain_normalized not in VALID_DOMAINS:
        warnings.append(
            f"'{domain}' is not one of the supported fields {sorted(VALID_DOMAINS)}. "
            f"The student must pick the ONE closest match from this fixed list -- "
            f"classification and matching run only inside that single field's data, "
            f"never a mix of fields."
        )

    if n_max <= n_min:
        warnings.append(
            f"n_max ({n_max}) must be greater than n_min ({n_min}) -- "
            f"the Modified Bavarian Formula cannot be computed otherwise."
        )

    grade_scale = GradeScaleInput(n_max=n_max, n_min=n_min, scale_description=scale_description)

    return StudentIntake(
        transcript=transcript,
        domain=domain_normalized,  # type: ignore[arg-type]
        grade_scale=grade_scale,
        warnings=warnings,
    )


if __name__ == "__main__":
    print("Step 1 intake module loaded.")
    print("Call build_student_intake(transcript, domain, n_max, n_min, scale_description).")
