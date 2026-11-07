"""Unit tests for semantic cue splitting and word alignment (docs/06 §5)."""

from __future__ import annotations

from pathlib import Path

from cueloom.config import load_config
from cueloom.models import AsrSegment, Word
from cueloom.stages.segment import FallbackAligner, split_cues


def test_fallback_aligner_monotonic() -> None:
    aligner = FallbackAligner()
    cfg = load_config()
    seg = AsrSegment(seg=0, start=1.0, end=3.0, text="Hello world from CueLoom", lang="en")
    words = aligner.align([seg], Path("dummy.wav"), cfg)

    assert len(words) == 4
    for i in range(len(words)):
        assert words[i].start < words[i].end
        if i > 0:
            assert words[i].start >= words[i - 1].end
    assert abs(words[0].start - 1.0) < 0.05
    assert abs(words[-1].end - 3.0) < 0.05


def test_split_cues_stable_ids_and_monotonic() -> None:
    cfg = load_config()
    words = [
        Word(text="Welcome", start=0.0, end=0.5),
        Word(text="to", start=0.5, end=0.8),
        Word(text="CueLoom.", start=0.8, end=1.5),  # Strong punct
        Word(text="Today", start=2.0, end=2.4),    # Pause 0.5s
        Word(text="we", start=2.4, end=2.6),
        Word(text="build", start=2.6, end=3.0),
        Word(text="agents.", start=3.0, end=3.6),
    ]
    cues = split_cues(words, cfg)

    assert len(cues) >= 2
    for i, cue in enumerate(cues):
        assert cue.id == i  # Stable sequential id
        assert cue.start < cue.end
        if i > 0:
            assert cue.start >= cues[i - 1].start
        assert cue.text


def test_split_cues_avoids_trailing_stop_words() -> None:
    cfg = load_config()
    words = [
        Word(text="我们", start=0.0, end=0.5),
        Word(text="和", start=0.5, end=0.8),       # Trailing function word
        Word(text="世界", start=1.5, end=2.0),     # Pause
        Word(text="对话", start=2.0, end=2.5),
    ]
    cues = split_cues(words, cfg)
    # The first cue should not end with "和" if it was split
    if len(cues) > 1:
        assert not cues[0].text.endswith("和")
