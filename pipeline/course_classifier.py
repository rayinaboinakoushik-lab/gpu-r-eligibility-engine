"""
Course classification: assigns each extracted course to a category from our
real, frozen taxonomy of the student's chosen field -- using genuine semantic understanding
via the OpenAI API, not string matching.

UPDATED: now checks the verified knowledge base first (knowledge_base.py)
before spending any LLM call. Only genuinely new or ambiguous courses are
sent to the LLM. Verified, HIGH-confidence results (from title or from a
resolved student excerpt) are recorded back into the knowledge base so the
next student with an equivalent course never needs a fresh LLM call.

Requires: the same .env setup as transcript_extractor.py (OPENAI_API_KEY).
Requires: the chosen field's taxonomy file (cs / eee / mechanical / civil _taxonomy.json) in the same folder.
"""

import json
import re
from openai import OpenAI

from transcript_parser import ExtractedCourse
from file_intake import PreparedFile
from knowledge_base import KnowledgeBase, is_generic_math_title
from llm_utils import call_llm_json

CLASSIFY_BATCH_SIZE = 20
import base64
import io
from pypdf import PdfReader, PdfWriter


def find_relevant_section(regulations_file: PreparedFile, program_keyword: str,
                            page_padding: int = 20) -> tuple[int, int]:
    """
    (Unchanged from before -- kept for any local, free page-narrowing needs.
    Not part of the primary intake flow anymore, per the retired
    full-regulations-upload design; kept as a utility, not a required step.)
    """
    import subprocess
    import tempfile

    raw_bytes = base64.standard_b64decode(regulations_file.base64_data)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", tmp_path, "-"],
            capture_output=True, text=True, timeout=60
        )
        full_text = result.stdout
    finally:
        import os as _os
        _os.unlink(tmp_path)

    pages_text = full_text.split("\f")

    matching_pages = [
        i + 1 for i, page in enumerate(pages_text)
        if program_keyword.upper() in page.upper()
    ]

    if not matching_pages:
        raise ValueError(
            f"No section matching '{program_keyword}' found anywhere in the "
            f"regulations document via local text search."
        )

    start_page = max(1, min(matching_pages) - page_padding)
    end_page = max(matching_pages) + page_padding
    return (start_page, end_page)


def extract_pdf_page_range(regulations_file: PreparedFile, start_page: int, end_page: int) -> PreparedFile:
    raw_bytes = base64.standard_b64decode(regulations_file.base64_data)
    reader = PdfReader(io.BytesIO(raw_bytes))
    writer = PdfWriter()

    total_pages = len(reader.pages)
    start_idx = max(0, start_page - 1)
    end_idx = min(total_pages, end_page)

    for i in range(start_idx, end_idx):
        writer.add_page(reader.pages[i])

    output_buffer = io.BytesIO()
    writer.write(output_buffer)
    trimmed_bytes = output_buffer.getvalue()

    return PreparedFile(
        original_path=f"{regulations_file.original_path} (pages {start_page}-{end_page})",
        file_kind="pdf",
        mime_type="application/pdf",
        size_bytes=len(trimmed_bytes),
        base64_data=base64.standard_b64encode(trimmed_bytes).decode("utf-8"),
        readable=True,
        error=None
    )


def load_taxonomy(path: str = "cs_taxonomy.json") -> dict:
    # 27.10.2026: a bare name like "cs_taxonomy.json" is looked up in data/taxonomy/ of the repo
    from paths import taxonomy_path
    with open(taxonomy_path(path), encoding="utf-8") as f:
        return json.load(f)


_TITLE_PREFIX = re.compile(r"^(PE-\s*\w+|Professional Elective-\s*\w+|Open Elective-\s*\w+)\s*:\s*", re.IGNORECASE)
_TITLE_SUFFIX = re.compile(r"\s*\((PE|OE|PE/OE|SDC|skill dev|\+Lab)\)\s*$", re.IGNORECASE)


def clean_example_titles(titles: list) -> list:
    """
    Strips curriculum bookkeeping ("PE-3:", "Professional Elective-IV:", "(PE)",
    "(+Lab)", ...) from example titles and removes duplicates, so the prompt
    shows each real subject once instead of the same title in five spellings.
    """
    seen, out = set(), []
    for t in titles:
        cleaned = t.strip()
        for _ in range(2):
            cleaned = _TITLE_PREFIX.sub("", cleaned)
            cleaned = _TITLE_SUFFIX.sub("", cleaned).strip()
        key = re.sub(r"[^a-z0-9]", "", cleaned.lower())
        if key and key not in seen:
            seen.add(key)
            out.append(cleaned)
    return out


def build_classification_prompt(taxonomy: dict) -> str:
    """
    Builds the system prompt dynamically from the real taxonomy file.
    Classifies into every category from the field's frozen category list that
    genuinely fits -- a flat list, no primary/secondary ranking. Genuine
    multi-category overlap is normal and expected, never forced into one
    bucket, never guessed from surface wording.
    """
    category_lines = []
    for cat_id, info in taxonomy["category_evidence_status"].items():
        # ALL examples, cleaned and de-duplicated -- previously only the first 8
        # raw titles were shown, which were often near-duplicates and hid core
        # examples (e.g. Python and OOP never appeared for programming).
        examples = clean_example_titles(info.get("candidate_courses", []))
        example_str = "; ".join(examples) if examples else "(no confirmed examples yet)"
        block = [f"- {cat_id}"]
        if info.get("definition"):
            block.append(f"    Definition: {info['definition']}")
        if info.get("includes"):
            block.append(f"    Includes: {'; '.join(info['includes'])}")
        if info.get("excludes"):
            block.append(f"    Does NOT include: {'; '.join(info['excludes'])}")
        if info.get("typical_topics"):  # 27.10.2026: syllabus topics from the approved taxonomy
            block.append(f"    Typical topics: {'; '.join(info['typical_topics'])}")
        block.append(
            f"    Example course titles (from JNTUH curricula ONLY -- illustrative, NOT an "
            f"exhaustive or restrictive list): {example_str}"
        )
        category_lines.append("\n".join(block))

    category_reference = "\n".join(category_lines)
    aggregate_note = taxonomy.get("_aggregation_method", "")
    evidence_defs = taxonomy.get("_evidence_status_definitions", {})
    taxonomy_rules = "\n".join(taxonomy.get("_classification_rules", []))  # 27.10.2026

    return f"""You are classifying university courses into a FIXED, FROZEN taxonomy for a
German university admissions matching system. You must assign EACH course to
every category from the list below that it genuinely belongs to (one, several,
or none -- see Rule 4). Use each category's Definition, Includes and Does NOT
include text to decide; the example titles only illustrate them.

## RULES FROM THE TAXONOMY (always follow)
{taxonomy_rules}

## THE FROZEN CATEGORY LIST (select ONLY from these exact IDs)

{category_reference}

## CRITICAL RULES

0. UNIVERSALITY REQUIREMENT -- read this first. The example course names shown
   under each category below come from ONE specific source (JNTUH regulations,
   India) that happened to be used to build this taxonomy. They are NOT the
   full set of valid course names, and they are NOT specific to any one
   university or country. This system must correctly classify courses from ANY
   institution worldwide, with ANY naming convention, including titles that
   look nothing like the examples shown. Your job is to understand what a
   course actually TEACHES based on its title (and content, if available), and
   match that real academic content to the correct category -- never to check
   whether a title superficially resembles one of the examples.

1. Semantic understanding, not string matching. Recognize when differently-worded
   course titles describe the same underlying subject.

2. Never invent a category ID. Use IDs exactly as they appear above, or return an
   empty categories list when none apply.

3. Distinguish real content differences from superficial word overlap. A course
   titled "Computer Oriented Statistical Methods" is a statistics course
   (mathematics_statistics), not a CS course, despite the word "Computer" in
   its title -- classify by actual academic content, never by surface wording.

4. NO PRIMARY OR SECONDARY CATEGORY. There is no ranking between categories a
   course belongs to -- every genuine match is an equal, independent one.
   List EVERY category from the frozen list above that the course genuinely,
   substantively belongs to, as a flat list. A course may belong to one
   category, several, or none. Overlap across categories is normal and
   expected (e.g. a Data Mining course genuinely combining data-science
   methodology with machine-learning technique) -- list both categories, with
   neither one treated as more "correct" than the other. Never force a course
   with genuine multi-category content into a single category, and never
   invent a false hierarchy between the categories you list. If a course
   title gives no reliable signal at all, return an empty categories list
   with confidence "INSUFFICIENT_TITLE_INFO" -- do not guess.

5. It is correct for non-technical courses (language labs, civics, environmental
   studies, soft skills, gender sensitization, workshops, etc.) to return an
   empty categories list. This is the correct answer for these, not a failure.
   PROJECTS: project work, seminars, mini-projects and internships (e.g.
   "Project Stage - I", "Seminar", "Industrial Oriented Mini Project / Summer
   Internship") go to a thesis / scientific-work category ONLY if one exists in
   the list above. If the list has no such category, return an EMPTY list with
   HIGH confidence -- their topic is unknown and never counts toward any subject
   category, so there is nothing to verify and no syllabus is needed.

6. A category only counts if it is a SUBSTANTIAL, dedicated part of the course --
   not a passing mention, background context, or introductory framing used to
   set up the course's real subject. For example, a Remote Sensing course that
   briefly explains the electromagnetic spectrum to introduce how sensors work
   is NOT thereby a physics course -- that is background context, not
   dedicated physics content, and should NOT be assigned
   physics_natural_sciences.general_physics.

   MINIMUM SHARE RULE: when you have full syllabus content (not just a title),
   a category only counts if the content genuinely belonging to it makes up AT
   LEAST 40% of the course's total syllabus (by units/topics covered, or by
   teaching time/weight if stated). A single unit dedicated to a topic is NOT
   automatically enough on its own -- if that unit is 1 of 6 largely unrelated
   units, it is roughly 17% of the course and does NOT meet the 40% bar, even
   though it is a real, dedicated unit and not a passing mention. Example: a
   Remote Sensing and GIS course where only 1 of 5 units covers spatial
   database design is NOT a databases_systems course -- that single unit is
   real, substantial content, but it is not 40%+ of what the course actually
   teaches. This rule applies only when you can see the real syllabus
   structure; for title-only classification, use your best overall judgment of
   what the course as a whole teaches.

7. Note on evidence status definitions below -- these describe how confirmed
   THIS TAXONOMY'S OWN EXAMPLE LIST is (it was built by reviewing one
   institution's curriculum), NOT a signal about how confidently you may
   classify a NEW course into that category. A category marked
   REQUIRES_SYLLABUS_VERIFICATION in this reference means "we have not yet
   confirmed real examples for this category from title alone" -- it does
   NOT mean "avoid assigning this category" or "always request syllabus
   evidence for this category." You classify every course strictly on its own
   semantic merits, from any institution, using your own genuine judgment of
   what the course teaches -- assign HIGH confidence whenever a course title
   is genuinely clear, regardless of which category it happens to be, and
   regardless of this taxonomy's own evidence-confirmation status:
{json.dumps(evidence_defs, indent=2)}

## AGGREGATION NOTE
{aggregate_note}

## OUTPUT FORMAT

Return a JSON object: {{"classifications": [...]}} where each entry is:
{{
  "course_id": "<as given>",
  "categories": ["<one or more exact category IDs from the list above, flat, no ranking>"],
  "confidence": "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT_TITLE_INFO",
  "reasoning": "<one or two sentences>"
}}
Use an empty list ("categories": []) when no category genuinely applies.

## WHEN YOU HAVE ACTUAL SYLLABUS CONTENT (not just a title)

If you are given real syllabus/course content (an excerpt, not just a title),
add one more field: "evidence_by_category", a JSON object mapping EACH
category ID you listed to its OWN separate, genuine quote from that content --
the actual text showing that category is a substantial, dedicated part of the
course (per Rule 6 above). One category, one quote, each specific to that
category -- never reuse the same quote for two different categories, and
never list a category you cannot back with its own quote. If a category
only has a passing one-line mention and nothing more, do not list it at all.
Example: {{"databases_systems": "Unit 3 covers spatial database design...",
"graphics_visual_computing": "Unit 5: raster and vector rendering techniques..."}}

Also add "syllabus_share_by_category": a JSON object mapping EACH listed
category to your honest estimate of what PERCENTAGE (0-100) of the course's
total syllabus content belongs to that category -- based on unit/topic count,
or teaching time/weight if the syllabus states it. Per the MINIMUM SHARE RULE
in Rule 6, only list a category whose real share is at least 40. If a
category's dedicated content is real but is a minority of the course (below
40%), do not list that category at all, however genuine that content is.
Example: {{"databases_systems": 20, "graphics_visual_computing": 45}}
"""



def make_course_ids_unique(courses: list[ExtractedCourse]) -> list[ExtractedCourse]:
    """
    Every course needs its own ID: results, credits and knowledge-base entries are all
    matched by course_id. Transcript reading can produce the same code twice (a misread
    code, or a memo that reuses codes), which would silently give one course another
    course's categories and credits. Duplicates get a suffix: EC3801, EC3801#2, ...
    """
    from dataclasses import replace
    seen: dict[str, int] = {}
    out = []
    for c in courses:
        base = (c.course_id or "").strip() or "COURSE"
        n = seen.get(base, 0) + 1
        seen[base] = n
        out.append(c if n == 1 and c.course_id == base else replace(c, course_id=base if n == 1 else f"{base}#{n}"))
    return out


def apply_implied_categories(categories: list, taxonomy: dict) -> list:
    """
    Adds every category a taxonomy says is implied by one already present, so a general
    category can never be forgotten. EE example: control_systems -> also general_ee;
    programming_practical_cs -> also general_cs. Taxonomies without "_implies" are unchanged.
    """
    implies = taxonomy.get("_implies", {})
    out = list(categories)
    for c in list(out):
        for extra in implies.get(c, []):
            if extra not in out:
                out.append(extra)
    return out

def classify_courses_openai(courses: list[ExtractedCourse], taxonomy: dict,
                              knowledge_base: KnowledgeBase,
                              api_key: str | None = None, model: str = "gpt-6-astra") -> list[dict]:
    """
    Knowledge-base-first classification:
      1. For every course, check the knowledge base for an exact, previously
         verified title match (from any institution). If found, reuse it --
         zero LLM cost for this course.
      2. Only courses with no knowledge-base match go to the LLM, in one
         batch call (same as before).
      3. Any NEW result that comes back HIGH confidence gets recorded into
         the knowledge base, so it's reusable for the next student.

    Returns the same shape as before: a list of classification dicts, one
    per course, in the same order as `courses`.
    """
    ids = [c.course_id for c in courses]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"Duplicate course IDs {dupes}: call make_course_ids_unique() first, "
                         f"otherwise one course would get another course's result.")
    known_results: dict[str, dict] = {}
    courses_needing_llm: list[ExtractedCourse] = []
    # Knowledge-base answers are reused only within the field of the taxonomy in use.
    field = taxonomy.get("_field", "cs")

    for c in courses:
        if is_generic_math_title(c.title):
            # Never guessed from the title, never taken from the knowledge base:
            # always flagged so the student's own syllabus decides.
            known_results[c.course_id] = {
                "course_id": c.course_id,
                "categories": [],
                "confidence": "INSUFFICIENT_TITLE_INFO",
                "reasoning": ("A general mathematics course title does not show what it covers "
                              "(calculus, linear algebra, differential equations or statistics). "
                              "This differs between universities, so the syllabus is always needed."),
            }
            continue
        hit = knowledge_base.lookup(c.title, field=field)
        if hit is not None:
            known_results[c.course_id] = {
                "course_id": c.course_id,
                "categories": list(hit.categories),
                "confidence": hit.confidence,
                "reasoning": f"[REUSED FROM KNOWLEDGE BASE, verified {hit.verified_count}x] {hit.reasoning}",
            }
        else:
            courses_needing_llm.append(c)

    llm_results: dict[str, dict] = {}
    if courses_needing_llm:
        client = OpenAI(api_key=api_key) if api_key else OpenAI()
        system_prompt = build_classification_prompt(taxonomy)
        valid_ids = set(taxonomy["category_evidence_status"].keys())

        # Batches keep every answer small enough to fit, whatever the transcript size
        # (a 4-year memo has ~70 courses; one big answer can overflow the output budget).
        for start in range(0, len(courses_needing_llm), CLASSIFY_BATCH_SIZE):
            batch = courses_needing_llm[start:start + CLASSIFY_BATCH_SIZE]
            course_list_text = "\n".join(
                json.dumps({"course_id": c.course_id, "title": c.title, "credits": c.credits}, ensure_ascii=False)
                for c in batch
            )
            messages: list = [  # type: ignore[assignment]
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Classify every course below.\n\n{course_list_text}"}
            ]
            parsed = call_llm_json(client, model, messages, max_tokens=16000,
                                   what=f"classification of courses {start + 1}-{start + len(batch)}")
            batch_ids = {c.course_id for c in batch}
            for r in parsed.get("classifications", []):
                if r.get("course_id") not in batch_ids:
                    continue  # ignore anything the model invented outside this batch
                cats = apply_implied_categories(r.get("categories") or [], taxonomy)
                r["categories"] = cats  # normalize missing key to empty list
                invalid = [c for c in cats if c not in valid_ids]
                if invalid:
                    # A category that is not in this field's taxonomy never counts for this
                    # field's programs (e.g. "geotechnical" for a Civil student). It is dropped,
                    # never allowed to crash the whole run.
                    r["categories"] = [c for c in cats if c in valid_ids]
                    r["reasoning"] = str(r.get("reasoning", "")) + f" [IGNORED -- not a category of this field: {invalid}]"
                llm_results[r["course_id"]] = r

        # A course the model silently skipped is flagged for evidence -- never guessed, never a crash.
        for c in courses_needing_llm:
            if c.course_id not in llm_results:
                llm_results[c.course_id] = {
                    "course_id": c.course_id, "categories": [], "confidence": "INSUFFICIENT_TITLE_INFO",
                    "reasoning": "The classifier returned no answer for this course, so it needs syllabus evidence.",
                }

        # Record new, HIGH-confidence results into the knowledge base for reuse.
        title_lookup = {c.course_id: c.title for c in courses_needing_llm}
        for course_id, r in llm_results.items():
            knowledge_base.record(
                field=field,
                title=title_lookup[course_id],
                categories=r.get("categories", []),
                confidence=r.get("confidence", "LOW"),
                reasoning=r.get("reasoning", ""),
                source="title_only",
            )

    # Merge, preserving the original course order
    all_results = []
    for c in courses:
        if c.course_id in known_results:
            all_results.append(known_results[c.course_id])
        else:
            all_results.append(llm_results[c.course_id])
    return all_results


def attach_credits_for_aggregates(classifications: list[dict], courses: list[ExtractedCourse]) -> list[dict]:
    """
    Produces the exact shape german_conversion.compute_aggregates() needs for
    its correct, union-of-unique-course-IDs path: each classification dict,
    with a "credits" field merged in from the matching ExtractedCourse.

    Without this step, classify_courses_openai()'s raw output has no
    "credits" field at all (credits live separately, keyed by course_id, on
    the ExtractedCourse objects) -- passed straight into compute_aggregates(),
    every course would silently contribute 0 credits to every aggregate/
    contextual pool. This is the required glue step between classification
    and aggregate computation; skip it and the union path looks like it ran
    correctly but produces all-zero totals.
    """
    credits_lookup = {c.course_id: c.credits for c in courses}
    return [
        {**r, "credits": credits_lookup.get(r["course_id"], 0)}
        for r in classifications
    ]


def compute_atomic_profile(classifications: list[dict], courses: list[ExtractedCourse]) -> dict:
    """
    Builds the atomic-category credit profile. Every category in a course's
    flat `categories` list is treated as an equal, independent match -- a
    course dual-mapped into two categories contributes its full credits to
    BOTH (this is legitimate atomic-level overlap, not double-counting; the
    only place a real double-count risk exists is in a POOLED aggregate
    total, which german_conversion.compute_aggregates() handles separately
    via union-of-unique-course-IDs).
    """
    credits_lookup = {c.course_id: c.credits for c in courses}
    profile: dict[str, float] = {}

    for r in classifications:
        course_id = r["course_id"]
        credits = credits_lookup.get(course_id, 0)
        for cat in r.get("categories", []):
            if cat:
                profile[cat] = profile.get(cat, 0) + credits

    return profile


def upgrade_classification_with_excerpt_pdf(course, excerpt_file, taxonomy,
                                              knowledge_base: KnowledgeBase,
                                              api_key=None, model="gpt-6-astra"):
    """
    Same as before, PLUS: on a successful, evidence-backed HIGH-confidence
    resolution, records it into the knowledge base so the next student with
    the same course title (from any institution) never needs to go through
    this excerpt process again.
    """
    if not excerpt_file.readable:
        raise ValueError("Cannot use an unreadable excerpt file: " + str(excerpt_file.error))

    client = OpenAI(api_key=api_key) if api_key else OpenAI()
    system_prompt = build_classification_prompt(taxonomy)

    if excerpt_file.file_kind == "pdf":
        content_block = {
            "type": "file",
            "file": {"filename": "excerpt.pdf", "file_data": "data:application/pdf;base64," + excerpt_file.base64_data}
        }
    elif excerpt_file.file_kind == "image":
        content_block = {
            "type": "image_url",
            "image_url": {"url": "data:" + excerpt_file.mime_type + ";base64," + excerpt_file.base64_data, "detail": "high"}
        }
    else:
        raise ValueError("Unsupported excerpt file kind: " + str(excerpt_file.file_kind))

    text_prompt = (
        "Course: " + course.title + " (course_id: " + course.course_id + ")\n\n"
        "The attached small document is an excerpt the student retrieved from their own "
        "study regulations, describing what this specific course actually covers. "
        "Using this real content (not just the title), classify this ONE course. "
        "Remember: no primary/secondary ranking -- list every category this course "
        "genuinely, substantively belongs to as a flat \"categories\" list (can be "
        "more than one, or empty if none apply) -- but per Rule 6, only list a "
        "category if it is a real, dedicated, substantial part of the syllabus, "
        "never a passing mention used to introduce something else. "
        "Return a JSON object with a single-item \"classifications\" array. Include "
        "\"evidence_by_category\": a mapping of EACH listed category to its OWN "
        "separate, genuine quote from the attached document -- one quote per "
        "category, each specific to that category, never a single quote reused "
        "for several categories. If you cannot find a real, substantial quote for "
        "a category, do not list that category at all. Also include "
        "\"syllabus_share_by_category\": your honest estimate, per listed category, "
        "of what percentage (0-100) of this course's total syllabus belongs to that "
        "category, based on the units/topics you can see in the attached document. "
        "Per the MINIMUM SHARE RULE, only list a category whose real share is at "
        "least 40 -- a single dedicated unit out of many unrelated units is real "
        "content but is NOT enough on its own if it is under 40% of the course. "
        "ALWAYS also include \"syllabus_found\": true only if the attached document "
        "really contains THIS course's own syllabus (its units or topics), otherwise "
        "false; and \"content_quote\": a direct quote of this course's unit/topic "
        "list from the document (at least one full unit), or an empty string if "
        "not found. If the syllabus is found and NO category reaches 40%, return an "
        "empty \"categories\" list with HIGH confidence -- that is a proven answer."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [content_block, {"type": "text", "text": text_prompt}]}
    ]

    parsed = call_llm_json(client, model, messages, max_tokens=8000,
                           what=f"syllabus check for '{course.title}'")
    results = parsed.get("classifications", [])
    if not results:
        raise ValueError("Model returned no classification for the excerpt-based upgrade.")

    result = results[0]
    result["course_id"] = course.course_id

    valid_ids = set(taxonomy["category_evidence_status"].keys())
    cats = result.get("categories") or []
    result["categories"] = cats
    invalid = [c for c in cats if c not in valid_ids]
    if invalid:
        # Not a category of this field: dropped (it can never count for this field's programs).
        cats = [c for c in cats if c in valid_ids]
        result["categories"] = cats
        result["reasoning"] = str(result.get("reasoning", "")) + f" [IGNORED -- not a category of this field: {invalid}]"

    # Per-category evidence check -- this is the real fix for over-broad
    # multi-category results. A single evidence_quote for the whole course
    # let the LLM attach 3-4 categories while only one of them had any real
    # backing. Now EACH category must have its OWN genuine, substantial,
    # non-reused quote, or it is dropped -- silently, per-category, not as
    # an all-or-nothing rejection of the whole result.
    evidence_by_category = result.get("evidence_by_category") or {}
    share_by_category = result.get("syllabus_share_by_category") or {}

    MIN_QUOTE_LEN = 15
    MIN_SYLLABUS_SHARE = 40  # a category must be at least this % of the course to count

    kept_categories = []
    seen_quotes = set()
    dropped_no_evidence = []
    dropped_low_share = []
    for cat in cats:
        quote = evidence_by_category.get(cat)
        quote_clean = quote.strip() if isinstance(quote, str) else ""
        has_genuine_quote = len(quote_clean) >= MIN_QUOTE_LEN and quote_clean not in seen_quotes

        share = share_by_category.get(cat)
        try:
            share_value = float(share) if share is not None else None
        except (TypeError, ValueError):
            share_value = None
        # Missing share data is treated as failing the bar -- we require the
        # model to report it whenever it has real syllabus content, so a
        # missing value means it likely couldn't justify one anyway.
        meets_share = share_value is not None and share_value >= MIN_SYLLABUS_SHARE

        if not has_genuine_quote:
            dropped_no_evidence.append(cat)
        elif not meets_share:
            dropped_low_share.append(f"{cat} ({share_value if share_value is not None else 'no share given'}%)")
        else:
            kept_categories.append(cat)
            seen_quotes.add(quote_clean)

    notes = []
    if dropped_no_evidence:
        notes.append(f"lacking their own genuine evidence quote: {dropped_no_evidence}")
    if dropped_low_share:
        notes.append(f"below the 40% minimum syllabus share: {dropped_low_share}")
    if notes:
        result["reasoning"] = str(result.get("reasoning", "")) + " [DROPPED -- " + "; ".join(notes) + "]"

    # Implied general categories are added after the evidence checks: they follow from a kept
    # category, so they need no quote of their own.
    result["categories"] = apply_implied_categories(kept_categories, taxonomy)
    cats = result["categories"]

    content_quote = result.get("content_quote")
    content_quote = content_quote.strip() if isinstance(content_quote, str) else ""
    proven_none = (
        not cats
        and result.get("syllabus_found") is True
        and len(content_quote) >= 40          # real unit/topic text, not a fragment
        and not dropped_no_evidence           # nothing was dropped for lack of a quote
        and result.get("confidence") == "HIGH"
    )

    if proven_none:
        # The course's own syllabus was read and no category reaches 40%: a proven
        # "no category" answer. Saved like any other verified answer, so the next
        # student with this title is not asked for a syllabus again.
        result["categories"] = []
        result["reasoning"] = "VERIFIED NONE from the syllabus: no category reaches 40%. " + str(result.get("reasoning", ""))
    elif not cats:
        original_reasoning = result.get("reasoning", "(none)")
        result["categories"] = []
        result["confidence"] = "INSUFFICIENT_TITLE_INFO"
        result["reasoning"] = "DOWNGRADED: no category retained its own genuine evidence quote and 40%+ syllabus share from the attached excerpt. " + str(original_reasoning)

    # The stored evidence is the per-category quotes that actually survived the
    # checks above, one line per kept category. (The model no longer returns a
    # single top-level evidence_quote -- relying on that field meant excerpt-
    # verified courses were silently never saved.)
    kept_evidence = "\n".join(
        f"{cat}: {evidence_by_category[cat].strip()}" for cat in cats if isinstance(evidence_by_category.get(cat), str)
    ) if cats else None
    if proven_none:
        kept_evidence = "NO CATEGORY (syllabus read): " + content_quote
    result["evidence_quote"] = kept_evidence

    # Record into the knowledge base -- KnowledgeBase.record() itself enforces
    # HIGH confidence + genuine evidence_quote before actually storing anything,
    # so an unresolved/downgraded result here is safely ignored, not stored.
    knowledge_base.record(
        field=taxonomy.get("_field", "cs"),
        title=course.title,
        categories=result.get("categories", []),
        confidence=result.get("confidence", "LOW"), reasoning=result.get("reasoning", ""),
        source="student_excerpt", evidence_quote=kept_evidence,
    )

    return result


if __name__ == "__main__":
    print("Classifier module loaded.")
    print("Call classify_courses_openai(courses, taxonomy, knowledge_base) "
          "with real extracted courses.")
