"""
RAG lab, step 4: measure retrieval with questions whose correct answer we know.

Because every record is structured, questions can be generated with a known target chunk
(programme + section). Metrics:
  hit@k  = the correct chunk is among the top k results
  MRR    = mean of 1/rank of the correct chunk (1.0 = always first)
  record hit@k = the right programme is among the top k (any section)
Negative questions (not answerable from the data) check the relevance threshold:
their best score should stay BELOW it, the positives' best score ABOVE it.
Run:  py -m rag_lab.eval_retrieval [--n 60] [--k 5]
Limit: template questions are cleaner than real student questions; treat results as an upper bound.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from rag_lab.chunking import FIELD_NAMES, load_records

RESULTS = Path(__file__).resolve().parent / "results"

TEMPLATES = {
    "grade": ["Is there a minimum grade for {p} at {u}?", "What final grade do I need for {p} at {u}?"],
    "english": ["What IELTS or TOEFL score does {p} at {u} require?", "Which English test is accepted for {p} at {u}?"],
    "conditional_admission": ["Can I be admitted to {p} at {u} if some credits are missing?",
                              "Does {p} at {u} allow conditional admission?"],
    "accepted_degrees": ["Which bachelor degrees are accepted for {p} at {u}?", "Can I apply to {p} at {u} with my bachelor field?"],
    "german": ["Do I need German language skills for {p} at {u}?"],
    "subject_requirement": ["How many ECTS in {s} does {p} at {u} require?"],
}
NEGATIVES = [
    "What is the tuition fee for an MBA at Harvard University?",
    "How long does a German student visa take to process in India?",
    "Which restaurants in Berlin are open on Sunday?",
    "What are the admission requirements for medicine (MBBS) in Telangana?",
    "How much does a flat cost in Munich?",
    "What is the deadline for the Oxford DPhil in History?",
    "How do I open a blocked account for Germany?",
    "Can I work full time on a student visa in Canada?",
    "What is the NEET cutoff for BC-D category?",
    "Who won the football World Cup in 2022?",
]


def _subject_words(category: str) -> str:
    return category.split(".")[-1].replace("_", " ")


def make_questions(n: int = 60, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    records = load_records()
    rng.shuffle(records)
    qs: list[dict] = []
    types = list(TEMPLATES)
    for i, rec in enumerate(records):
        if len(qs) >= n:
            break
        t = types[i % len(types)]
        p, u = rec["program"], rec["university"]
        if t == "subject_requirement":
            items = (rec.get("subject_credit_requirements") or {}).get("items") or []
            if not items:
                continue
            it = rng.choice(items)
            text = rng.choice(TEMPLATES[t]).format(p=p, u=u, s=_subject_words(it["canonical_category"]))
        else:
            text = rng.choice(TEMPLATES[t]).format(p=p, u=u)
        qs.append({"question": text, "record_id": str(rec["id"]), "section": t,
                   "field": FIELD_NAMES.get(rec["_domain"], rec["_domain"])})
    return qs


def run(n: int, k: int) -> dict:
    from rag_lab.store import search
    from rag_lab.answer import min_score
    qs = make_questions(n)
    rows, t0 = [], time.time()
    for q in qs:
        hits = search(q["question"], top_k=k)
        rank = next((i + 1 for i, h in enumerate(hits) if h["record_id"] == q["record_id"] and h["section"] == q["section"]), None)
        rrank = next((i + 1 for i, h in enumerate(hits) if h["record_id"] == q["record_id"]), None)
        rows.append({**q, "rank": rank, "record_rank": rrank, "top_score": hits[0]["score"] if hits else 0.0,
                     "top_hit": f"{hits[0]['program']} | {hits[0]['university']} | {hits[0]['section']}" if hits else None})
    neg = [{"question": q, "top_score": (search(q, top_k=1) or [{"score": 0.0}])[0]["score"]} for q in NEGATIVES]

    def hit(key, kk):
        return round(sum(1 for r in rows if r[key] and r[key] <= kk) / len(rows), 3)
    thr = min_score()
    pos_scores = [r["top_score"] for r in rows]
    summary = {
        "questions": len(rows), "k": k, "seconds": round(time.time() - t0, 1),
        "hit@1": hit("rank", 1), "hit@3": hit("rank", 3), f"hit@{k}": hit("rank", k),
        "mrr": round(statistics.mean(1 / r["rank"] if r["rank"] else 0 for r in rows), 3),
        "record_hit@1": hit("record_rank", 1), f"record_hit@{k}": hit("record_rank", k),
        "by_section_hit@3": {s: round(sum(1 for r in rows if r["section"] == s and r["rank"] and r["rank"] <= 3)
                                      / max(1, sum(1 for r in rows if r["section"] == s)), 2) for s in TEMPLATES},
        "threshold": thr,
        "positives_min_top_score": round(min(pos_scores), 3), "positives_median_top_score": round(statistics.median(pos_scores), 3),
        "negatives_max_top_score": round(max(x["top_score"] for x in neg), 3),
        "positives_below_threshold": sum(1 for s in pos_scores if s < thr),
        "negatives_above_threshold": sum(1 for x in neg if x["top_score"] >= thr),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "retrieval_eval.json").write_text(json.dumps({"summary": summary, "questions": rows, "negatives": neg},
                                                             ensure_ascii=False, indent=1), encoding="utf-8")
    return summary


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--k", type=int, default=5)
    a = ap.parse_args()
    print(json.dumps(run(a.n, a.k), indent=2))
