"""OpenRouter LLM provider (Stage 4)."""

from __future__ import annotations

import logging

import httpx

from config import Settings
from llm.base import LLMClient
from llm.http_client import create_http_client

logger = logging.getLogger("dimkava.llm.openrouter")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMClient):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.openrouter_api_key
        self._model = settings.llm_model

    def complete(self, system: str, user: str) -> str:
        logger.debug("OpenRouter request, model=%s", self._model)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        with create_http_client(timeout=120.0) as client:
            response = client.post(OPENROUTER_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("OpenRouter returned no choices")
        content = choices[0].get("message", {}).get("content", "")
        if not content.strip():
            raise RuntimeError("OpenRouter returned empty content")
        return content.strip()
