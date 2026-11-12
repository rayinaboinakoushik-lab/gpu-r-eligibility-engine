"""
RAG lab, step 3: grounded answers.

question -> top-k chunks -> relevance threshold -> the LLM answers ONLY from those chunks, citing them.
Below the threshold, no model is called: "Not found in the regulations".
This explains regulations; it never decides eligibility (that is the rule engine's job).
Settings: RAG_MODEL (default: the model GPU-R uses), RAG_MIN_SCORE (default 0.55, chosen from the retrieval evaluation), RAG_TOP_K (default 5).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

from rag_lab.store import search  # noqa: E402

NOT_FOUND = "Not found in the regulations."
SYSTEM = """You answer questions about the admission rules of German master's programmes.
Rules:
1. Use ONLY the numbered sources below. Do not use outside knowledge.
2. Cite every fact with its source number, e.g. [S2].
3. If the sources do not contain the answer, reply exactly: "Not found in the regulations."
4. Never decide whether a specific student is eligible; you only explain what the regulation says.
Return JSON: {"answer": "...", "sources_used": [numbers]}"""


def min_score() -> float:
    return float(os.environ.get("RAG_MIN_SCORE", "0.55"))


def ask(question: str, top_k: int | None = None, client=None) -> dict:
    top_k = top_k or int(os.environ.get("RAG_TOP_K", "5"))
    hits = search(question, top_k=top_k)
    relevant = [h for h in hits if h["score"] >= min_score()]
    if not relevant:
        return {"question": question, "answer": NOT_FOUND, "sources": [], "top_score": hits[0]["score"] if hits else 0.0}

    from openai import OpenAI
    from llm_utils import call_llm_json
    client = client or OpenAI()
    context = "\n\n".join(f"[S{i + 1}] {h['text']}\n(source: {h['source_url']})" for i, h in enumerate(relevant))
    out = call_llm_json(client, os.environ.get("RAG_MODEL", "gpt-6-astra"),
                        [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Sources:\n{context}\n\nQuestion: {question}"}],
                        max_tokens=2000, what="RAG answer")
    used = [n for n in out.get("sources_used", []) if isinstance(n, int) and 1 <= n <= len(relevant)]
    return {"question": question, "answer": out.get("answer", NOT_FOUND),
            "sources": [{"n": n, "programme": relevant[n - 1]["program"], "university": relevant[n - 1]["university"],
                         "section": relevant[n - 1]["section"], "score": round(relevant[n - 1]["score"], 3),
                         "url": relevant[n - 1]["source_url"]} for n in used],
            "top_score": round(relevant[0]["score"], 3)}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    q = " ".join(sys.argv[1:]) or input("Question: ")
    print(json.dumps(ask(q), ensure_ascii=False, indent=2))
