"""Subtitle output via pysubs2. Only SRT/VTT/ASS files are produced."""

from __future__ import annotations

from pathlib import Path

import pysubs2

from cueloom.models import Cue

SUFFIXES = {"srt", "vtt", "ass"}


def emit(
    cues: list[Cue],
    path: Path,
    bilingual: bool = True,
    order: str = "source_first",
) -> Path:
    fmt = path.suffix.lstrip(".").lower()
    if fmt not in SUFFIXES:
        raise ValueError(f"unsupported subtitle format: {fmt}")

    subs = pysubs2.SSAFile()
    for cue in cues:
        text = cue.text
        if bilingual and cue.target_text:
            pair = [cue.text, cue.target_text]
            if order == "target_first":
                pair.reverse()
            text = "\\N".join(pair)
        subs.events.append(
            pysubs2.SSAEvent(start=int(cue.start * 1000), end=int(cue.end * 1000), text=text)
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(path), format_=fmt)
    return path


def load(path: Path) -> pysubs2.SSAFile:
    return pysubs2.load(str(path))
