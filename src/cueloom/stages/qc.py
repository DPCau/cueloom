"""Stage 4: quality rules and backfill (M1, self-written core)."""

from __future__ import annotations

from cueloom.config import Config
from cueloom.models import Cue, QcIssue

NOT_IMPLEMENTED = "Stage 4 (QC) is implemented in M1; see docs/04-stage-design.md"


def check(cues: list[Cue], cfg: Config) -> list[QcIssue]:
    raise NotImplementedError(NOT_IMPLEMENTED)


def auto_fix(cues: list[Cue], issues: list[QcIssue]) -> list[Cue]:
    raise NotImplementedError(NOT_IMPLEMENTED)
