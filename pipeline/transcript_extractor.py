"""
Real transcript extraction using the OpenAI API (GPT-4o / vision-capable model).

This replaces the earlier Anthropic-specific design with one that actually works
with an OpenAI API key. The extraction PROMPT itself is unchanged (it's plain
text, model-agnostic) -- only the API call mechanics are OpenAI-specific.

Requires: pip install openai --break-system-packages
Requires: an OPENAI_API_KEY environment variable, or pass the key directly.
"""

import json
import base64
from openai import OpenAI

from file_intake import PreparedFile, prepare_file
from llm_utils import call_llm_json
from transcript_parser import (
    ExtractedCourse, TranscriptExtractionResult,
    EXTRACTION_SYSTEM_PROMPT, validate_extraction, assemble_student_profile
)


def extract_transcript_openai(prepared_file: PreparedFile, api_key: str | None = None,
                                model: str = "gpt-6-astra") -> TranscriptExtractionResult:
    """
    Sends a prepared transcript image/PDF to OpenAI's vision-capable model and
    parses the response into a TranscriptExtractionResult.

    prepared_file: the output of file_intake.prepare_file() -- already validated
                    and base64-encoded.
    api_key: your OpenAI API key. If None, reads from OPENAI_API_KEY env variable
             (the openai library does this automatically).
    model: defaults to gpt-4o, OpenAI's vision-capable model. Any vision-capable
           OpenAI model name can be substituted here.
    """
    if not prepared_file.readable:
        raise ValueError(f"Cannot extract from an unreadable file: {prepared_file.error}")

    client = OpenAI(api_key=api_key) if api_key else OpenAI()

    if prepared_file.file_kind == "image":
        # OpenAI's vision input format: image as a data URL inside the message content
        image_data_url = f"data:{prepared_file.mime_type};base64,{prepared_file.base64_data}"
        user_content = [
            {"type": "text", "text": "Extract all course data from this transcript image, following the schema in your instructions exactly."},
            {"type": "image_url", "image_url": {"url": image_data_url, "detail": "high"}}
        ]
    elif prepared_file.file_kind == "pdf":
        # PDFs are sent as file attachments via OpenAI's file input format
        user_content = [
            {"type": "text", "text": "Extract all course data from this transcript PDF, following the schema in your instructions exactly."},
            {"type": "file", "file": {"filename": "transcript.pdf", "file_data": f"data:application/pdf;base64,{prepared_file.base64_data}"}}
        ]
    else:
        raise ValueError(f"Unsupported file kind for extraction: {prepared_file.file_kind}")

    # No output limit for transcript reading: the old fixed 4000-token limit ran out
    # during the model's thinking on a 64-course memo and returned an EMPTY answer.
    parsed = call_llm_json(
        client, model,
        messages=[
            {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ],
        max_tokens=None,
        what="transcript extraction",
    )

    courses = []
    for i, c in enumerate(parsed.get("courses", [])):
        title = c.get("title")
        if not title:
            raise ValueError(
                f"Course at index {i} has no title (got: {title!r}) -- this is a "
                f"required field. The model's extraction is incomplete or malformed "
                f"for this course: {c}"
            )
        credits = c.get("credits")
        if credits is None:
            raise ValueError(
                f"Course '{title}' has no credits value -- this is a required field. "
                f"The model's extraction is incomplete for this course: {c}"
            )
        courses.append(ExtractedCourse(
            course_id=c.get("course_id") or f"unknown-{i}",
            title=title,
            credits=credits,
            grade_letter=c.get("grade_letter"),
            grade_point=c.get("grade_point"),
            semester=c.get("semester")
        ))

    # Use "or" instead of .get(key, default) for str-typed fields --
    # .get()'s default only applies when the KEY is missing, not when the key
    # is present with an explicit null value (which our own prompt allows for
    # "regulation"). "or" correctly falls back to the default in both cases.
    return TranscriptExtractionResult(
        student_name=parsed.get("student_name") or "UNKNOWN",
        institution=parsed.get("institution") or "UNKNOWN",
        program=parsed.get("program") or "UNKNOWN",
        regulation=parsed.get("regulation") or "UNKNOWN",
        entry_type=parsed.get("entry_type") or "regular",
        courses=courses,
        stated_total_credits=parsed.get("stated_total_credits"),
        stated_cgpa=parsed.get("stated_cgpa"),
        min_credits_for_award=parsed.get("min_credits_for_award"),
        years_with_courses=parsed.get("years_with_courses"),
    )


if __name__ == "__main__":
    print("OpenAI extraction module loaded.")
    print("Call extract_transcript_openai(prepared_file, api_key=...) with a real prepared file to run extraction.")