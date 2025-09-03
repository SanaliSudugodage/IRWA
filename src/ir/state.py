from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "ir_state.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

# Default comes from env; otherwise OFF (so you don’t get surprise citations)
_DEFAULT = os.getenv("IR_DEFAULT_ON", "0").strip().lower() in {"1", "true", "yes"}

_enabled: bool = _DEFAULT


def _load() -> None:
    """Load persisted IR state from disk (if present)."""
    global _enabled
    try:
        if STATE_PATH.exists():
            obj = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            _enabled = bool(obj.get("enabled", _DEFAULT))
    except Exception:
        _enabled = _DEFAULT


def _save() -> None:
    """Persist IR state to disk; ignore failures (best-effort)."""
    try:
        STATE_PATH.write_text(json.dumps({"enabled": _enabled}, indent=2), encoding="utf-8")
    except Exception:
        pass


_load()


def is_ir_enabled() -> bool:
    return bool(_enabled)


def set_ir_enabled(v: bool) -> bool:
    """Set + persist state; returns the new state."""
    global _enabled
    _enabled = bool(v)
    _save()
    return _enabled
