"""Build (or rebuild) the Qdrant index from the frozen records. Run from the repo folder:
    py -m rag_lab.build_index
"""
import time

from dotenv import load_dotenv

from rag_lab.chunking import all_chunks
from rag_lab.store import COLLECTION, build_index, embed_model

if __name__ == "__main__":
    load_dotenv()
    t0 = time.time()
    chunks = all_chunks()
    n = build_index(chunks)
    print(f"Indexed {n} chunks into '{COLLECTION}' with {embed_model()} in {time.time() - t0:.0f} s")
