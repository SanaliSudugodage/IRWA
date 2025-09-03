# src/schemas/debate.py
from __future__ import annotations

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class DebateSettings(BaseModel):
    mode: Literal["fixed_turns", "first_to", "best_of"] = Field(
        default="fixed_turns",
        description="fixed_turns: play all max_turns; first_to: stop when a side reaches target_points; best_of: highest score after max_turns wins."
    )
    max_turns: int = Field(default=10, ge=1, le=50)
    target_points: Optional[int] = Field(default=None, ge=1, le=50, description="Used when mode='first_to'.")
    win_by_margin: Optional[int] = Field(default=None, ge=1, le=10, description="Early-stop if lead is decisive.")
    swap_sides_each_turn: bool = Field(default=True)
    judge_each_turn: bool = Field(default=True)
    judge_final_overall: bool = Field(default=True)


class DebateRunRequest(BaseModel):
    motion: str = Field(..., min_length=4, max_length=500)
    stance: Optional[str] = Field(default=None, description="Optional opener for turn 1: 'pro' or 'con'.")
    settings: DebateSettings = Field(default_factory=DebateSettings)


class ScoreDetail(BaseModel):
    relevance: int = Field(..., ge=0, le=5)
    logic: int = Field(..., ge=0, le=5)
    evidence: int = Field(..., ge=0, le=5)
    clarity: int = Field(..., ge=0, le=5)
    fairness: int = Field(..., ge=0, le=5)
    total: int = Field(..., ge=0, le=25)


class TurnScores(BaseModel):
    pro: ScoreDetail
    con: ScoreDetail


class TurnItem(BaseModel):
    turn_index: int
    side: Literal["pro", "con"]                 # who opened the turn
    argument_point: str
    argument_citations: List[str] = Field(default_factory=list)
    rebuttal: Optional[str] = None
    rebuttal_citations: List[str] = Field(default_factory=list)
    turn_winner: Optional[Literal["pro", "con", "tie"]] = None
    turn_scores: Optional[TurnScores] = None    # nicer Swagger than Dict[str, Dict[str,int]]


class DebateScoreboard(BaseModel):
    pro_points: int
    con_points: int
    total_turns: int


class DebateReport(BaseModel):
    motion: str
    settings: DebateSettings
    turns: List[TurnItem]
    scoreboard: DebateScoreboard
    final_winner: Literal["pro", "con", "tie"]
    final_justification: str
