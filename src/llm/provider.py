# src/llm/provider.py
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional
import json
import httpx
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

#Initializes the chosen client: HF via httpx, OpenAI via official SDK, or Ollama via local HTTP
@dataclass
class LLMConfig:
    provider: str = os.getenv("LLM_PROVIDER", "none").strip().lower()  #used LLM
    model: str = os.getenv("LLM_MODEL", "TinyLlama/TinyLlama-1.1B-Chat-v1.0")
    # Keys (used for HF/OpenAI only)
    api_key: Optional[str] = os.getenv("HUGGINGFACE_API_TOKEN") or os.getenv("OPENAI_API_KEY")
    temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.2"))
    max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "400"))
    # Ollama base URL
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434") ##endpoint

class LLM:
    """
    Unified provider wrapper: Hugging Face, OpenAI, Ollama (local), or disabled ('none').
    Uses a 'fuse' to disable the remote client after the first hard error (401/403/404).
    """

    def __init__(self, cfg: LLMConfig | None = None):
        self.cfg = cfg or LLMConfig()
        self.client: Optional[object] = None  # httpx.Client or OpenAI client
        self._disabled: bool = False

        if self.cfg.provider == "huggingface" and self.cfg.api_key:
            base = f"https://api-inference.huggingface.co/models/{self.cfg.model}"
            headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}
            self.client = httpx.Client(base_url=base, headers=headers, timeout=600.0)
            logger.info(f"LLM(HF) ready → model={self.cfg.model}")

        elif self.cfg.provider == "openai" and self.cfg.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.cfg.api_key)  # type: ignore
                logger.info("LLM(OpenAI) ready")
            except Exception as e:
                logger.warning(f"OpenAI client init failed: {e}")
                self.client = None

        elif self.cfg.provider == "ollama":
            # plain http client to local server
            self.client = httpx.Client(base_url=self.cfg.ollama_base_url, timeout=60.0)
            logger.info(f"LLM(Ollama) ready → base={self.cfg.ollama_base_url}, model={self.cfg.model}")

        else:
            logger.info("LLM disabled (provider=none or missing API key)")

    def is_enabled(self) -> bool:
        return (self.client is not None) and (not self._disabled) and (self.cfg.provider in {"huggingface", "openai", "ollama"})

#Calls Hugging Face Inference API with a single prompt; sets temperature and max tokens. On 401/403/404 it disables further remote calls to avoid repeated failures.
    # Hugging Face 
    def _hf_complete(self, prompt: str, max_tokens: int | None = None) -> str:
        assert isinstance(self.client, httpx.Client), "HF client not initialized"
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": int(max_tokens or self.cfg.max_tokens),
                "temperature": float(self.cfg.temperature),
                "return_full_text": False,
            }
        }
        logger.info(
            f"LLM(HF) call → model={self.cfg.model}, max_new_tokens={payload['parameters']['max_new_tokens']}, temp={self.cfg.temperature}"
        )
        resp = self.client.post("", content=json.dumps(payload), params={"wait_for_model": "true"})
        if resp.status_code >= 400:
            body = resp.text[:400]
            logger.error(f"HF API error {resp.status_code} for model={self.cfg.model}. Response body: {body}")
            if resp.status_code in (401, 403, 404):
                self._disabled = True
                logger.warning("Disabling LLM for this process due to auth/not-found. Falling back to local summary.")
            raise RuntimeError(f"HF API {resp.status_code} for {self.cfg.model}")
        data = resp.json()
        if isinstance(data, list) and data and "generated_text" in data[0]:
            return (data[0]["generated_text"] or "").strip()
        if isinstance(data, dict) and "generated_text" in data:
            return (data["generated_text"] or "").strip()
        if isinstance(data, dict) and "error" in data:
            raise RuntimeError(f"HF inference error: {data['error']}")
        return str(data).strip()

#Calls local Ollama /api/generate in non-stream mode, controlling num_predict and temperature. Returns the plain text from response.
    #Ollama (local) 
    def _ollama_complete(self, prompt: str, max_tokens: int | None = None) -> str:
        """Calls Ollama /api/generate (non-stream) with a single prompt string."""
        assert isinstance(self.client, httpx.Client), "Ollama client not initialized"
        url = "/api/generate"
        payload = {
            "model": self.cfg.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": float(self.cfg.temperature),
                "num_predict": int(max_tokens or self.cfg.max_tokens),
            }
        }
        logger.info(f"LLM(Ollama) call → model={self.cfg.model}, num_predict={payload['options']['num_predict']}, temp={self.cfg.temperature}")
        resp = self.client.post(url, json=payload)
        if resp.status_code >= 400:
            body = resp.text[:400]
            logger.error(f"Ollama error {resp.status_code} for model={self.cfg.model}. Body: {body}")
            if resp.status_code in (401, 403, 404):
                self._disabled = True
                logger.warning("Disabling LLM (Ollama) for this process due to auth/not-found. Falling back to local summary.")
            raise RuntimeError(f"Ollama API {resp.status_code} for {self.cfg.model}")
        data = resp.json()
        # response shape: {"model": "...", "created_at": "...", "response": "...", ...}
        text = (data.get("response") or "").strip()
        return text


#Unified entry point: formats a simple “system + user” prompt and routes to HF, Ollama, or OpenAI. If all providers fail or are off, falls back to the local summarizer so the app never breaks.
    # Unified public method 
    def complete(self, system: str, user: str, max_tokens: int | None = None) -> str:
        if self.cfg.provider == "huggingface" and isinstance(self.client, httpx.Client) and not self._disabled:
            prompt = f"[SYSTEM]\n{system.strip()}\n\n[USER]\n{user.strip()}\n\n[ASSISTANT]\n"
            return self._hf_complete(prompt, max_tokens=max_tokens)

        if self.cfg.provider == "ollama" and isinstance(self.client, httpx.Client) and not self._disabled:
            prompt = f"[SYSTEM]\n{system.strip()}\n\n[USER]\n{user.strip()}\n\n[ASSISTANT]\n"
            return self._ollama_complete(prompt, max_tokens=max_tokens)

        if self.cfg.provider == "openai" and self.client is not None and not self._disabled:
            try:
                from openai import OpenAI
                resp = self.client.chat.completions.create(  # type: ignore[attr-defined]
                    model=self.cfg.model,
                    temperature=self.cfg.temperature,
                    max_tokens=(max_tokens or self.cfg.max_tokens),
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                return (resp.choices[0].message.content or "").strip()
            except Exception as e:
                logger.warning(f"OpenAI completion failed: {e}; falling back")

        # Final fallback: local summarizer
        try:
            from src.nlp.summarizer import summarize
            return summarize(user, max_tokens=(max_tokens or self.cfg.max_tokens))
        except Exception as e:
            logger.error(f"Local summarizer fallback also failed: {e}")
            return user[: (max_tokens or self.cfg.max_tokens)]
