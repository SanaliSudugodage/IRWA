# src/schemas/judge.py
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field
from src.schemas.argument import ArgumentPoint  # reuse your existing model


class SideArgument(BaseModel):
    thesis: str = Field(..., min_length=3, max_length=600)
    points: List[ArgumentPoint] = Field(default_factory=list, min_length=1)


class CriterionScore(BaseModel):
    name: str
    score: int = Field(..., ge=0, le=5)
    explanation: str = Field(..., min_length=5, max_length=600)


class JudgeRequest(BaseModel):
    motion: str = Field(..., min_length=4, max_length=500)
    pro: SideArgument
    con: SideArgument


class JudgeResponse(BaseModel):
    pro_breakdown: List[CriterionScore]
    con_breakdown: List[CriterionScore]
    pro_total: float
    con_total: float
    winner: str = Field(..., pattern="^(pro|con)$")
    tie_breaker: Optional[str] = None
    feedback_pro: List[str] = Field(default_factory=list)
    feedback_con: List[str] = Field(default_factory=list)
