# RAG lab: regulation search over the GPU-R records

A separate experiment on the same data as the rule engine. The engine, the website and the records are untouched.

**Question it answers:** what can retrieval-augmented generation (RAG) do with GPU-R's 228 programme records, and where must the rule engine decide instead?

| Step | File | What it does |
|---|---|---|
| 1 Chunking | `chunking.py` | One chunk per requirement section (grade, each subject requirement, conditions, English, ...), each with a context header (programme, university, field) and its regulation URL |
| 2 Embeddings + store | `store.py`, `build_index.py` | OpenAI embeddings (`text-embedding-3-small`) into a Qdrant collection `gpur_regulations`, cosine similarity |
| 3 Grounded answers | `answer.py` | Top-k chunks, a relevance threshold, then the LLM answers only from those chunks with citations, or "Not found in the regulations." It never decides eligibility |
| 4 Retrieval evaluation | `eval_retrieval.py` | Generated questions with a known correct chunk: hit@1/3/5, MRR, and negative questions to check the threshold |

## Run

```
docker run -d -p 6333:6333 --name gpur_qdrant qdrant/qdrant:v1.20.0   # or any running Qdrant
py -m pip install qdrant-client
py -m rag_lab.build_index                  # about 3,000 chunks, cost well under 0.05 USD
py -m rag_lab.answer "What English test does AI & Robotics at UTN require?"
py -m rag_lab.eval_retrieval --n 60
```

Settings in `.env`: `OPENAI_API_KEY`, optional `QDRANT_URL`, `RAG_EMBED_MODEL`, `RAG_MODEL`, `RAG_MIN_SCORE` (0.55), `RAG_TOP_K` (5).

## Design choices

- **Section chunks, not fixed windows.** A regulation rule is a natural unit; a fixed 500-character window would cut rules in half or mix two programmes.
- **Context header in every chunk.** "At least 18 ECTS in analysis" is useless without the programme name; the header makes the chunk self-contained and retrievable by programme.
- **Threshold before the model.** If the best match is weak, no LLM call is made, so the model cannot fill gaps with general knowledge.
- **Citations.** Every answer lists the sources used, with section, similarity and regulation link.
- **Explains, never decides.** Eligibility stays with the rule engine; this lab measures why.

## Results (November 2026)

### Retrieval

60 generated questions with a known correct chunk, plus 10 questions the records cannot answer.

| hit@1 | hit@3 | hit@5 | MRR | right programme at rank 1 |
|---|---|---|---|---|
| 0.60 | 0.90 | 0.95 | 0.741 | 0.95 |

The relevance threshold of 0.55 was chosen from the data: every answerable question scored at least 0.683, every unanswerable one at most 0.462, so no question fell on the wrong side.

### Rules vs RAG: who should decide eligibility?

`experiment.py` asks the same question three ways, for 4 synthetic students and a sample of programmes stratified by the engine's list:

- **rules**: the GPU-R engine (no AI).
- **oracle**: an LLM given the programme's complete, correct record. It tests reasoning alone.
- **rag**: the same LLM given the top 8 chunks retrieved by a search. It tests retrieval and reasoning together.

Both LLM variants get the same student profile, the same prompt and the same GPU-R policy notes, so the comparison is fair. "Looser" means the LLM put the student in a better list than the rules allow, which is the dangerous direction.

| Run | Cases | Oracle agrees | Oracle looser | RAG agrees | RAG looser |
|---|---|---|---|---|---|
| Before the engine fix | 60 | 88.3% | 0 | 86.7% | 3 |
| After the engine fix | 54 | 98.1% | 0 | 85.2% | 4 |

What the manual review of the 15 disagreements of the first run showed:

- **The experiment found engine errors too.** In 7 of them, the LLM was right and the engine wrong: 14 regulations state per-area condition limits (for example "at most 12 CP of mathematics as a condition") that the engine stored but did not enforce. After the fix, the oracle agrees in 53 of 54 cases. The remaining case showed one more engine gap: a route that needs proof of a "special qualification" was open without that proof. It now needs the student's confirmation (12 November 2026).
- **Of the 6 real LLM errors, 4 were retrieval errors** (RAG only): the search returned the wrong chunks (for example another programme's copy of a record), and the model reasoned from the wrong text. Better reasoning cannot fix this. The other 2 were reasoning errors (a general rule applied where it did not fit). The last 2 disagreements were an ambiguous regulation.
- **RAG was looser than the rules in both runs**, including a student marked eligible for a programme the rules exclude.

Manual review of the 9 disagreements of the second run (1 oracle, 8 RAG): 5 RAG retrieval errors, 1 RAG reasoning error, 1 ambiguous case (ranking "only if applicants exceed places"; kept as no selection step), and the engine gap above, found by both the oracle and RAG. **All 4 looser RAG answers were retrieval errors**: the search missed a subject requirement and the model then judged the student eligible.

**Conclusion:** RAG is good for explaining a regulation with citations; the eligibility decision stays with the rules.

Limits: one model (`gpt-6-astra`), 4 synthetic students, 54 to 60 cases per run. The second run stopped at case 54 because of a network timeout; its consistency repeats did not run. In the first run, all three repeated answers were identical for 100% of the 20 repeated cases, for both variants. Raw results and the review table are written to `results/`.
