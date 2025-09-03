# src/orchestrator/debate_flow.py
from __future__ import annotations

import os
import json
import time
import uuid
from typing import List, Literal, Optional
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Query
from loguru import logger

from src.schemas.debate import (
    DebateRunRequest,
    DebateReport,
    DebateSettings,
    TurnItem,
    TurnScores,
    DebateScoreboard,
    ScoreDetail,
)
from src.schemas.argument import ArgumentPoint, ArgumentResponse
from src.schemas.counter import CounterRequest, Opponent, OpponentPoint
from src.schemas.judge import JudgeRequest, SideArgument
from src.llm.provider import LLM
from src.security.auth import require_api_key
from src.security.sanitize import sanitize_text

# Read global IR toggle (safe fallback)
try:
    from src.ir.state import is_ir_enabled
except Exception:

    def is_ir_enabled() -> bool:
        return False


router = APIRouter(dependencies=[Depends(require_api_key)])

BASE_URL = os.getenv("DEBATE_BASE_URL", "http://127.0.0.1:8000")
RUNS_DIR = Path("data/runs")
RUNS_DIR.mkdir(parents=True, exist_ok=True)

# ---- Bigger internal timeout so long LLM+IR calls don’t 504 ----
# You can override via env: DEBATE_INTERNAL_TIMEOUT=180
_REQUEST_TIMEOUT = float(os.getenv("DEBATE_INTERNAL_TIMEOUT", "180"))
_TIMEOUT = httpx.Timeout(
    connect=120.0,
    read=_REQUEST_TIMEOUT,
    write=_REQUEST_TIMEOUT,
    pool=_REQUEST_TIMEOUT,
)

_LLM = LLM()

# ---- In-memory cancellation flags keyed by request_id ----
CANCEL_FLAGS: dict[str, bool] = {}


#Checks if the user has asked to stop this debate run. Returns True if the flag is set.
def _is_cancelled(request_id: Optional[str]) -> bool:
    return bool(request_id) and bool(CANCEL_FLAGS.get(request_id))



def _clear_cancel(request_id: Optional[str]) -> None:
    if request_id:
        CANCEL_FLAGS.pop(request_id, None)

#Converts the counter-agent’s JSON into a list of ArgumentPoints. If nothing came back, returns a single “no counter generated” placeholder
def _points_from_counter(counter_json: dict) -> List[ArgumentPoint]:
    pts: List[ArgumentPoint] = []
    for rb in counter_json.get("rebuttals", []):
        pts.append(
            ArgumentPoint(
                text=str(rb.get("counterclaim", ""))[:1000],
                citations=list(rb.get("citations", []))[:10],
            )
        )
    if not pts:
        pts = [ArgumentPoint(text="(no counter generated)", citations=[])]
    return pts


def _mk_side_argument(thesis: str, points: List[ArgumentPoint]) -> SideArgument:
    return SideArgument(thesis=thesis or "", points=points)

#Adds up the numeric score fields from the judge’s criterion breakdown. Used to compute totals quickly.
def _sum_scores(d: List[dict]) -> int:
    return int(sum(int(x.get("score", 0)) for x in d))

#Takes the judge’s detailed JSON and builds a typed TurnScores object for pro and con (relevance, logic, evidence, clarity, fairness, total)
def _pack_turn_scores(judge_resp: dict) -> TurnScores:
    pro_scores = judge_resp["pro_breakdown"]
    con_scores = judge_resp["con_breakdown"]
    return TurnScores(
        pro=ScoreDetail(
            relevance=pro_scores[0]["score"],
            logic=pro_scores[1]["score"],
            evidence=pro_scores[2]["score"],
            clarity=pro_scores[3]["score"],
            fairness=pro_scores[4]["score"],
            total=_sum_scores(pro_scores),
        ),
        con=ScoreDetail(
            relevance=con_scores[0]["score"],
            logic=con_scores[1]["score"],
            evidence=con_scores[2]["score"],
            clarity=con_scores[3]["score"],
            fairness=con_scores[4]["score"],
            total=_sum_scores(con_scores),
        ),
    )

#Compares pro vs con totals for the turn and returns "pro", "con", or "tie". Tiny tie tolerance avoids float weirdness
def _pick_turn_winner(judge_resp: dict) -> Literal["pro", "con", "tie"]:
    pro_total = float(judge_resp["pro_total"])
    con_total = float(judge_resp["con_total"])
    if abs(pro_total - con_total) < 1e-6:
        return "tie"
    return "pro" if pro_total > con_total else "con"

#Calls the Argument Generator endpoint
async def _call_argument(
    client: httpx.AsyncClient,
    motion: str,
    stance: Optional[str],
    use_ir: bool,
) -> ArgumentResponse:
    r = await client.post(
        f"{BASE_URL}/agents/argument",
        params={"use_ir": str(use_ir).lower()},
        json={"motion": motion, "stance": stance},
    )
    r.raise_for_status()
    data = r.json()
    points = [ArgumentPoint(**p) for p in data.get("points", [])]
    return ArgumentResponse(thesis=data.get("thesis", ""), points=points)

#Calls the Counter-Agent
async def _call_counter(
    client: httpx.AsyncClient,
    motion: str,
    opponent_points: List[ArgumentPoint],
    use_ir: bool,
) -> dict:
    payload = CounterRequest(
        motion=motion,
        opponent=Opponent(
            thesis=None,
            points=[OpponentPoint(text=p.text, citations=p.citations) for p in opponent_points],
        ),
    ).model_dump()
    r = await client.post(
        f"{BASE_URL}/agents/counter",
        params={"use_ir": str(use_ir).lower()},
        json=payload,
    )
    r.raise_for_status()
    return r.json()

#Sends both sides to the Judge service and returns the judge’s JSON decision/breakdown.
async def _call_judge(
    client: httpx.AsyncClient,
    motion: str,
    pro_thesis: str,
    pro_points: List[ArgumentPoint],
    con_thesis: str,
    con_points: List[ArgumentPoint],
) -> dict:
    jreq = JudgeRequest(
        motion=motion,
        pro=SideArgument(thesis=pro_thesis, points=pro_points),
        con=SideArgument(thesis=con_thesis, points=con_points),
    ).model_dump()
    r = await client.post(f"{BASE_URL}/agents/judge", json=jreq)
    r.raise_for_status()
    return r.json()

#If the LLM is on, asks it for a short “why this winner” paragraph based on the turn histor
def _llm_finalize_justification(
    motion: str,
    turns: List[TurnItem],
    pro_points: int,
    con_points: int,
    winner: str,
) -> Optional[str]:
    if not _LLM.is_enabled():
        return None
    try:
        system = "You write concise, neutral debate summaries that justify the winner."

        def tline(t: TurnItem) -> str:
            ap = (t.argument_point or "").replace("\n", " ")[:160]
            rb = (t.rebuttal or "").replace("\n", " ")[:160] if t.rebuttal else "(no rebuttal)"
            return f"Turn {t.turn_index} opener={t.side} | arg: {ap} | rebuttal: {rb} | turn_winner={t.turn_winner}"

        synopsis = "\n".join(tline(t) for t in turns[:6])
        user = (
            f"Motion: {motion}\n"
            f"Scoreboard: pro={pro_points}, con={con_points}, final={winner}\n"
            "Based on the turns below, write one tight paragraph (2–3 sentences) that explains why the final winner is justified, "
            "referencing patterns in logic/evidence across turns.\n"
            f"{synopsis}\n"
            "Return only the paragraph."
        )
        return _LLM.complete(system, user, max_tokens=160)
    except Exception as e:
        logger.warning(f"LLM final justification failed, use fallback: {e}")
        return None


@router.post("/cancel")
async def cancel_run(request_id: str = Query(..., description="ID passed when calling /debate/run")):
    """Signal the orchestrator to stop an in-flight debate run."""
    CANCEL_FLAGS[request_id] = True
    logger.info(f"Cancellation requested for debate run: {request_id}")
    return {"ok": True}


@router.post("/run", response_model=DebateReport)
async def run_debate(
    req: DebateRunRequest,
    request_id: Optional[str] = Query(
        default=None, description="Client-provided id to allow cancellation"
    ),
) -> DebateReport:
    if not request_id:
        request_id = str(uuid.uuid4())

    logger.info(f"Orchestrator: starting debate on '{req.motion}'  request_id={request_id}")

    # Basic input hygiene
    motion = sanitize_text(req.motion)

    turns: List[TurnItem] = []
    pro_points_total = 0
    con_points_total = 0

    opener: Literal["pro", "con"] = "pro" if (req.stance or "pro").lower() == "pro" else "con"

    # Determine IR usage (per-run override if settings.use_ir present, else global)
    use_ir: bool
    try:
        # If your DebateSettings has `use_ir: Optional[bool]`
        run_override = getattr(req.settings, "use_ir", None)
        use_ir = bool(is_ir_enabled()) if run_override is None else bool(run_override)
    except Exception:
        use_ir = bool(is_ir_enabled())

    logger.info(f"Orchestrator: opener={opener}, use_ir={use_ir}")

    # Propagate API key to internal calls if present
    api_key = os.getenv("API_KEY", "").strip()
    default_headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    cancelled = False

    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=default_headers) as client:
        for turn_idx in range(1, req.settings.max_turns + 1):
            if _is_cancelled(request_id):
                logger.info(f"Debate cancelled before turn {turn_idx} — request_id={request_id}")
                cancelled = True
                break

            logger.info(f"Orchestrator: turn {turn_idx} opener={opener}")

            if opener == "pro":
                arg = await _call_argument(client, motion, stance="pro", use_ir=use_ir)
                pro_thesis = arg.thesis
                pro_points = arg.points

                if _is_cancelled(request_id):
                    cancelled = True
                    break

                con_counter = await _call_counter(client, motion, pro_points, use_ir=use_ir)
                con_points = _points_from_counter(con_counter)
                con_thesis = "Countering the pro's claims for balance."
            else:
                arg = await _call_argument(client, motion, stance="con", use_ir=use_ir)
                con_thesis = arg.thesis
                con_points = arg.points

                if _is_cancelled(request_id):
                    cancelled = True
                    break

                pro_counter = await _call_counter(client, motion, con_points, use_ir=use_ir)
                pro_points = _points_from_counter(pro_counter)
                pro_thesis = "Countering the con's claims for balance."

            if _is_cancelled(request_id):
                cancelled = True
                break

            jresp = await _call_judge(
                client,
                motion,
                pro_thesis=pro_thesis,
                pro_points=pro_points,
                con_thesis=con_thesis,
                con_points=con_points,
            )

            t_scores = _pack_turn_scores(jresp)
            winner = _pick_turn_winner(jresp)
            if winner == "pro":
                pro_points_total += 1
            elif winner == "con":
                con_points_total += 1

            opener_points = pro_points if opener == "pro" else con_points
            opener_point_text = opener_points[0].text if opener_points else "(no point)"
            opener_citations = opener_points[0].citations if opener_points else []

            rebuttal_points = con_points if opener == "pro" else pro_points
            rebuttal_text = rebuttal_points[0].text if rebuttal_points else None
            rebuttal_citations = rebuttal_points[0].citations if rebuttal_points else []

            turns.append(
                TurnItem(
                    turn_index=turn_idx,
                    side=opener,
                    argument_point=opener_point_text,
                    argument_citations=opener_citations,
                    rebuttal=rebuttal_text,
                    rebuttal_citations=rebuttal_citations,
                    turn_winner=winner,
                    turn_scores=t_scores,
                )
            )

            if req.settings.swap_sides_each_turn:
                opener = "con" if opener == "pro" else "pro"

    # Determine final winner by turn points
    if pro_points_total == con_points_total:
        final_winner: Literal["pro", "con", "tie"] = "tie"
    else:
        final_winner = "pro" if pro_points_total > con_points_total else "con"

    # Final justification
    if cancelled:
        final_just = f"Cancelled by user after {len(turns)} turn(s)."
    else:
        llm_just = _llm_finalize_justification(motion, turns, pro_points_total, con_points_total, final_winner)
        final_just = (
            llm_just
            if llm_just
            else (
                "Tie on turn points; see per-turn judge totals."
                if final_winner == "tie"
                else f"Higher number of turn wins: pro={pro_points_total}, con={con_points_total}."
            )
        )

    report = DebateReport(
        motion=motion,
        settings=req.settings,
        turns=turns,
        scoreboard=DebateScoreboard(
            pro_points=pro_points_total,
            con_points=con_points_total,
            total_turns=len(turns),
        ),
        final_winner=final_winner,
        final_justification=final_just,
    )

    # Persist JSON
    ts = int(time.time())
    out_path = RUNS_DIR / f"debate_{ts}.json"
    try:
        out_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
        logger.info(f"Debate report saved to {out_path}")
    except Exception as e:
        logger.warning(f"Could not persist debate run: {e}")

    # cleanup cancellation flag
    _clear_cancel(request_id)

    return report
