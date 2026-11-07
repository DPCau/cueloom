"""Stage 5: pure subtitle output, no video/audio artifacts (M1)."""

from __future__ import annotations

from pathlib import Path

from cueloom.config import Config
from cueloom.models import Cue, Job

NOT_IMPLEMENTED = "Stage 5 (emit) is implemented in M1; see docs/04-stage-design.md"


def emit(cues: list[Cue], job: Job, cfg: Config) -> list[Path]:
    raise NotImplementedError(NOT_IMPLEMENTED)
