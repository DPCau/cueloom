"""Stage 2: forced alignment + semantic cue splitting (M1, self-written core)."""

from __future__ import annotations

from pathlib import Path

from cueloom.config import Config
from cueloom.models import Cue, Word

NOT_IMPLEMENTED = "Stage 2 (align/segment) is implemented in M1; see docs/04-stage-design.md"


def align(words_or_segments: object, audio: Path, cfg: Config) -> list[Word]:
    raise NotImplementedError(NOT_IMPLEMENTED)


def split_cues(words: list[Word], cfg: Config) -> list[Cue]:
    raise NotImplementedError(NOT_IMPLEMENTED)
