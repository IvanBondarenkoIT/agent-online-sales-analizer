"""Mock LLM provider for testing without API keys."""

from __future__ import annotations

import json
import logging

from llm.base import LLMClient

logger = logging.getLogger("dimkava.llm.mock")

MOCK_RESPONSE = {
    "summary": "Клиент спрашивает цену кофемашины.",
    "client_emotion": "Нерешительность, сравнивает варианты",
    "errors_found": [
        "Цена названа без вовлекающего вопроса",
        "Отсутствует CTA в конце диалога",
    ],
    "killer_phrase": "ფასდაკლებით 1899 ლარია",
    "scores": {"needs_id": 1, "cta": 0},
    "ideal_response_georgian": (
        "გამარჯობა! სანამ ფასს გეტყვით — სახლისთვის გჭირდებათ "
        "თუ ბიზნესისთვის? რომელი სასმელს მიირთმევთ ყველაზე ხშირად?"
    ),
}


class MockProvider(LLMClient):
    def complete(self, system: str, user: str) -> str:
        logger.info("Mock LLM response (no API call)")
        return json.dumps(MOCK_RESPONSE, ensure_ascii=False)
