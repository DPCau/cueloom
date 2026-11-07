"""OpenAI-compatible chat completions client and a lightweight connectivity probe."""

from __future__ import annotations

import json
from typing import Protocol

import httpx

from cueloom.config import LlmConfig
from cueloom.llm.schema import RESPONSE_SCHEMA


class LlmClient(Protocol):
    def complete_json(self, system: str, payload: dict, schema: dict) -> dict: ...


class OpenAiCompatibleClient:
    """Only sends {id, text}, glossary and language tags. Never sends timecodes."""

    def __init__(self, cfg: LlmConfig) -> None:
        self.cfg = cfg

    def complete_json(self, system: str, payload: dict, schema: dict | None = None) -> dict:
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.cfg.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        with httpx.Client(timeout=self.cfg.timeout_sec) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


def probe(cfg: LlmConfig) -> dict:
    """Explicit, opt-in connectivity check. Never logs the key or its value."""
    if not cfg.configured:
        return {"ok": False, "reason": "not_configured"}

    payload = {
        "task": "subtitle_translation",
        "source_lang": "en",
        "target_lang": "zh-CN",
        "context_before": [],
        "context_after": [],
        "glossary": [],
        "items": [{"id": 0, "text": "Hello"}],
    }
    system = 'Return JSON only: {"items":[{"id":0,"text":"..."}]}'
    try:
        data = OpenAiCompatibleClient(cfg).complete_json(system, payload, RESPONSE_SCHEMA)
        ids = [item.get("id") for item in data.get("items", [])]
        return {"ok": ids == [0], "reason": "" if ids == [0] else "id_mismatch"}
    except Exception as exc:  # noqa: BLE001 - only the class name is exposed
        return {"ok": False, "reason": type(exc).__name__}
