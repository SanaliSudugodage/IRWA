from __future__ import annotations

import os
# Hard-disable optional TensorFlow/Flax imports inside transformers
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TRANSFORMERS_NO_FLAX", "1")

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict

import faiss
import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer

# Paths
ROOT = Path(__file__).resolve().parents[2]
INDEX_DIR = ROOT / "data" / "faiss_index"
INDEX_PATH = INDEX_DIR / "index.faiss"
META_PATH = INDEX_DIR / "meta.jsonl"
CONFIG_PATH = INDEX_DIR / "config.json"


@dataclass
class Passage:
    doc_id: str
    chunk_id: str
    title: str | None
    source_path: str | None
    text: str
    score: float


class Retriever:
    def __init__(self) -> None:
        if not INDEX_PATH.exists() or not META_PATH.exists() or not CONFIG_PATH.exists():
            raise FileNotFoundError(
                "Index or metadata not found. Run: python -m src.ir.chunk_embed"
            )

        self.index = faiss.read_index(str(INDEX_PATH))
        self.config: Dict = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.model = SentenceTransformer(self.config["embed_model"])

        # Load metadata rows (aligned with the index order used when adding)
        self._meta: List[Dict] = []
        with META_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                self._meta.append(json.loads(line))
        logger.info(f"Retriever ready. Passages: {len(self._meta)}")

    def search(self, query: str, k: int = 5) -> List[Passage]:
        """Return top-k passages for a query using cosine similarity (via IP)."""
        emb = self.model.encode([query], convert_to_numpy=True).astype("float32")
        emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-12)

        D, I = self.index.search(emb, k)
        scores = D[0]
        idxs = I[0]

        results: List[Passage] = []
        for score, idx in zip(scores, idxs):
            if idx < 0 or idx >= len(self._meta):
                continue
            m = self._meta[idx]
            results.append(
                Passage(
                    doc_id=m["doc_id"],
                    chunk_id=m["chunk_id"],
                    title=m.get("title"),
                    source_path=m.get("source_path"),
                    text=m["text"],
                    score=float(score),
                )
            )
        return results


# Simple CLI smoke test
if __name__ == "__main__":
    r = Retriever()
    hits = r.search("what is universal basic income", k=3)
    for h in hits:
        snippet = h.text.replace("\n", " ").strip()[:120]
        print(f"{h.score:0.3f}  [{h.doc_id}#{h.chunk_id}] {h.title}  -> {snippet}…")
