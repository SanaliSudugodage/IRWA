# src/security/auth.py
from __future__ import annotations

#Reads the API key from the API_KEY environment variable once at startup. If it’s empty, we treat the app as running in DEV mode
#Protects every route that depends on it: if no key is configured, it allows requests (DEV). Otherwise it expects an Authorization: Bearer <key> header and returns 401 if it’s missing or wrong.
import os
from fastapi import Depends, Header, HTTPException, status

API_KEY_ENV = os.getenv("API_KEY", "").strip()

def require_api_key(authorization: str | None = Header(default=None)):
    
    if not API_KEY_ENV:
        # No key configured → do not enforce (DEV). For prod, require a key.
        return True

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if token != API_KEY_ENV:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return True
