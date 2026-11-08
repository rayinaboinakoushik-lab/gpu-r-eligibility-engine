"""
Verifies Step 1 (file_intake.py) actually works before anything downstream
depends on it -- same discipline as verify_grade_field.py earlier: run it,
look at the real output, don't assume.

Fill in n_max/n_min with YOUR actual confirmed grading-scale values once you
know them (JNTUH's real minimum passing CGPA) -- these are placeholders
until then, same as agreed: never silently trusted, always visible.

Run in the same folder as your other scripts:
    python.exe run_step1_test.py
"""

from file_intake import build_student_intake

TRANSCRIPT_PATH = r"C:\Users\koush\Downloads\KOUSHIK.jpeg"  # adjust if needed

# Placeholder until JNTUH's real minimum passing CGPA is confirmed --
# do not trust this value for a real decision yet.
N_MAX = 10.0
N_MIN = 4.0
SCALE_DESCRIPTION = "10-point CGPA, JNTUH (Nmin unconfirmed -- placeholder)"

DOMAIN = "cs"


def main():
    intake = build_student_intake(
        transcript_path_or_bytes=TRANSCRIPT_PATH,
        domain=DOMAIN,
        n_max=N_MAX,
        n_min=N_MIN,
        scale_description=SCALE_DESCRIPTION,
    )

    print("=== STEP 1 INTAKE RESULT ===")
    print("Transcript readable :", intake.transcript.readable)
    print("Transcript file kind:", intake.transcript.file_kind)
    print("Transcript mime type:", intake.transcript.mime_type)
    print("Transcript size     :", intake.transcript.size_bytes, "bytes")
    print("Domain              :", intake.domain)
    print("Grade scale         : Nmax =", intake.grade_scale.n_max,
          ", Nmin =", intake.grade_scale.n_min)
    print("Scale description   :", intake.grade_scale.scale_description)
    print("Ready for Step 2?   :", intake.ready_for_step2)

    if intake.warnings:
        print("\n=== WARNINGS ===")
        for w in intake.warnings:
            print("-", w)
    else:
        print("\nNo warnings.")


if __name__ == "__main__":
    main()
