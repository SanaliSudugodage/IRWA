# src/schemas/counter.py
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field

class OpponentPoint(BaseModel):
    text: str = Field(..., min_length=3, max_length=1000)
    citations: List[str] = Field(default_factory=list)

class Opponent(BaseModel):
    thesis: Optional[str] = Field(default=None, max_length=600)
    points: List[OpponentPoint] = Field(default_factory=list, min_length=1)

class Weakness(BaseModel):
    target_point_index: int
    weakness_score: float = Field(..., ge=0.0, le=1.0)
    fallacies: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    evidence_gap: bool = False

class Rebuttal(BaseModel):
    target_point_index: int
    counterclaim: str = Field(..., min_length=5, max_length=600)
    citations: List[str] = Field(default_factory=list)
    improved_argument: str = Field(..., min_length=5, max_length=600)

class CounterRequest(BaseModel):
    motion: str = Field(..., min_length=4, max_length=500)
    # Preferred modern payload:
    opponent: Optional[Opponent] = None
    # Back-compat payload the service normalizes if present:
    opponent_points: Optional[List[str]] = None

class CounterResponse(BaseModel):
    weaknesses: List[Weakness]
    rebuttals: List[Rebuttal]
