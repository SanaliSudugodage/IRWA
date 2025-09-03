# src/ir/ingest.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from loguru import logger

# Optional PDF support
try:
    from pypdf import PdfReader  # pip install pypdf
except Exception:
    PdfReader = None


ROOT = Path(__file__).resolve().parents[2]  # project root
CORPUS_DIR = ROOT / "data" / "corpus"
RAW_DIR = ROOT / "data" / "raw_texts"
MANIFEST = RAW_DIR / "manifest.jsonl"


def _read_text_file(p: Path) -> str:
    # Read with errors='ignore' to avoid codec crashes, then normalize
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        with p.open("rb") as f:
            raw = f.read()
        return raw.decode("utf-8", errors="ignore")


def _read_pdf_file(p: Path) -> Optional[str]:
    if PdfReader is None:
        logger.warning(f"Skipping PDF (pypdf not installed): {p}")
        return None
    try:
        reader = PdfReader(str(p))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages)
    except Exception as e:
        logger.error(f"Failed to read PDF {p}: {e}")
        return None


def ingest() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    written = 0

    # Truncate old manifest
    if MANIFEST.exists():
        MANIFEST.unlink()

    with MANIFEST.open("w", encoding="utf-8") as mf:
        for p in sorted(CORPUS_DIR.rglob("*")):
            if not p.is_file():
                continue
            ext = p.suffix.lower()

            if ext in {".txt", ".md"}:
                text = _read_text_file(p)
            elif ext == ".pdf":
                text = _read_pdf_file(p)
                if text is None:
                    continue
            else:
                logger.info(f"Skipping unsupported file: {p.name}")
                continue

            text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            if not text:
                logger.info(f"Empty after extraction, skipping: {p.name}")
                continue

            # Save normalized text
            doc_id = f"doc_{written:05d}"
            out_path = RAW_DIR / f"{doc_id}.txt"
            out_path.write_text(text, encoding="utf-8")

            # Write manifest record
            record = {
                "doc_id": doc_id,
                "title": p.stem,
                "source_path": str(p.resolve()),
                "stored_path": str(out_path.resolve()),
                "n_chars": len(text),
            }
            mf.write(json.dumps(record, ensure_ascii=False) + "\n")

            written += 1
            logger.info(f"Ingested {p.name} -> {out_path.name}")

    logger.success(f"Ingestion complete. Wrote {written} documents to {RAW_DIR}")


if __name__ == "__main__":
    if not CORPUS_DIR.exists():
        print(f"Input folder not found: {CORPUS_DIR}\nCreate it and add .txt/.md/.pdf files.")
    else:
        ingest()
