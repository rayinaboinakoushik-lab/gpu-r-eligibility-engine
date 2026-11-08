# Passing the new taxonomy fields to the LLM (course_classifier.py)

Your `build_classification_prompt()` already reads definition, includes, excludes and candidate_courses.
Two additions make it read the new fields too (your code, your decision):

1. Inside the per-category loop, after the "Does NOT include" line:
```python
        if info.get("typical_topics"):
            block.append(f"    Typical topics: {'; '.join(info['typical_topics'])}")
```

2. At the start of the returned prompt (before the category list), add the file's rules:
```python
    rules = "\n".join(taxonomy.get("_classification_rules", []))
    # then put  {rules}  under a heading "## RULES FROM THE TAXONOMY" in the f-string
```

Copy the four files from `data/taxonomy/` next to your scripts (same names as before:
cs_taxonomy.json, eee_taxonomy.json, mechanical_taxonomy.json, civil_taxonomy.json).
`apply_implied_categories()` already applies `_implies` (rules S1-S3).
