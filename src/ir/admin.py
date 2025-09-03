from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional, List

from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from pydantic import BaseModel
from loguru import logger

from src.ir.state import is_ir_enabled, set_ir_enabled

router = APIRouter()

ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = ROOT / "data" / "corpus"


class ToggleIRRequest(BaseModel):
    # accept either key; both optional so we can also support "flip" when no body is sent
    enabled: Optional[bool] = None
    use_ir: Optional[bool] = None


class IRStats(BaseModel):
    corpus_dir: str
    files: int
    size_bytes: int
    # expose both names for frontends that expect one or the other
    ir_enabled: bool
    use_ir: bool


def _count_and_size(path: Path) -> tuple[int, int]:
    files = 0
    size = 0
    if path.exists():
        for p in path.rglob("*"):
            if p.is_file():
                files += 1
                try:
                    size += p.stat().st_size
                except Exception:
                    pass
    return files, size


def _clear_cached_retrievers() -> None:
    # Reset the module-level cached retrievers in both agents
    try:
        from src.agents.argument_generator import service as ag
        ag._retriever = None  # type: ignore[attr-defined]
    except Exception:
        pass
    try:
        from src.agents.counter_agent import service as ca
        ca._RETRIEVER = None  # type: ignore[attr-defined]
    except Exception:
        pass


@router.get("/stats", response_model=IRStats)
def stats() -> IRStats:
    files, size = _count_and_size(CORPUS_DIR)
    current = is_ir_enabled()
    return IRStats(
        corpus_dir=str(CORPUS_DIR.resolve()),
        files=files,
        size_bytes=size,
        ir_enabled=current,
        use_ir=current,  # alias for UI compatibility
    )


@router.post("/toggle")
def toggle(req: ToggleIRRequest | None = Body(None)):
    """
    Body options:
      - {"enabled": true/false}  OR  {"use_ir": true/false}
      - {} or no body -> flip current state
    """
    if req is None or (req.enabled is None and req.use_ir is None):
        desired = not is_ir_enabled()
    else:
        desired = req.enabled if req.enabled is not None else bool(req.use_ir)
    new_state = set_ir_enabled(bool(desired))
    logger.info(f"IR toggled -> {new_state}")
    return {"ok": True, "ir_enabled": new_state, "use_ir": new_state}


@router.post("/upload")
async def upload(
    files: List[UploadFile] = File(..., description="One or more .txt/.md/.pdf files"),
    auto_reindex: bool = True,
):
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    (CORPUS_DIR / "uploads").mkdir(parents=True, exist_ok=True)

    stored_paths: List[str] = []
    for file in files:
        suffix = (file.filename or "").split(".")[-1].lower()
        if suffix not in {"txt", "md", "pdf"}:
            raise HTTPException(status_code=400, detail=f"Only .txt, .md, .pdf allowed (got: {file.filename})")

        dest = CORPUS_DIR / "uploads" / file.filename
        with dest.open("wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            size = dest.stat().st_size
        except Exception:
            size = -1
        logger.info(f"Uploaded -> {dest} ({size} bytes)")
        stored_paths.append(str(dest))

    reindexed = False
    if auto_reindex:
        # 1) Ingest raw docs -> normalized texts & manifest
        # 2) Build FAISS index from chunks
        # 3) Clear cached retrievers so new index is used
        from src.ir import ingest
        from src.ir import chunk_embed

        ingest.ingest()
        chunk_embed.build_index()
        _clear_cached_retrievers()
        logger.info("IR reindex: cleared cached retrievers.")
        reindexed = True

    return {"ok": True, "stored": stored_paths, "reindexed": reindexed}
