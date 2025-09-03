# src/agents/argument_generator/service.py
from __future__ import annotations

from typing import List, Optional
from fastapi import APIRouter, Response, Depends, Query
from loguru import logger

from src.schemas.argument import ArgumentRequest, ArgumentResponse, ArgumentPoint
from src.nlp.ner_keywords import extract_entities_and_keywords
from src.nlp.summarizer import summarize
from src.llm.provider import LLM
from src.security.auth import require_api_key
from src.security.sanitize import sanitize_text

# ---- IR state (optional global toggle) ----
try:
    # your src/ir/state.py should expose is_ir_enabled()
    from src.ir.state import is_ir_enabled as _global_ir_enabled
except Exception:
    def _global_ir_enabled() -> bool:
        return True

# Lazily import Retriever only if we end up using IR
Retriever = None  # type: ignore

router = APIRouter(dependencies=[Depends(require_api_key)])

_llm = LLM()
_retriever = None  # lazy singleton


def _resolve_use_ir(qparam: Optional[bool]) -> bool:
    """
    If caller provides use_ir, honor it but don't override a global OFF.
    Otherwise follow the global toggle.
    """
    global_on = _global_ir_enabled()
    if qparam is None:
        return bool(global_on)
    return bool(qparam) and bool(global_on)


def _get_retriever_safe():
    """Return a retriever instance or None if the index isn't available."""
    global Retriever, _retriever
    if _retriever is not None:
        return _retriever
    try:
        if Retriever is None:
            from src.ir.retriever import Retriever as _R  # type: ignore
            Retriever = _R
        _retriever = Retriever()
        logger.info("ArgumentGenerator: retriever initialized")
        return _retriever
    except Exception as e:
        logger.warning(f"IR retriever unavailable; using no-IR mode. ({e})")
        return None


def _build_query_terms(motion: str, stance: str | None) -> List[str]:
    ents: List[str] = []
    kws: List[str] = []
    try:
        res = extract_entities_and_keywords(motion) or {}
        ents = list(res.get("entities") or [])
        kws = list(res.get("keywords") or [])
    except Exception:
        pass

    base = [motion] + ([stance] if stance else [])
    seen = set()
    out: List[str] = []
    for t in base + ents + kws:
        t = (t or "").strip()
        low = t.lower()
        if len(t) > 1 and low not in seen:
            seen.add(low)
            out.append(t)
    return out[:8]


def _make_points_ir(motion: str, stance: str | None, max_points: int = 3) -> List[ArgumentPoint]:
    r = _get_retriever_safe()
    if r is None:
        # No index → fall back
        return _make_points_no_ir(motion, stance, max_points=max_points)

    terms = _build_query_terms(motion, stance)
    logger.debug(f"[IR] query terms: {terms}")

    pool = []
    seen = set()
    for q in terms:
        try:
            hits = r.search(q, k=4)  # type: ignore[attr-defined]
        except Exception as e:
            logger.warning(f"Retriever.search failed ({e}); switching to no-IR mode.")
            return _make_points_no_ir(motion, stance, max_points=max_points)
        for h in hits:
            if h.chunk_id in seen:
                continue
            seen.add(h.chunk_id)
            pool.append(h)

    if not pool:
        logger.info("IR returned no passages; falling back to no-IR generation.")
        return _make_points_no_ir(motion, stance, max_points=max_points)

    pool.sort(key=lambda x: x.score, reverse=True)
    points: List[ArgumentPoint] = []
    for p in pool[:max_points]:
        claim: Optional[str] = None

        if _llm.is_enabled():
            system = "You are a debate assistant. Write one concise factual claim using ONLY the provided evidence."
            user = (
                f"Motion: {motion}\n"
                f"Stance: {stance or '(unspecified)'}\n\n"
                f"Evidence passage:\n{p.text}\n\n"
                "Constraints:\n- One sentence\n- 25–45 words\n- Neutral tone\n- Avoid speculation\n"
            )
            try:
                claim = _llm.complete(system=system, user=user, max_tokens=70)
            except Exception as e:
                logger.warning(f"LLM generation failed, will summarize evidence. ({e})")

        if not claim:
            claim = summarize(p.text, max_tokens=60) or (p.text or "").strip().split("\n")[0][:220]

        points.append(ArgumentPoint(text=claim, citations=[f"{p.doc_id}#{p.chunk_id}"]))

    return points


def _make_points_no_ir(motion: str, stance: str | None, max_points: int = 3) -> List[ArgumentPoint]:
    """LLM-only path when IR is off or corpus is thin."""
    if _llm.is_enabled():
        system = "You are a concise debate assistant."
        user = (
            f"Motion: {motion}\n"
            f"Stance: {stance or '(unspecified)'}\n\n"
            "Write 3 separate one-sentence claims (25–40 words each) that someone on this stance could make.\n"
            "Neutral, evidence-aware tone. Avoid exaggeration. No numbering—one claim per line."
        )
        try:
            txt = _llm.complete(system, user, max_tokens=200) or ""
            lines = [ln.strip("-• \t") for ln in txt.splitlines() if ln.strip()]
            out: List[ArgumentPoint] = []
            for ln in lines:
                if len(out) >= max_points:
                    break
                s = ln.strip()
                if len(s) > 280:
                    s = s[:277].rstrip() + "…"
                out.append(ArgumentPoint(text=s, citations=[]))
            if out:
                return out
        except Exception as e:
            logger.warning(f"No-IR LLM generation failed, using summarizer fallback. ({e})")

    # tiny fallback from motion text
    try:
        res = extract_entities_and_keywords(motion) or {}
        kws = list(res.get("keywords") or [])[:5]
    except Exception:
        kws = []
    base = summarize(motion, max_tokens=18) or motion
    out = []
    for i in range(max_points):
        extra = f" This considers {', '.join(kws[:2])}." if i == 1 and kws else ""
        s = (base + extra).strip()
        if len(s) > 280:
            s = s[:277].rstrip() + "…"
        out.append(ArgumentPoint(text=s, citations=[]))
    return out


@router.post("/argument", response_model=ArgumentResponse)
async def generate_argument(
    req: ArgumentRequest,
    response: Response,
    use_ir: Optional[bool] = Query(default=None, description="Override IR usage for this call"),
) -> ArgumentResponse:
    motion = sanitize_text(req.motion)
    stance = sanitize_text(req.stance) if req.stance else None

    resolved_ir = _resolve_use_ir(use_ir)
    points = _make_points_ir(motion, stance) if resolved_ir else _make_points_no_ir(motion, stance)

    thesis = f"Position on: {motion}" + (f" ({stance})" if stance else "")
    response.headers["x-llm-provider"] = _llm.cfg.provider or "none"
    response.headers["x-llm-model"] = _llm.cfg.model or "none"
    response.headers["x-llm-enabled"] = "true" if _llm.is_enabled() else "false"
    response.headers["x-ir-used"] = "true" if resolved_ir else "false"

    return ArgumentResponse(thesis=thesis, points=points)
