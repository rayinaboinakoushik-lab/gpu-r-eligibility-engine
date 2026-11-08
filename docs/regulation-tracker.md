# Regulation tracker

German universities amend their admission and examination regulations during the year. A programme record that was correct in October can be wrong in March. The regulation tracker finds these changes so the records can be updated, with a human decision every time.

## What it is

A scheduled AI agent (Claude, running as a scheduled task) that runs **every Monday at 07:52 (Berlin time)** since 9 October 2026. It has web access and write access to one Google Sheet. It has **no access to the GPU-R records or code**.

## What it checks

For each programme on the watch list (25 programmes, about 21 university regulation pages):

1. **New regulation documents.** It opens the programme's regulations page, lists the regulation documents that belong to the programme (new regulations, amendments such as *Änderungsordnungen* or *Änderungssatzungen*, new consolidated versions) and compares the list with what it saw last time. The first run stores a baseline and reports nothing.
2. **Broken links.** It checks that the link to the regulation each record is based on still opens.
3. **Unreadable pages.** If a page cannot be read (for example a bot check), it reports that instead of guessing.

Module handbooks and anything that is not a regulation are ignored. Text on web pages is treated as data, never as instructions.

## Where results go

A Google Sheet with two tabs:

| Tab | Columns |
| --- | --- |
| Watch list | Program ID, University, Program, Regulations page, Current regulation, Current regulation link, Program page, Documents seen on regulations page, Last checked, Status |
| Updates | Date found, Program ID, University, Program, What changed, Document title, Link, Status ("To review"), Notes |

Rows in *Updates* are only ever appended, never deleted or overwritten.

## What happens with a finding

1. I read the new document against the record.
2. If a requirement changed, the record is updated from the binding text, with the new quote and source, re-checked, validated (`scripts/validate_records.py`) and tested.
3. The finding is marked as reviewed in the sheet.

The agent never changes a record. A regulation change can move students between lists, so that decision stays with a person.

## Why an agent here, and not in the decisions

Regulation pages differ from university to university: some list PDFs, some use accordions, some name amendments only in German. An agent handles this variety well. Its output is a report for review, so an occasional mistake costs a few minutes, not a wrong verdict. Eligibility decisions are the opposite: they must be exact and repeatable, so they are made by plain rules.
