# tests/test_ner_keywords.py
from __future__ import annotations

from src.nlp.ner_keywords import extract_entities_and_keywords


def test_extract_entities_and_keywords_smoke():
    text = (
        "Debate on Universal Basic Income in the United States. "
        "Stanford Basic Income Lab mentions pilots in Finland and Stockton."
    )
    out = extract_entities_and_keywords(text, top_k=8)

    assert "entities" in out and "keywords" in out
    assert isinstance(out["entities"], list)
    assert isinstance(out["keywords"], list)
    # We expect at least a couple of keywords from TF-IDF fallback
    assert len(out["keywords"]) >= 2

#########################
