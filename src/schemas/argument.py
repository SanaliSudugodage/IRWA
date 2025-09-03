from typing import List, Optional
from pydantic import BaseModel, Field

class ArgumentRequest(BaseModel):
    motion: str = Field(..., min_length=4, max_length=500)
    stance: Optional[str] = Field(None, description="e.g., 'pro' or 'con'")

class ArgumentPoint(BaseModel):
    text: str = Field(..., min_length=3, max_length=1000)
    citations: List[str] = Field(default_factory=list, description="doc ids / urls")

class ArgumentResponse(BaseModel):
    thesis: str = Field(..., min_length=3, max_length=500)
    points: List[ArgumentPoint] = Field(default_factory=list)
    counter_anticipation: List[str] = Field(
        default_factory=list,
        description="Anticipated counters you expect from the other side"
    )
    conclusion: Optional[str] = Field(
        None,
        description="Short wrap-up that ties points back to the thesis"
    )
