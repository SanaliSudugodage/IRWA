# src/schemas/common.py
from pydantic import BaseModel

class HealthResponse(BaseModel):
    status: str
    version: str

class ErrorResponse(BaseModel):
    detail: str
