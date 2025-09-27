# src/app.py
# imports and dependencies
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
import httpx
from loguru import logger

# Load .env ASAP
load_dotenv()

# Logging
logger.remove()
logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"))

from src.config import settings
from src.schemas.common import HealthResponse

app = FastAPI(
    title="AI Debate System",
    version=settings.app_version,
    description="Multi-agent debate API: Argument Generator, Counter-Agent, Judge, with IR/NLP.",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Exception handlers ()
try:
    from src.security.errors import (
        validation_exception_handler,
        httpx_timeout_handler,
        generic_exception_handler,
    )
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(httpx.TimeoutException, httpx_timeout_handler)
    app.add_exception_handler(Exception, generic_exception_handler)
except Exception:
    pass

# Health endpoint
@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version)

# --- Core routers ---
from src.agents.argument_generator.service import router as argument_router  # noqa: E402
app.include_router(argument_router, prefix="/agents", tags=["argument"])

for _mod, _attr, _prefix, _tags in [
    ("src.agents.counter_agent.service", "router", "/agents", ["counter"]),
    ("src.agents.evaluation_agent.service", "router", "/agents", ["judge"]),
    ("src.orchestrator.debate_flow", "router", "/debate", ["orchestrator"]),
]:
    try:
        mod = __import__(_mod, fromlist=[_attr])
        app.include_router(getattr(mod, _attr), prefix=_prefix, tags=_tags)
    except Exception as e:
        logger.warning(f"Skipping router {_mod}: {e}")

# IR admin (toggle, upload, reindex, stats)
try:
    from src.ir.admin import router as ir_admin_router
    app.include_router(ir_admin_router, prefix="/ir", tags=["ir-admin"])
except Exception as e:
    logger.warning(f"Skipping IR admin router: {e}")


#  Swagger: Bearer auth  
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema.setdefault("components", {}).setdefault(
        "securitySchemes", {}
    )["bearerAuth"] = {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
    }
    # Make bearer the default for all endpoints (lock icon shows)
    openapi_schema["security"] = [{"bearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi
