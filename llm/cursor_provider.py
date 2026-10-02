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
        self._client: httpx.Client | None = None
        self.last_create_ms: float | None = None
        self.last_poll_ms: float | None = None
        self.last_total_ms: float | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = create_http_client(timeout=120.0)
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()
        self._client = None

    def complete(self, system: str, user: str) -> str:
        prompt_text = f"{system}\n\n---\n\n{user}"
        logger.debug("Cursor Cloud API request, model=%s", self._model)

        payload: dict = {
            "prompt": {"text": prompt_text},
            "model": {"id": self._model},
        }

        t0 = time.monotonic()
        client = self._get_client()
        create_resp = client.post(
            f"{CURSOR_API_BASE}/v1/agents",
            headers=self._headers(),
            json=payload,
        )
        create_ms = (time.monotonic() - t0) * 1000.0
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
            t_poll = time.monotonic()
            result = self._poll_run(client, agent_id, run_id)
            poll_ms = (time.monotonic() - t_poll) * 1000.0
        finally:
            self._delete_agent(client, agent_id)

        total_ms = (time.monotonic() - t0) * 1000.0
        self.last_create_ms = create_ms
        self.last_poll_ms = poll_ms
        self.last_total_ms = total_ms
        logger.info(
            "Cursor timing: create=%.0fms poll=%.0fms total=%.0fms",
            create_ms,
            poll_ms,
            total_ms,
        )

        if not result.strip():
            raise RuntimeError("Cursor API returned empty result")
        return result.strip()

    def _get_run(self, client: httpx.Client, agent_id: str, run_id: str) -> httpx.Response:
        last_exc: httpx.HTTPError | None = None
        for attempt in range(3):
            try:
                return client.get(
                    f"{CURSOR_API_BASE}/v1/agents/{agent_id}/runs/{run_id}",
                    headers=self._headers(),
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < 2:
                    logger.warning("Cursor poll HTTP error (retry %s): %s", attempt + 1, exc)
                    time.sleep(1.0)
        assert last_exc is not None
        raise last_exc

    def _poll_run(self, client: httpx.Client, agent_id: str, run_id: str) -> str:
        deadline = time.monotonic() + MAX_POLL_SEC
        while time.monotonic() < deadline:
            run_resp = self._get_run(client, agent_id, run_id)
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
