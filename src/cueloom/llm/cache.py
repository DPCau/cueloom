"""Per-cue cache key (docs/03 §3.3). Changing prompt/glossary/model invalidates it."""

from __future__ import annotations

import hashlib


def cache_key(
    model: str,
    prompt_version: str,
    glossary_version: str,
    source_lang: str,
    target_lang: str,
    text: str,
) -> str:
    raw = "|".join([model, prompt_version, glossary_version, source_lang, target_lang, text])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
