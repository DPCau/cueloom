"""Stage 1: audio extraction + VAD + ASR (M1)."""

from __future__ import annotations

from pathlib import Path

from cueloom.config import Config
from cueloom.models import AsrSegment, Job, StageResult

NOT_IMPLEMENTED = "Stage 1 (ASR) is implemented in M1; see docs/04-stage-design.md"


def transcribe(path: Path, cfg: Config) -> tuple[str, list[AsrSegment]]:
    raise NotImplementedError(NOT_IMPLEMENTED)


def run(job: Job, cfg: Config) -> StageResult:
    raise NotImplementedError(NOT_IMPLEMENTED)
