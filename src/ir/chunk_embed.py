from __future__ import annotations

import os
# Hard-disable optional TensorFlow/Flax imports inside transformers
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TRANSFORMERS_NO_FLAX", "1")

import json
from pathlib import Path
from typing import Iterator, List, Dict

import faiss
import numpy as np
from loguru import logger
from sentence_transformers import SentenceTransformer

# Paths
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw_texts"
MANIFEST = RAW_DIR / "manifest.jsonl"

INDEX_DIR = ROOT / "data" / "faiss_index"
INDEX_PATH = INDEX_DIR / "index.faiss"
META_PATH = INDEX_DIR / "meta.jsonl"
CONFIG_PATH = INDEX_DIR / "config.json"

# Model & chunking
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"  # small, fast, free
CHUNK_CHARS = 3500
CHUNK_OVERLAP = 400
BATCH_SIZE = 128


def _iter_manifest() -> Iterator[Dict]:
    """Yield records describing each ingested document."""
    if not MANIFEST.exists():
        raise FileNotFoundError(f"Manifest not found: {MANIFEST} (run: python -m src.ir.ingest)")
    with MANIFEST.open("r", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def _chunk_text(text: str) -> List[str]:
    """Simple character-based chunking with overlap."""
    chunks: List[str] = []
    n = len(text)
    i = 0
    while i < n:
        j = min(i + CHUNK_CHARS, n)
        chunk = text[i:j]
        chunks.append(chunk.strip())
        if j == n:
            break
        i = max(0, j - CHUNK_OVERLAP)  # step back for overlap
    return [c for c in chunks if c]


def build_index() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    # Clean old artifacts so meta stays aligned with vectors
    if META_PATH.exists():
        META_PATH.unlink()
    if INDEX_PATH.exists():
        INDEX_PATH.unlink()

    logger.info(f"Loading embedding model: {EMBED_MODEL}")
    model = SentenceTransformer(EMBED_MODEL)
    dim = model.get_sentence_embedding_dimension()
    logger.info(f"Embedding dimension: {dim}")

    # FAISS inner-product index; we normalize vectors to use cosine similarity
    index = faiss.IndexFlatIP(dim)

    total_meta_rows = 0
    all_vecs: List[np.ndarray] = []

    with META_PATH.open("w", encoding="utf-8") as mf:
        for rec in _iter_manifest():
            doc_id = rec["doc_id"]
            text_path = Path(rec["stored_path"])
            text = text_path.read_text(encoding="utf-8", errors="ignore")

            chunks = _chunk_text(text)
            logger.info(f"{doc_id}: {len(chunks)} chunks")

            for start in range(0, len(chunks), BATCH_SIZE):
                batch = chunks[start : start + BATCH_SIZE]

                # Encode to numpy; show_progress_bar=False keeps logs clean
                vecs: np.ndarray = model.encode(
                    batch,
                    batch_size=min(BATCH_SIZE, 32),
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )

                # L2 normalize for cosine via inner product
                norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
                vecs = (vecs / norms).astype("float32")
                all_vecs.append(vecs)

                # Write metadata aligned with embeddings
                for k, chunk_text in enumerate(batch):
                    meta = {
                        "doc_id": doc_id,
                        "chunk_id": f"{doc_id}_{start + k}",
                        "title": rec.get("title"),
                        "source_path": rec.get("source_path"),
                        "text": chunk_text,
                    }
                    mf.write(json.dumps(meta, ensure_ascii=False) + "\n")
                    total_meta_rows += 1

    if not all_vecs:
        raise RuntimeError(
            "No chunks embedded. Did you run ingest and add files to data/corpus/?"
        )

    mat = np.vstack(all_vecs)  # (N, dim), float32
    logger.info(f"Adding {mat.shape[0]} vectors to FAISS index…")
    index.add(mat)
    faiss.write_index(index, str(INDEX_PATH))

    CONFIG_PATH.write_text(
        json.dumps(
            {"embed_model": EMBED_MODEL, "dim": dim, "metric": "cosine (via inner product)"},
            indent=2,
        ),
        encoding="utf-8",
    )

    logger.success(
        f"Index built: {INDEX_PATH}  | Meta: {META_PATH}  | Count: {total_meta_rows}"
    )


if __name__ == "__main__":
    build_index()
