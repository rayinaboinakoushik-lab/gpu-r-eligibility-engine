"""
Runs synthetic test samples through the REAL pipeline without typing (02.11.2026).

    py tools/run_batch.py                       all samples not yet scored on the current version
    py tools/run_batch.py S01_vtu_git_cse S02   only these (prefix match)
    py tools/run_batch.py --force               run again even if already scored on this version

The product is NOT changed: this runner executes the normal scripts (run_stage_1_to_3.py, run_stage_4_to_5.py,
run_eligibility.py) exactly as a student would, and only answers their questions -- like a careful student
holding the memo:
  * path, Nmax, Nmin, field, degree: from the sample spec
  * check screen: corrects only the key values (CGPA, entry type, years, credits registered, credits for award)
    when they differ from the memo, and fills required values that were not found -- every correction is LOGGED
    as a reading error; course titles and credits are never touched
  * syllabus excerpt: skipped (Enter), so 'not counted' stays visible
  * GATE and route questions: skip / "n" (fictional students have no evidence)
  * any question it does not recognise: it STOPS, it never guesses
Then it scores the run (log record) and at the end writes the report.
"""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import re
import runpy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PIPE = REPO / "pipeline"
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(PIPE))
sys.path.insert(0, str(REPO))

import synthetic_transcripts as ST  # noqa: E402


class UnknownQuestion(RuntimeError):
    pass


class Tee(io.TextIOBase):
    """Keeps everything the scripts print (for parsing and the run log) and echoes a short progress line."""
    def __init__(self, echo):
        self.buf, self.echo = [], echo

    def write(self, s):
        self.buf.append(s)
        return len(s)

    def text(self):
        return "".join(self.buf)


def _key_values(screen: str) -> dict:
    """Values shown on the latest check screen: {field number: shown text}."""
    last = screen.rfind("=== Please check what was read")
    vals = {}
    for m in re.finditer(r"^\s{2}(\d)\. [^:]+: (.*)$", screen[last:], re.M):
        vals[int(m.group(1))] = m.group(2).strip()
    return vals


class Student:
    """Answers the pipeline's questions for one sample, from its spec and truth."""
    FIELD_NO = {"cgpa": 5, "entry": 6, "years": 7, "registered": 8, "award": 9}

    def __init__(self, spec: dict, truth: dict, image: Path, tee: Tee):
        ex = truth["extraction"]
        self.spec, self.tee, self.image = spec, tee, image
        award = ex["credits_for_award_printed"] or ex["credits_registered"]
        self.want = {5: ex["cgpa"], 6: ex["entry_type"], 7: ex["years_studied"], 8: ex["credits_registered"], 9: award}
        self.pending = None            # field number we chose to correct, waiting for "New value"
        self.corrections = []
        self.session = None

    def _wrong_fields(self):
        shown = _key_values(self.tee.text())
        wrong = []
        for no, want in self.want.items():
            got = shown.get(no, "")
            if no == 6:
                ok = got == want
            else:
                try:
                    ok = abs(float(got) - float(want)) < 1e-6
                except ValueError:
                    ok = False
            if not ok and not any(c["field"] == no for c in self.corrections):
                wrong.append((no, got))
        return wrong

    def answer(self, prompt: str = "") -> str:
        p = prompt.strip()
        if p.startswith("Path to your transcript"):
            return str(self.image)
        if "(Nmax)" in p:
            return str(self.spec["grading"][0][1])
        if "(Nmin)" in p:
            return str(self.spec["pass_min"])
        if p.startswith("Short description of your grading scale"):
            return ""
        if p.startswith('Type "fine"'):
            wrong = self._wrong_fields()
            if wrong:
                no, got = wrong[0]
                self.pending = no
                self.corrections.append({"field": no, "shown": got, "corrected_to": self.want[no]})
                return str(no)
            return "fine"
        if p.startswith("New value for") and self.pending:
            v = self.want[self.pending]
            self.pending = None
            return str(v)
        if p.startswith("Enter a number (1-"):
            from file_intake import DOMAIN_OPTIONS
            return str([d for d, _ in DOMAIN_OPTIONS].index(self.spec["field"]) + 1)
        if p.startswith("Your GATE score"):
            return ""
        if p.startswith("Session ID"):
            return self.session
        if p.startswith("Path to your syllabus excerpt"):
            return ""
        if p.startswith("Pick your degree"):
            from gpur import profile as prof
            ids = list(prof.load_degree_fields())
            return str(ids.index(self.spec["degree_field_id"]) + 1)
        if p.endswith("(y/n)"):
            return "n"
        raise UnknownQuestion(f"unrecognised question, stopping instead of guessing: {p!r}")


def run_script(script: str, argv: list, student: Student, tee: Tee):
    import os
    os.environ["GPUR_EVAL_RUN"] = "1"      # 07.11.2026: evaluation runs are counted in eval_log, not in the run ledger
    from llm_utils import reset_usage
    reset_usage()
    old_input, old_argv = builtins.input, sys.argv
    builtins.input = student.answer
    sys.argv = [str(PIPE / script)] + argv
    try:
        with contextlib.redirect_stdout(tee):
            try:
                runpy.run_path(str(PIPE / script), run_name="__main__")
            except SystemExit as e:
                if e.code not in (0, None):
                    raise
    finally:
        builtins.input, sys.argv = old_input, old_argv


def already_scored(sid: str) -> bool:
    from eval_log import load_log, version_info
    ver = version_info("cs")["version"]
    return any(r["sample"] == sid and r["version"]["version"] == ver for r in load_log())


def run_sample(sid: str) -> dict:
    spec = json.loads((ST.SPECS / f"{sid}.json").read_text(encoding="utf-8"))
    if not (ST.OUT / f"{sid}_truth.json").exists():
        ST.make([sid])
    truth = json.loads((ST.OUT / f"{sid}_truth.json").read_text(encoding="utf-8"))
    tee = Tee(sys.stdout)
    st = Student(spec, truth, ST.OUT / f"{sid}.jpg", tee)
    log_path = ST.OUT / f"{sid}_run.log"
    try:
        print(f"[{sid}] stage 1-3 (reading + classification) ...", flush=True)
        run_script("run_stage_1_to_3.py", [], st, tee)
        m = re.search(r"checkpoint_(run_[0-9a-f]+)\.json", tee.text())
        if not m:
            raise RuntimeError("stage 1-3 did not save a checkpoint (see the run log)")
        st.session = m.group(1)
        print(f"[{sid}] stage 4-5 (profile, syllabus skipped) ...", flush=True)
        run_script("run_stage_4_to_5.py", [], st, tee)
        print(f"[{sid}] eligibility ...", flush=True)
        run_script("run_eligibility.py", [f"final_matching_profile_{st.session}.json"], st, tee)
    finally:
        log_path.write_text(tee.text(), encoding="utf-8")
    (ST.OUT / f"{sid}_corrections.json").write_text(json.dumps(st.corrections, indent=1), encoding="utf-8")
    print(f"[{sid}] scoring ...", flush=True)
    ST.main(["score", sid, st.session])
    return {"sample": sid, "session": st.session, "corrections": st.corrections}


def main(argv: list) -> int:
    force = "--force" in argv
    wanted = [a for a in argv if not a.startswith("--")]
    ids = sorted(p.stem for p in ST.SPECS.glob("*.json"))
    if wanted:
        ids = [i for i in ids if any(i.startswith(w) for w in wanted)]
    done, failed = [], []
    for sid in ids:
        if not force and already_scored(sid):
            print(f"[{sid}] already scored on this version -- skipped (use --force to run again)")
            continue
        try:
            done.append(run_sample(sid))
        except Exception as e:                      # one broken sample must not stop the batch
            failed.append((sid, f"{type(e).__name__}: {e}"))
            print(f"[{sid}] FAILED: {type(e).__name__}: {e}  (details: synthetic_out/{sid}_run.log)", flush=True)
    ST.main(["report"])
    print(f"\nBatch finished: {len(done)} scored, {len(failed)} failed, report in tests/synthetic/results/EVAL_REPORT.md")
    for sid, err in failed:
        print(f"   FAILED {sid}: {err}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
