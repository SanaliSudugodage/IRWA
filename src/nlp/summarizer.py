# src/nlp/summarizer.py
from __future__ import annotations

import os
# Make sure Transformers doesn't try to import TensorFlow/JAX on your machine
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("TRANSFORMERS_NO_FLAX", "1")

from typing import Optional
from loguru import logger
import nltk

# Lightweight extractive fallback
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt")
    try:
        nltk.download("punkt_tab")
    except Exception:
        pass

from nltk.tokenize import sent_tokenize

# Optional abstractive summarizer (uses PyTorch; ~450MB model download the first time)
_SUMMARY_PIPELINE = None

def _get_abstractive_pipeline():
    """Lazy-load a small, reliable summarization pipeline (PyTorch only)."""
    global _SUMMARY_PIPELINE
    if _SUMMARY_PIPELINE is not None:
        return _SUMMARY_PIPELINE

    try:
        from transformers import pipeline  # (PyTorch-only due to env flags above)
        # DistilBART CNN is a good balance of speed/quality
        _SUMMARY_PIPELINE = pipeline(
            "summarization",
            model="sshleifer/distilbart-cnn-12-6",
            device_map="auto",  # runs on CPU or GPU if available
        )
        return _SUMMARY_PIPELINE
    except Exception as e:
        logger.warning(f"Abstractive pipeline unavailable, will use extractive fallback. ({e})")
        return None


def _extractive(text: str, max_tokens: int = 120) -> str:
    """
    Super-simple extractive fallback:
    - Split into sentences
    - Keep the first N sentences until roughly max_tokens (word-based)
    """
    sents = [s.strip() for s in sent_tokenize(text) if s.strip()]
    if not sents:
        return text

    chosen = []
    count = 0
    for s in sents:
        w = len(s.split())
        if count + w > max_tokens and chosen:
            break
        chosen.append(s)
        count += w
    return " ".join(chosen)


def summarize(text: str, max_tokens: int = 120, abstractive: bool = True) -> str:
    """
    Summarize text to ~max_tokens words.
    - If the Transformers pipeline is available, do an abstractive summary.
    - Otherwise, fall back to simple extractive approach.
    """
    text = (text or "").strip()
    if not text:
        return ""

    if abstractive:
        pipe = _get_abstractive_pipeline()
        if pipe is not None:
            # Rough mapping: words -> tokens; be conservative
            # DistilBART is trained on news; we bound length with min/max
            try:
                # Heuristic: ~1.3 tokens per word. Keep output short.
                max_chars = max(100, min(1000, max_tokens * 7))
                # Many pipelines accept max_length/min_length; use char clipping for safety
                in_text = text[:4000]  # prevent very long prompts from being slow
                out = pipe(
                    in_text,
                    max_length=200,   # ~ 200 tokens (BPE), concise paragraph
                    min_length=30,
                    do_sample=False,
                )
                candidate = out[0]["summary_text"].strip()
                # Trim to ~max_tokens words just in case
                words = candidate.split()
                if len(words) > max_tokens:
                    candidate = " ".join(words[:max_tokens])
                return candidate
            except Exception as e:
                logger.warning(f"Abstractive summarization failed, fallback to extractive. ({e})")

    return _extractive(text, max_tokens=max_tokens)


if __name__ == "__main__":
    demo = (
        "Universal Basic Income (UBI) proposes giving all citizens a regular, "
        "unconditional cash payment. Proponents argue it reduces poverty, "
        "simplifies welfare, and supports people as automation changes labor markets. "
        "Critics worry about costs, inflation, and potential disincentives to work. "
        "Multiple pilots worldwide suggest improvements in well-being and financial stability, "
        "but long-term macroeconomic effects remain debated."
    )
    print(summarize(demo, max_tokens=60, abstractive=True))
