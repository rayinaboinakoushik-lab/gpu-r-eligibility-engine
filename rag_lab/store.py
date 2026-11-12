"""
RAG lab, step 2: embeddings and the vector store (Qdrant).

Embeddings: OpenAI (default text-embedding-3-small, 1536 numbers per text). The same model must
embed both the chunks and the questions, otherwise the vectors are not comparable.
Similarity: cosine (1 = same meaning, 0 = unrelated).
Settings (.env): OPENAI_API_KEY, RAG_EMBED_MODEL, QDRANT_URL (default http://localhost:6333).
"""
from __future__ import annotations

import os
import uuid

COLLECTION = "gpur_regulations"


def embed_model() -> str:
    return os.environ.get("RAG_EMBED_MODEL", "text-embedding-3-small")


def embed(texts: list[str], client=None, batch: int = 100) -> list[list[float]]:
    from openai import OpenAI
    client = client or OpenAI()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        res = client.embeddings.create(model=embed_model(), input=texts[i:i + batch])
        vectors.extend(d.embedding for d in res.data)
    return vectors


_MEMORY = None


def qdrant():
    """QDRANT_URL=":memory:" gives an in-process store (used by the tests)."""
    global _MEMORY
    from qdrant_client import QdrantClient
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    if url == ":memory:":
        _MEMORY = _MEMORY or QdrantClient(location=":memory:")
        return _MEMORY
    return QdrantClient(url=url)


def point_id(chunk_id: str) -> str:
    # Qdrant ids must be ints or UUIDs; a stable UUID per chunk keeps re-indexing idempotent.
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "gpur:" + chunk_id))


def build_index(chunks: list[dict], recreate: bool = True) -> int:
    from qdrant_client.models import Distance, PointStruct, VectorParams
    qc = qdrant()
    vectors = embed([c["text"] for c in chunks])
    if recreate and qc.collection_exists(COLLECTION):
        qc.delete_collection(COLLECTION)          # re-indexing never leaves duplicates behind
    if not qc.collection_exists(COLLECTION):
        qc.create_collection(COLLECTION, vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE))
    points = [PointStruct(id=point_id(c["id"]), vector=v, payload=c) for c, v in zip(chunks, vectors)]
    for i in range(0, len(points), 256):
        qc.upsert(COLLECTION, points=points[i:i + 256])
    return len(points)


def search(question: str, top_k: int = 5, field: str | None = None) -> list[dict]:
    """Top-k chunks for a question, each with its similarity score."""
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    qc = qdrant()
    qvec = embed([question])[0]
    flt = Filter(must=[FieldCondition(key="field", match=MatchValue(value=field))]) if field else None
    hits = qc.query_points(COLLECTION, query=qvec, limit=top_k, query_filter=flt, with_payload=True).points
    return [{**h.payload, "score": float(h.score)} for h in hits]
