"""Unit tests for QC rules and auto-fix mechanisms (docs/04 §4)."""

from __future__ import annotations

from cueloom.config import load_config
from cueloom.models import Cue, GlossaryEntry
from cueloom.stages.qc import auto_wrap_lines, check_and_fix


def test_auto_wrap_lines() -> None:
    long_line = "这是一个超过十四个字符的非常长的单行字幕文本测试"
    wrapped, fixed = auto_wrap_lines(long_line, max_chars_per_line=14)
    assert fixed is True
    assert "\n" in wrapped
    for part in wrapped.split("\n"):
        assert len(part) <= 15


def test_qc_detects_time_overlap_and_nonmonotonic() -> None:
    cfg = load_config()
    cues = [
        Cue(id=0, start=2.0, end=1.0, text="Bad duration", target_text="错误时长"),
        Cue(id=1, start=0.5, end=3.0, text="Overlap", target_text="重叠"),
    ]
    _, issues = check_and_fix(cues, [], cfg)
    codes = {iss.code for iss in issues}
    assert "time_nonmonotonic" in codes
    assert "time_overlap" in codes


def test_qc_detects_term_miss_and_digit_mismatch() -> None:
    cfg = load_config()
    glossary = [GlossaryEntry(src="Agent", tgt="智能体", do_not_translate=False)]
    cues = [
        Cue(
            id=0,
            start=0.0,
            end=2.0,
            text="Agent 100 is ready",
            target_text="代理准备好了",  # Missed "智能体" and dropped 100
        )
    ]
    _, issues = check_and_fix(cues, glossary, cfg)
    codes = {iss.code for iss in issues}
    assert "term_miss" in codes
    assert "digit_mismatch" in codes


def test_qc_detects_cue_missing() -> None:
    cfg = load_config()
    cues = [Cue(id=0, start=0.0, end=1.0, text="Hello", target_text=None)]
    _, issues = check_and_fix(cues, [], cfg)
    codes = {iss.code for iss in issues}
    assert "cue_missing" in codes
