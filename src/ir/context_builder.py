# src/ir/context_builder.py
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Dict, Tuple

from loguru import logger

# Reuse the Passage type from retriever without circular import
# (you can also define a tiny Protocol if you prefer)
@dataclass
class PassageLite:
    doc_id: str
    chunk_id: str
    title: str | None
    source_path: str | None
    text: str
    score: float


def _clean_text(text: str) -> str:
    # Basic cleanup: normalize whitespace, squash long spaces
    text = text.replace("\r", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def build_context(
    passages: List[PassageLite],
    max_chars: int = 4000,
    include_scores: bool = False,
) -> Tuple[str, Dict[str, Dict[str, str]]]:
    """
    Returns:
      context_str: concatenation of top passages with citations.
      citations: { citation_id: {"title": str, "source_path": str or "", "doc_id": str, "chunk_id": str} }
    """
    ctx_parts: List[str] = []
    citations: Dict[str, Dict[str, str]] = {}

    used = 0
    for p in passages:
        cit = f"[doc:{p.doc_id}#{p.chunk_id}]"
        cleaned = _clean_text(p.text)
        entry = cleaned
        if include_scores:
            entry = f"(score={p.score:.3f}) {entry}"
        entry = f"{entry} {cit}"

        if used + len(entry) + 2 > max_chars:
            logger.debug("Context budget reached; stopping.")
            break

        ctx_parts.append(entry)
        used += len(entry) + 2  # account for \n\n
        citations[cit] = {
            "title": p.title or "",
            "source_path": p.source_path or "",
            "doc_id": p.doc_id,
            "chunk_id": p.chunk_id,
        }

    context_str = "\n\n".join(ctx_parts)
    logger.info(f"Built context: {len(context_str)} chars, {len(ctx_parts)} passages, {len(citations)} citations")
    return context_str, citations


# Tiny demo when run directly
if __name__ == "__main__":
    from src.ir.retriever import Retriever  # local import to avoid circulars

    r = Retriever()
    hits = r.search("what is universal basic income", k=5)
    # Adapt hits into PassageLite
    pl = [
        PassageLite(
            doc_id=h.doc_id,
            chunk_id=h.chunk_id,
            title=h.title,
            source_path=h.source_path,
            text=h.text,
            score=h.score,
        )
        for h in hits
    ]
    ctx, cits = build_context(pl, max_chars=1500, include_scores=True)
    print("=== CONTEXT ===")
    print(ctx[:1000] + ("…" if len(ctx) > 1000 else ""))
    print("\n=== CITATIONS ===")
    for k, v in cits.items():
        print(k, "->", v)
