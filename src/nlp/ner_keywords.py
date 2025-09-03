from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Tuple

import spacy
from loguru import logger
from sklearn.feature_extraction.text import TfidfVectorizer

# Export only the function the tests import
__all__ = ["extract_entities_and_keywords"]

# Try to load spaCy 'en_core_web_sm'; fall back to a blank English pipeline
try:
    _NLP = spacy.load("en_core_web_sm")
    logger.info("spaCy model 'en_core_web_sm' loaded.")
except Exception:
    logger.warning(
        "spaCy model 'en_core_web_sm' not found. Using a blank English pipeline (NER disabled). "
        "Install with: python -m spacy download en_core_web_sm"
    )
    _NLP = spacy.blank("en")
    if "sentencizer" not in _NLP.pipe_names:
        _NLP.add_pipe("sentencizer")


def _simple_tokens(text: str) -> List[str]:
    """Very light tokenizer used for TF-IDF fallback."""
    # Lowercase, keep letters/numbers, split on non-word
    words = re.findall(r"[A-Za-z][A-Za-z0-9\-']{2,}", text.lower())
    return words


def _tfidf_keywords(text: str, top_k: int = 10) -> List[str]:
    """Extract top keywords using TF-IDF on a single doc vs itself (ok for short docs)."""
    tokens = " ".join(_simple_tokens(text))
    if not tokens.strip():
        return []
    vec = TfidfVectorizer(ngram_range=(1, 2), max_features=5000, stop_words="english")
    X = vec.fit_transform([tokens])
    scores = X.toarray()[0]
    feats = vec.get_feature_names_out()
    pairs: List[Tuple[str, float]] = list(zip(feats, scores))
    pairs.sort(key=lambda x: x[1], reverse=True)
    return [w for w, _ in pairs[:top_k]]


def extract_entities_and_keywords(text: str, top_k: int = 10) -> Dict[str, List[str]]:
   
    entities: List[str] = []

    # If NER is available (not blank), get entities
    if "ner" in _NLP.pipe_names:
        doc = _NLP(text)
        # Keep common, debate-relevant entity types
        allowed = {"PERSON", "ORG", "GPE", "LOC", "NORP", "EVENT", "WORK_OF_ART", "LAW", "LANGUAGE"}
        for ent in doc.ents:
            if ent.label_ in allowed:
                entities.append(ent.text)

        # De-duplicate while preserving order
        seen = set()
        entities = [e for e in entities if not (e in seen or seen.add(e))]
    else:
        entities = []

    # Keywords via TF-IDF fallback (works whether NER available or not)
    keywords = _tfidf_keywords(text, top_k=top_k)

    # If we have many entities and few keywords, add most frequent capitalized tokens as hints
    if len(keywords) < max(3, top_k // 2):
        # crude boost for capitalized tokens (titles, names)
        caps = re.findall(r"\b([A-Z][a-zA-Z0-9\-']{2,}(?:\s+[A-Z][a-zA-Z0-9\-']{2,})*)\b", text)
        for cand, _ in Counter(caps).most_common(5):
            if cand not in entities and cand.lower() not in (k.lower() for k in keywords):
                keywords.append(cand)
                if len(keywords) >= top_k:
                    break

    return {"entities": entities, "keywords": keywords}


if __name__ == "__main__":
    sample = (
        "Debate: Should we implement Universal Basic Income (UBI) in the United States? "
        "According to the Stanford Basic Income Lab and the IMF, pilots in Stockton and Finland "
        "reported mixed labor market effects but positive well-being outcomes."
    )
    out = extract_entities_and_keywords(sample, top_k=8)
    print(out)
