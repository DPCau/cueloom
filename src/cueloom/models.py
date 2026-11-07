"""Core data models. Field names are the M1 contract (see docs/03-data-contracts.md)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class AsrSegment(BaseModel):
    seg: int
    start: float
    end: float
    text: str
    lang: str
    avg_logprob: float = 0.0


class Word(BaseModel):
    text: str
    start: float
    end: float
    confidence: float = 1.0


class Cue(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[Word] = []
    target_text: str | None = None
    flags: list[str] = []


class GlossaryEntry(BaseModel):
    src: str
    tgt: str
    case_sensitive: bool = False
    do_not_translate: bool = False


class Job(BaseModel):
    job_id: str
    input_path: str
    source_lang: str | None = None
    target_lang: str
    bilingual: bool = True
    formats: list[Literal["srt", "vtt", "ass"]] = ["srt"]
    prompt_version: str = "v1"
    glossary_version: str = "v1"
    status: str = "created"
    stage: str | None = None
    created_at: str = ""


class StageResult(BaseModel):
    stage: str
    ok: bool
    count: int = 0
    duration_sec: float = 0.0
    warnings: list[str] = []


class QcIssue(BaseModel):
    cue_id: int
    code: str
    severity: Literal["info", "warn", "error"]
    detail: str
    auto_fixed: bool = False
