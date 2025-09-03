# src/agents/counter_agent/service.py
from __future__ import annotations

from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, Query
from loguru import logger

from src.schemas.counter import (
    CounterRequest, CounterResponse,
    Weakness, Rebuttal, Opponent, OpponentPoint
)
from src.nlp.ner_keywords import extract_entities_and_keywords
from src.nlp.fallacy import detect_fallacies
from src.llm.provider import LLM
from src.security.auth import require_api_key
from src.security.sanitize import sanitize_text, sanitize_list_str

# ---- IR state (optional global toggle) ----
try:
    from src.ir.state import is_ir_enabled as _global_ir_enabled
except Exception:
    def _global_ir_enabled() -> bool:
        return True

# lazily import retriever only if needed
Retriever = None  # type: ignore

router = APIRouter(dependencies=[Depends(require_api_key)])
_RETRIEVER: Optional[object] = None
_LLM = LLM()


def _resolve_use_ir(qparam: Optional[bool]) -> bool:
    global_on = _global_ir_enabled()
    if qparam is None:
        return bool(global_on)
    return bool(qparam) and bool(global_on)


def _get_retriever_safe():
    global Retriever, _RETRIEVER
    if _RETRIEVER is not None:
        return _RETRIEVER
    try:
        if Retriever is None:
            from src.ir.retriever import Retriever as _R  # type: ignore
            Retriever = _R
        _RETRIEVER = Retriever()
        return _RETRIEVER
    except Exception as e:
        logger.warning(f"IR retriever unavailable in counter-agent; using no-IR mode. ({e})")
        return None


def _clip(s: str, n: int) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else (s[: n - 1].rstrip() + "…")


def _score_point_weakness(point_text: str, citations: List[str]) -> Tuple[float, List[str], List[str]]:
    reasons: List[str] = []
    fallacy_hits = detect_fallacies(point_text or "")
    fallacy_types = [f["type"] for f in fallacy_hits]

    score = 0.0
    if not citations:
        score += 0.5
        reasons.append("No citations attached.")
    elif len(citations) < 2:
        score += 0.2
        reasons.append("Only a single citation; limited evidence breadth.")
    if fallacy_types:
        score += 0.5
        reasons.append(f"Potential fallacies detected: {', '.join(fallacy_types)}.")
    return min(1.0, score), fallacy_types, reasons


def _build_query_terms(motion: str, point_text: str) -> str:
    ents: List[str] = []
    kws: List[str] = []
    try:
        res = extract_entities_and_keywords(point_text) or {}
        ents = list(res.get("entities") or [])
        kws = list(res.get("keywords") or [])
    except Exception:
        pass

    pieces = [motion] + ents[:5] + kws[:5]
    seen = set()
    out: List[str] = []
    for p in pieces:
        p = (p or "").strip()
        low = p.lower()
        if p and low not in seen:
            seen.add(low)
            out.append(p)
    return " ; ".join(out[:10])


def _make_counterclaim_no_ir(motion: str, point_text: str) -> str:
    if _LLM.is_enabled():
        system = "You are a concise debate counter-argument generator."
        user = (
            f"Motion: {motion}\n"
            f"Opponent's claim:\n{point_text}\n\n"
            "Write a short, rigorous counter-argument (2–3 sentences) in a neutral tone, "
            "highlighting caveats, missing assumptions, or contradictory possibilities. "
            "Do not cite or fabricate specific studies; keep it general and careful."
        )
        try:
            return _LLM.complete(system, user, max_tokens=160)
        except Exception as e:
            logger.warning(f"No-IR counterclaim LLM failed; using template. ({e})")
    pt = (point_text or "").replace("\n", " ")
    return (
        f"Although the claim states “{pt[:200]}…”, it abstracts away key conditions and trade-offs; "
        f"outcomes vary by context, implementation quality, and time horizon, so the assertion is overstated."
    )


def _make_improved_argument_no_ir(motion: str) -> str:
    if _LLM.is_enabled():
        system = "You help refine debate claims to be accurate and defensible."
        user = (
            f"Motion: {motion}\n"
            "Propose a stronger, narrower version of the same stance (1–2 sentences) that is cautious and testable, "
            "explicitly acknowledging one limitation."
        )
        try:
            return _LLM.complete(system, user, max_tokens=120)
        except Exception as e:
            logger.warning(f"No-IR improved-argument LLM failed; using template. ({e})")
    return (
        "A more defensible claim narrows the scope to well-defined conditions and identifies assumptions explicitly, "
        "noting that effects can vary across settings and over time."
    )


def _make_counterclaim_ir(point_text: str, retrieved_texts: List[str]) -> str:
    if _LLM.is_enabled():
        system = "You are a concise debate counter-argument generator."
        evid = " ".join([t[:500].replace("\n", " ") for t in retrieved_texts[:2]])
        user = (
            "Opposing claim:\n"
            f"{point_text}\n\n"
            "Use this evidence to craft a short, rigorous counter-argument (2–3 sentences) with a cautious tone. "
            "Do not hallucinate; only use plausible implications of the evidence.\n"
            f"Evidence:\n{evid}\n"
            "Return only the counter-argument paragraph."
        )
        try:
            return _LLM.complete(system, user, max_tokens=160)
        except Exception as e:
            logger.warning(f"LLM counterclaim failed, will use template. ({e})")

    snippets = " ".join([t[:240].replace("\n", " ") for t in retrieved_texts[:2]]) if retrieved_texts else ""
    pt = (point_text or "").replace("\n", " ")
    base = "the available evidence highlights caveats and mixed results"
    tail = f" Specifically: {snippets}" if snippets else ""
    return f"While the opponent claims: “{pt[:200]}…”, {base}.{tail}"


def _make_improved_argument_ir(motion: str, retrieved_texts: List[str]) -> str:
    if _LLM.is_enabled():
        system = "You help refine debate claims to be accurate and defensible."
        support = " ".join([t[:400].replace("\n", " ") for t in retrieved_texts[:2]])
        user = (
            f"Motion: {motion}\n"
            "Using the evidence below, propose a stronger and narrower version of the same stance (1–2 sentences), "
            "explicitly acknowledging any limitations.\n"
            f"Evidence:\n{support}\n"
            "Return only the improved claim."
        )
        try:
            return _LLM.complete(system, user, max_tokens=120)
        except Exception as e:
            logger.warning(f"LLM improved-argument failed, using fallback. ({e})")

    if retrieved_texts:
        support = " ".join([t[:200].replace("\n", " ") for t in retrieved_texts[:1]])
        return (
            f"A more defensible position focuses on the strongest evidence: “{support}”, "
            f"and states assumptions and limitations explicitly."
        )
    return _make_improved_argument_no_ir(motion)


def _normalize_opponent(req: CounterRequest) -> Opponent:
    if getattr(req, "opponent", None):
        opp = req.opponent
        opp.thesis = sanitize_text(opp.thesis) if opp.thesis else None
        for p in opp.points:
            p.text = sanitize_text(p.text)
            p.citations = sanitize_list_str(p.citations)
        return opp

    pts = []
    for p in getattr(req, "opponent_points", []) or []:
        if isinstance(p, str):
            pts.append(OpponentPoint(text=sanitize_text(p), citations=[]))
        else:
            text = sanitize_text(p.get("text")) if isinstance(p, dict) else sanitize_text(str(p))
            citations = sanitize_list_str(p.get("citations", [])) if isinstance(p, dict) else []
            pts.append(OpponentPoint(text=text, citations=citations))
    return Opponent(thesis=None, points=pts)


@router.post("/counter", response_model=CounterResponse)
async def counter_argument(
    req: CounterRequest,
    use_ir: Optional[bool] = Query(default=None, description="Override IR usage for this call"),
) -> CounterResponse:
    resolved_ir = _resolve_use_ir(use_ir)

    clean_motion = sanitize_text(req.motion)
    opponent = _normalize_opponent(req)

    weaknesses: List[Weakness] = []
    rebuttals: List[Rebuttal] = []

    r = _get_retriever_safe() if resolved_ir else None

    for idx, p in enumerate(opponent.points):
        text = p.text or ""
        citations_in = p.citations or []

        weak_score, fallacy_types, reasons = _score_point_weakness(text, citations_in)
        weaknesses.append(
            Weakness(
                target_point_index=idx,
                weakness_score=weak_score,
                fallacies=fallacy_types,
                reasons=reasons,
                evidence_gap=(len(citations_in) == 0),
            )
        )

        cite_ids: List[str] = []
        top_texts: List[str] = []

        if r is not None:
            try:
                query = _build_query_terms(clean_motion, text)
                hits = r.search(query, k=5)  # type: ignore[attr-defined]
                cite_ids = [f"{h.doc_id}#{h.chunk_id}" for h in hits][:10]
                top_texts = [h.text for h in hits]
            except Exception as e:
                logger.warning(f"Retriever search failed in counter-agent: {e}. Proceeding without IR.")
                r = None

        if r is None:
            counterclaim = _make_counterclaim_no_ir(clean_motion, text)
            improved = _make_improved_argument_no_ir(clean_motion)
        else:
            counterclaim = _make_counterclaim_ir(text, top_texts)
            improved = _make_improved_argument_ir(clean_motion, top_texts)

        # Clamp to schema limits (prevent 422/500)
        counterclaim = _clip(counterclaim, 600)
        improved     = _clip(improved, 600)

        rebuttals.append(
            Rebuttal(
                target_point_index=idx,
                counterclaim=counterclaim,
                citations=cite_ids,
                improved_argument=improved,
            )
        )

    return CounterResponse(weaknesses=weaknesses, rebuttals=rebuttals)
