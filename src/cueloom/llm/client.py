"""OpenAI-compatible chat completions client, mock client, and connectivity probe."""

from __future__ import annotations

import json
from typing import Protocol

import httpx

from cueloom.config import LlmConfig
from cueloom.llm.schema import RESPONSE_SCHEMA


class LlmClient(Protocol):
    def complete_json(self, system: str, payload: dict, schema: dict | None = None) -> dict: ...


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


class MockLlmClient:
    """Deterministic mock translator for testing, CI, and local demos."""

    SAMPLE_TRANSLATIONS: dict[str, str] = {
        "welcome to the channel.": "欢迎来到本频道。",
        "today we build an agent with cueloom.": "今天我们用 CueLoom 构建一个智能体。",
        "it preserves timecodes and glossaries.": "它保留了时间轴和术语表。",
        "let us inspect the output format in detail.": "让我们详细检查输出格式。",
        "hello": "你好",
        "welcome back to the channel": "欢迎回到本频道",
        "today we build an agent": "今天我们构建一个智能体",
    }

    def complete_json(self, system: str, payload: dict, schema: dict | None = None) -> dict:
        items = payload.get("items", [])
        glossary = payload.get("glossary", [])
        tgt_items = []
        for it in items:
            cid = it["id"]
            src_text = it["text"]
            key = src_text.strip().lower()
            if key in self.SAMPLE_TRANSLATIONS:
                translated = self.SAMPLE_TRANSLATIONS[key]
            else:
                translated = f"[译] {src_text}"

            # Apply glossary overrides
            for g in glossary:
                src = g.get("src", "")
                tgt = g.get("tgt", "")
                if src and tgt and src in src_text and not g.get("do_not_translate", False):
                    translated = translated.replace(src, tgt)

            tgt_items.append({"id": cid, "text": translated})
        return {"items": tgt_items}


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
