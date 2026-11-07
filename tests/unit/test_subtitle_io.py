"""Unit tests for pysubs2 subtitle generation and verification."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cueloom.io.subtitle import emit, load
from cueloom.models import Cue


def test_emit_and_load_srt() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cues = [
            Cue(id=0, start=1.234, end=3.456, text="Hello world", target_text="你好世界"),
            Cue(id=1, start=4.000, end=6.500, text="Second line", target_text="第二行"),
        ]
        out_path = Path(tmpdir) / "test.srt"
        emit(cues, out_path, mode="bilingual")

        assert out_path.exists()
        subs = load(out_path)
        assert len(subs.events) == 2
        assert abs(subs.events[0].start - 1234) <= 1
        assert abs(subs.events[0].end - 3456) <= 1
        assert "Hello world" in subs.events[0].text
        assert "你好世界" in subs.events[0].text


def test_emit_vtt_and_ass() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cues = [Cue(id=0, start=0.5, end=2.0, text="Source", target_text="目标")]
        vtt = Path(tmpdir) / "test.vtt"
        ass = Path(tmpdir) / "test.ass"
        emit(cues, vtt, mode="target")
        emit(cues, ass, mode="source")

        assert vtt.exists()
        assert ass.exists()
        assert len(load(vtt).events) == 1
        assert len(load(ass).events) == 1
