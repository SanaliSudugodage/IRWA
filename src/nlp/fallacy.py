# src/nlp/fallacy.py
from __future__ import annotations
from typing import List, Dict
import re

# Simple pattern bag. These are heuristic and conservative.
_PATTERNS = [
    {
        "type": "Ad Hominem",
        "regex": r"\b(you are|he is|she is|they are)\s+(an?\s+)?(idiot|stupid|liar|ignorant|incompetent)\b",
        "why": "Attacks the person rather than the argument.",
    },
    {
        "type": "Strawman",
        "regex": r"\b(so you’re saying|so you are saying|you claim that).*?\b(always|never|everyone|no one)\b",
        "why": "Misrepresents opponent’s position to make it easier to attack.",
    },
    {
        "type": "Slippery Slope",
        "regex": r"\b(if|once)\b.*\bthen\b.*\bthen\b",
        "why": "Asserts chain of events without justification.",
    },
    {
        "type": "False Dilemma",
        "regex": r"\b(either|only)\b.*\bor\b.*\b(no other|nothing else|the only)\b",
        "why": "Presents limited choices as the only possibilities.",
    },
    {
        "type": "Appeal to Authority",
        "regex": r"\b(according to|as|per)\s+[A-Z][a-z]+(\s[A-Z][a-z]+)*\b.*\b(thus|therefore|prove|proves)\b",
        "why": "Uses authority as definitive proof without evidence.",
    },
    {
        "type": "Hasty Generalization",
        "regex": r"\b(always|never|everyone|no one|all of them|none of them)\b",
        "why": "Generalizes from insufficient examples.",
    },
]

def detect_fallacies(text: str) -> List[Dict[str, str]]:
    flags: List[Dict[str, str]] = []
    for rule in _PATTERNS:
        for m in re.finditer(rule["regex"], text, flags=re.IGNORECASE | re.DOTALL):
            span = text[max(0, m.start()-40): m.end()+40].replace("\n", " ")
            flags.append({
                "type": rule["type"],
                "rationale": rule["why"],
                "span": span.strip(),
            })
    # Deduplicate by (type, span)
    seen = set()
    uniq = []
    for f in flags:
        key = (f["type"], f["span"])
        if key not in seen:
            uniq.append(f)
            seen.add(key)
    return uniq

if __name__ == "__main__":
    demo = (
        "Either you accept UBI or you hate poor people. According to Dr. Smith, therefore UBI must work. "
        "Once we give UBI, then people will stop working, then the economy collapses."
    )
    for f in detect_fallacies(demo):
        print(f)
