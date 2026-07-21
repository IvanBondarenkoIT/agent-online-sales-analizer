"""Cursor Cloud Agents API provider (works without local Node bridge)."""

from __future__ import annotations

import logging
import time

import httpx

from config import Settings
from llm.base import LLMClient
from llm.http_client import create_http_client

logger = logging.getLogger("dimkava.llm.cursor")

CURSOR_API_BASE = "https://api.cursor.com"
TERMINAL_STATUSES = {"FINISHED", "ERROR", "CANCELLED", "EXPIRED"}
POLL_INTERVAL_SEC = 2.0
MAX_POLL_SEC = 300.0


class CursorProvider(LLMClient):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.cursor_api_key
        self._model = settings.llm_model

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def complete(self, system: str, user: str) -> str:
        prompt_text = f"{system}\n\n---\n\n{user}"
        logger.debug("Cursor Cloud API request, model=%s", self._model)

        payload: dict = {
            "prompt": {"text": prompt_text},
            "model": {"id": self._model},
        }

        with create_http_client(timeout=120.0) as client:
            create_resp = client.post(
                f"{CURSOR_API_BASE}/v1/agents",
                headers=self._headers(),
                json=payload,
            )
            if create_resp.status_code >= 400:
                raise RuntimeError(
                    f"Cursor API create failed ({create_resp.status_code}): "
                    f"{create_resp.text[:500]}"
                )

            data = create_resp.json()
            agent_id = data["agent"]["id"]
            run_id = data["run"]["id"]
            logger.debug("Created agent %s, run %s", agent_id, run_id)

            try:
                result = self._poll_run(client, agent_id, run_id)
            finally:
                self._delete_agent(client, agent_id)

        if not result.strip():
            raise RuntimeError("Cursor API returned empty result")
        return result.strip()

    def _poll_run(self, client: httpx.Client, agent_id: str, run_id: str) -> str:
        deadline = time.monotonic() + MAX_POLL_SEC
        while time.monotonic() < deadline:
            run_resp = client.get(
                f"{CURSOR_API_BASE}/v1/agents/{agent_id}/runs/{run_id}",
                headers=self._headers(),
            )
            if run_resp.status_code >= 400:
                raise RuntimeError(
                    f"Cursor API poll failed ({run_resp.status_code}): "
                    f"{run_resp.text[:500]}"
                )

            run = run_resp.json()
            status = run.get("status", "")
            logger.debug("Run %s status=%s", run_id, status)

            if status in TERMINAL_STATUSES:
                if status != "FINISHED":
                    raise RuntimeError(
                        f"Cursor run ended with status={status}: "
                        f"{run.get('result', '')[:200]}"
                    )
                return str(run.get("result") or "")

            time.sleep(POLL_INTERVAL_SEC)

        raise RuntimeError(f"Cursor run {run_id} timed out after {MAX_POLL_SEC}s")

    def _delete_agent(self, client: httpx.Client, agent_id: str) -> None:
        try:
            client.delete(
                f"{CURSOR_API_BASE}/v1/agents/{agent_id}",
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            logger.warning("Failed to delete agent %s: %s", agent_id, exc)
