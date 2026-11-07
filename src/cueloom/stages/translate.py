"""Stage 3: cue-level translation orchestration (M1, self-written core)."""

from __future__ import annotations

from cueloom.config import Config
from cueloom.models import Cue, GlossaryEntry

NOT_IMPLEMENTED = "Stage 3 (translation) is implemented in M1; see docs/04-stage-design.md"


def build_batches(cues: list[Cue], cfg: Config) -> list[list[Cue]]:
    raise NotImplementedError(NOT_IMPLEMENTED)


def translate_cues(cues: list[Cue], glossary: list[GlossaryEntry], cfg: Config) -> list[Cue]:
    raise NotImplementedError(NOT_IMPLEMENTED)
