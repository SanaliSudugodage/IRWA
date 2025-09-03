# src/agents/evaluation_agent/service.py
from __future__ import annotations

import os
from typing import List, Tuple
from fastapi import APIRouter, Depends
from loguru import logger

from src.schemas.judge import JudgeRequest, JudgeResponse, CriterionScore
from src.schemas.argument import ArgumentPoint

# NLP helpers (may rely on spaCy)
try:
    from src.nlp.ner_keywords import extract_entities_and_keywords
except Exception:
    extract_entities_and_keywords = None  # guard if module fails to import

from src.nlp.fallacy import detect_fallacies
from src.llm.provider import LLM
from src.security.auth import require_api_key
from src.security.sanitize import sanitize_text

router = APIRouter(dependencies=[Depends(require_api_key)])
FAST_MODE = os.getenv("DEBATE_FAST", "0") == "1"
_LLM = LLM()

# ---------- small helpers

def _text_of(points: List[ArgumentPoint]) -> str:
    return " ".join([(p.text or "") for p in points]).strip()

def _unique_citations(points: List[ArgumentPoint]) -> List[str]:
    seen = set()
    out: List[str] = []
    for p in points:
        for c in (p.citations or []):
            key = c.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(c)
    return out

def _pick_span_with_citation(points: List[ArgumentPoint]) -> Tuple[str, str]:
    for p in points:
        if p.citations:
            span = (p.text or "").replace("\n", " ")[:140]
            return span, p.citations[0]
    if points:
        return (points[0].text or "").replace("\n", " ")[:140], ""
    return "", ""

def _split_sentences(text: str) -> List[str]:
    parts = []
    for seg in text.replace("\n", " ").split("."):
        seg = seg.strip()
        if seg:
            parts.append(seg)
    return parts

def _keyword_fallback(text: str) -> List[str]:
    tokens = [t.strip(",;:()[]{}'\" ").lower() for t in text.split()]
    return [t for t in tokens if len(t) >= 4][:20]

# ---------- rubric (0–5 each)

def _score_relevance(motion: str, points: List[ArgumentPoint]) -> Tuple[int, str]:
    key_terms = set()
    if not FAST_MODE and extract_entities_and_keywords is not None:
        try:
            ents, kws = extract_entities_and_keywords(motion)
            if not isinstance(ents, list):
                ents = [ents] if ents else []
            if not isinstance(kws, list):
                kws = [kws] if kws else []
            key_terms |= {str(e).lower() for e in ents if e}
            key_terms |= {str(k).lower() for k in kws if k}
        except Exception as e:
            logger.warning(f"NER keywords unavailable, using fallback: {e}")
            key_terms |= set(_keyword_fallback(motion))
    else:
        key_terms |= set(_keyword_fallback(motion))

    body = (_text_of(points) + " " + motion).lower()
    if not key_terms:
        return 3, "Motion had few extractable keywords; defaulting to mid score."

    hits = sum(1 for k in key_terms if k and k in body)
    ratio = hits / max(1, len(key_terms))
    score = round(5 * ratio)
    span, cit = _pick_span_with_citation(points)
    expl = f"Matched {hits}/{len(key_terms)} motion terms in the argument. Example: “{span}”" + (f" [{cit}]" if cit else "")
    return int(score), expl

def _score_logic(points: List[ArgumentPoint]) -> Tuple[int, str]:
    text = _text_of(points)
    hits = detect_fallacies(text)
    kinds = sorted({h["type"] for h in hits})
    score = max(0, 5 - len(kinds))
    span = hits[0]["span"][:120].replace("\n", " ") if hits else ""
    expl = ("No obvious fallacies detected." if not kinds else f"Potential fallacies: {', '.join(kinds)}.") + (f" Example: “{span}”" if span else "")
    return int(score), expl

def _score_evidence(points: List[ArgumentPoint]) -> Tuple[int, str]:
    uniq = _unique_citations(points)
    per_point = [len(p.citations or []) for p in points]
    breadth = sum(1 for n in per_point if n > 0)
    diversity = len(uniq)

    if diversity >= 6 and breadth >= min(3, len(points)):
        score = 5
    elif diversity >= 4 and breadth >= 2:
        score = 4
    elif diversity >= 2 and breadth >= 1:
        score = 3
    elif diversity >= 1:
        score = 2
    else:
        score = 1

    span, cit = _pick_span_with_citation(points)
    expl = f"{diversity} unique citation(s) across {breadth}/{len(points)} point(s). " + (f"Example: “{span}” [{cit}]" if cit else "No citation examples found.")
    return int(score), expl

def _score_clarity(points: List[ArgumentPoint]) -> Tuple[int, str]:
    sents = _split_sentences(_text_of(points))
    if not sents:
        return 1, "No sentences detected; unclear."
    avg_len = sum(len(s) for s in sents) / len(sents)
    if   avg_len <= 120: score = 5
    elif avg_len <= 160: score = 4
    elif avg_len <= 200: score = 3
    elif avg_len <= 260: score = 2
    else:                score = 1
    span, cit = _pick_span_with_citation(points)
    expl = f"Avg sentence length ≈ {avg_len:.0f} chars. Example: “{span}”" + (f" [{cit}]" if cit else "")
    return int(score), expl

def _score_fairness(points: List[ArgumentPoint]) -> Tuple[int, str]:
    text = _text_of(points).lower()
    hedges = ["however", "although", "on the other hand", "while", "despite", "limitations"]
    ack = sum(1 for t in hedges if t in text)
    ad_hominem = any(t in text for t in ["idiot", "stupid", "liar"])
    base = 3 + min(2, ack)
    if ad_hominem:
        base = max(0, base - 2)
    score = max(0, min(5, base))
    span, cit = _pick_span_with_citation(points)
    expl = (
        ("Shows nuance with hedging; " if ack else "Little acknowledgement of limitations; ")
        + ("penalized for ad hominem. " if ad_hominem else "no ad hominem. ")
        + (f"Example: “{span}”" + (f" [{cit}]" if cit else "") if span else "")
    )
    return int(score), expl

def _judge_side(motion: str, points: List[ArgumentPoint]) -> List[CriterionScore]:
    r1, e1 = _score_relevance(motion, points)
    r2, e2 = _score_logic(points)
    r3, e3 = _score_evidence(points)
    r4, e4 = _score_clarity(points)
    r5, e5 = _score_fairness(points)
    return [
        CriterionScore(name="Relevance",          score=r1, explanation=e1),
        CriterionScore(name="Logical Soundness",  score=r2, explanation=e2),
        CriterionScore(name="Evidence Quality",   score=r3, explanation=e3),
        CriterionScore(name="Clarity",            score=r4, explanation=e4),
        CriterionScore(name="Fairness",           score=r5, explanation=e5),
    ]

def _total(scores: List[CriterionScore]) -> float:
    return float(sum(s.score for s in scores))

def _feedback(points: List[ArgumentPoint]) -> List[str]:
    tips: List[str] = []
    uniq = _unique_citations(points)
    if len(uniq) < 3:
        tips.append("Add more diverse citations; support each key claim.")
    sents = _split_sentences(_text_of(points))
    if sents and (sum(len(s) for s in sents) / len(sents)) > 180:
        tips.append("Break up long sentences; add signposting (first, second, therefore).")
    falls = detect_fallacies(_text_of(points))
    if falls:
        tips.append("Address potential logical issues flagged by heuristics.")
    if not tips:
        tips.append("Good structure; keep explicit assumptions and citations.")
    return tips

def _tie_breaker_det(pro_points: List[ArgumentPoint], con_points: List[ArgumentPoint]) -> tuple[str, str]:
    pro_c = len(_unique_citations(pro_points))
    con_c = len(_unique_citations(con_points))
    if pro_c != con_c:
        return ("pro" if pro_c > con_c else "con", f"Tie-break by citation diversity: pro={pro_c}, con={con_c}.")
    pro_supported = sum(1 for p in pro_points if p.citations)
    con_supported = sum(1 for p in con_points if p.citations)
    if pro_supported != con_supported:
        return ("pro" if pro_supported > con_supported else "con", f"Tie-break by supported points: pro={pro_supported}, con={con_supported}.")
    return ("pro", "Tie remained; deterministic fallback to 'pro'.")

def _tie_breaker_llm(motion: str, pro_points: List[ArgumentPoint], con_points: List[ArgumentPoint]) -> tuple[str, str]:
    if not _LLM.is_enabled():
        return _tie_breaker_det(pro_points, con_points)

    system = "You are a fair, terse debate judge. Pick a winner strictly based on evidence and logic."
    def short(ps: List[ArgumentPoint]) -> str:
        return "\n".join([f"- {p.text[:180]}" for p in ps[:3]])
    user = (
        f"Motion: {motion}\n\n"
        f"Pro points:\n{short(pro_points)}\n\n"
        f"Con points:\n{short(con_points)}\n\n"
        "Return exactly two lines:\n"
        "winner: pro|con\n"
        "reason: <one concise sentence>\n"
    )
    try:
        out = _LLM.complete(system, user, max_tokens=60) or ""
        low = out.lower()
        if "winner: con" in low:
            return ("con", out.strip())
        elif "winner: pro" in low:
            return ("pro", out.strip())
        else:
            logger.warning(f"LLM tie-break ambiguous, fallback. Output: {out!r}")
            return _tie_breaker_det(pro_points, con_points)
    except Exception as e:
        logger.warning(f"LLM tie-break failed, fallback: {e}")
        return _tie_breaker_det(pro_points, con_points)

def _refine_explanations_with_llm(motion: str, points: List[ArgumentPoint], scores: List[CriterionScore]) -> List[CriterionScore]:
    if not _LLM.is_enabled():
        return scores
    try:
        system = "You are a concise technical writer who polishes justifications for a debate scorecard."
        body = "\n".join([f"{s.name}: {s.explanation}" for s in scores])
        sample = "\n".join([f"- {p.text[:150]}" for p in points[:3]])
        user = (
            f"Motion: {motion}\n"
            f"Sample points:\n{sample}\n\n"
            "Rewrite each explanation to be one tight sentence, avoiding fluff, preserving meaning:\n"
            f"{body}\n"
            "Return the same five lines in the same order, unchanged labels."
        )
        out = _LLM.complete(system, user, max_tokens=150) or ""
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        if len(lines) >= 5:
            new_scores: List[CriterionScore] = []
            for s, line in zip(scores, lines[:5]):
                # drop 'Relevance:' etc if present
                if ":" in line:
                    line = line.split(":", 1)[1].strip()
                if len(line) < 5:
                    line = s.explanation
                new_scores.append(CriterionScore(name=s.name, score=s.score, explanation=line))
            return new_scores
        return scores
    except Exception as e:
        logger.warning(f"LLM refine explanations failed, keeping originals: {e}")
        return scores

# ---------- route

@router.post("/judge", response_model=JudgeResponse)
def judge(req: JudgeRequest) -> JudgeResponse:
    logger.info("Judge evaluating debate round...")

    # sanitize inputs
    req.motion = sanitize_text(req.motion)
    req.pro.thesis = sanitize_text(req.pro.thesis)
    req.con.thesis = sanitize_text(req.con.thesis)
    for p in req.pro.points + req.con.points:
        p.text = sanitize_text(p.text)
        p.citations = [sanitize_text(c) for c in p.citations]

    pro_scores = _judge_side(req.motion, req.pro.points)
    con_scores = _judge_side(req.motion, req.con.points)

    # optional LLM polish of explanations (safe)
    pro_scores = _refine_explanations_with_llm(req.motion, req.pro.points, pro_scores)
    con_scores = _refine_explanations_with_llm(req.motion, req.con.points, con_scores)

    pro_total = _total(pro_scores)
    con_total = _total(con_scores)

    if abs(pro_total - con_total) < 1e-6:
        winner, tie_msg = _tie_breaker_llm(req.motion, req.pro.points, req.con.points)
    else:
        winner = "pro" if pro_total > con_total else "con"
        tie_msg = None

    return JudgeResponse(
        pro_breakdown=pro_scores,
        con_breakdown=con_scores,
        pro_total=pro_total,
        con_total=con_total,
        winner=winner,
        tie_breaker=tie_msg,
        feedback_pro=_feedback(req.pro.points),
        feedback_con=_feedback(req.con.points),
    )
