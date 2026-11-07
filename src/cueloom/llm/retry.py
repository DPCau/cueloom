"""Retry policy for LLM calls (docs/05 §5)."""

from __future__ import annotations


def backoff_delays(retries: int = 3) -> list[float]:
    return [1.0, 2.0, 4.0][:retries]


def degradation_chain() -> list[str]:
    return ["retry_batch", "split_to_single_cue", "exponential_backoff", "mark_cue_failed"]
