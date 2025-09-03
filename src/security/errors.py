# src/security/errors.py
from __future__ import annotations
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette import status
import httpx
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from src.schemas.common import ErrorResponse

async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ErrorResponse(detail="Validation failed").model_dump(),
    )

async def httpx_timeout_handler(request: Request, exc: httpx.TimeoutException):
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content=ErrorResponse(detail="Upstream timeout").model_dump(),
    )

async def generic_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(detail="Internal server error").model_dump(),
    )

# Wrap SlowAPI's default handler to keep your JSON schema
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    # Use their default for headers, but keep your body shape
    resp = await _rate_limit_exceeded_handler(request, exc)
    return JSONResponse(
        status_code=resp.status_code,
        headers=dict(resp.headers),
        content=ErrorResponse(detail="Rate limit exceeded").model_dump(),
    )
