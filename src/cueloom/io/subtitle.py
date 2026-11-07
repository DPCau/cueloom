"""Subtitle output via pysubs2. Only SRT/VTT/ASS files are produced."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pysubs2

from cueloom.models import Cue

SUFFIXES = {"srt", "vtt", "ass"}
Mode = Literal["source", "target", "bilingual"]


def emit(
    cues: list[Cue],
    path: Path,
    bilingual: bool = True,
    order: str = "source_first",
    mode: Mode | None = None,
) -> Path:
    fmt = path.suffix.lstrip(".").lower()
    if fmt not in SUFFIXES:
        raise ValueError(f"unsupported subtitle format: {fmt}")

    if mode is None:
        effective_mode: Mode = "bilingual" if bilingual else "target"
    else:
        effective_mode = mode

    subs = pysubs2.SSAFile()
    for cue in cues:
        if effective_mode == "source":
            text = cue.text
        elif effective_mode == "target":
            text = cue.target_text if cue.target_text else cue.text
        else:  # bilingual
            if cue.target_text:
                pair = [cue.text, cue.target_text]
                if order == "target_first":
                    pair.reverse()
                text = "\\N".join(pair)
            else:
                text = cue.text

        subs.events.append(
            pysubs2.SSAEvent(
                start=int(round(cue.start * 1000)),
                end=int(round(cue.end * 1000)),
                text=text,
            )
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(path), format_=fmt)
    return path


def load(path: Path) -> pysubs2.SSAFile:
    return pysubs2.load(str(path))
