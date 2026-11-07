"""Stage 2: forced alignment + semantic cue splitting (self-written core).

Inputs: 10_asr.jsonl + audio.
Outputs: 15_words.jsonl, 20_cues.jsonl.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Protocol

from cueloom.config import Config
from cueloom.io.jsonl import read_jsonl, write_jsonl
from cueloom.models import AsrSegment, Cue, Job, StageResult, Word

TRAILING_STOP_WORDS = {
    # Chinese function words
    "的", "了", "和", "在", "把", "与", "及", "或", "而", "着", "向", "从",
    # English stop words
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "for", "with", "at", "by", "as",
}

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]")
NUMBER_DATE_RE = re.compile(r"^\d+([.,]\d+)?%?$")


class AlignBackend(Protocol):
    def align(self, segments: list[AsrSegment], audio: Path, cfg: Config) -> list[Word]: ...


class FallbackAligner:
    """Interpolates word boundaries proportionally from ASR segment timestamps."""

    def align(self, segments: list[AsrSegment], audio: Path, cfg: Config) -> list[Word]:
        words: list[Word] = []
        for seg in segments:
            seg_words = self._segment_to_words(seg)
            words.extend(seg_words)
        return words

    def _segment_to_words(self, seg: AsrSegment) -> list[Word]:
        text = seg.text.strip()
        if not text:
            return []

        # Tokenize based on CJK vs Latin
        tokens: list[str] = []
        if CJK_RE.search(text):
            # CJK characters + English/digits clusters
            pattern = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+|[^\w\s]")
            tokens = [m.group(0) for m in pattern.finditer(text)]
        else:
            tokens = text.split()

        if not tokens:
            return [Word(text=text, start=seg.start, end=seg.end, confidence=1.0)]

        total_chars = sum(max(1, len(t)) for t in tokens)
        duration = max(0.1, seg.end - seg.start)
        sec_per_char = duration / total_chars

        curr_t = seg.start
        result: list[Word] = []
        for i, t in enumerate(tokens):
            w_dur = max(0.05, len(t) * sec_per_char)
            # Ensure last token aligns with segment end
            end_t = seg.end if i == len(tokens) - 1 else min(seg.end, curr_t + w_dur)
            result.append(
                Word(
                    text=t,
                    start=round(curr_t, 3),
                    end=round(max(curr_t + 0.05, end_t), 3),
                    confidence=1.0,
                )
            )
            curr_t = end_t
        return result


def get_align_backend(cfg: Config) -> AlignBackend:
    align_cfg = cfg.raw.get("align", {}) or {}
    backend_name = align_cfg.get("backend", "none").lower()
    if backend_name in ("none", "fallback", "linear"):
        return FallbackAligner()
    # If other backend requested, return fallback for M1 prototype
    return FallbackAligner()


def _join_words(words: list[Word]) -> str:
    """Joins words with natural spacing (space between Latin, no space between CJK)."""
    if not words:
        return ""
    result = []
    for i, w in enumerate(words):
        t = w.text
        if i > 0:
            prev = words[i - 1].text
            # Add space if both are Latin / alphanumeric
            if not CJK_RE.search(prev) and not CJK_RE.search(t):
                if not re.match(r"^[.,!?;:]", t):
                    result.append(" ")
        result.append(t)
    return "".join(result).strip()


def _is_strong_boundary(text: str) -> bool:
    return any(p in text for p in ("。", "！", "？", ".", "!", "?", "\n"))


def _is_soft_boundary(text: str) -> bool:
    return any(p in text for p in ("，", ",", "；", ";", "、", ":", "："))


def split_cues(words: list[Word], cfg: Config) -> list[Cue]:
    """Semantic cue splitting adhering to CPS, duration, and trailing word constraints."""
    if not words:
        return []

    seg_cfg = cfg.raw.get("segment", {}) or {}
    min_dur = float(seg_cfg.get("min_duration_sec", 0.8))
    max_dur = float(seg_cfg.get("max_duration_sec", 7.0))
    max_chars_line = int(seg_cfg.get("max_chars_per_line", 14))
    max_lines = int(seg_cfg.get("max_lines", 2))
    max_cue_chars = max_chars_line * max_lines

    # Step 1: initial clustering by punctuation & pause
    groups: list[list[Word]] = []
    current_group: list[Word] = []

    for i, w in enumerate(words):
        current_group.append(w)
        # Check if boundary
        is_last = i == len(words) - 1
        if is_last:
            groups.append(current_group)
            break

        next_w = words[i + 1]
        pause = next_w.start - w.end
        dur = current_group[-1].end - current_group[0].start
        chars_count = sum(len(x.text) for x in current_group)

        is_pause_break = pause >= 0.35
        is_punct_break = _is_strong_boundary(w.text)
        is_over_length = dur >= max_dur or chars_count >= max_cue_chars

        if is_punct_break or (is_pause_break and dur >= min_dur) or is_over_length:
            # Trailing function word check: move split before stopword if possible
            if len(current_group) > 1 and current_group[-1].text.lower() in TRAILING_STOP_WORDS:
                # Keep stopword with next group if next group has space
                popped = current_group.pop()
                groups.append(current_group)
                current_group = [popped]
            else:
                groups.append(current_group)
                current_group = []

    # Step 2: merge overly short groups (< min_dur) if feasible
    merged_groups: list[list[Word]] = []
    for grp in groups:
        if not grp:
            continue
        if not merged_groups:
            merged_groups.append(grp)
            continue

        prev_grp = merged_groups[-1]
        combined_dur = grp[-1].end - prev_grp[0].start
        combined_chars = sum(len(w.text) for w in prev_grp) + sum(len(w.text) for w in grp)
        prev_dur = prev_grp[-1].end - prev_grp[0].start

        if prev_dur < min_dur and combined_dur <= max_dur and combined_chars <= max_cue_chars:
            merged_groups[-1] = prev_grp + grp
        else:
            merged_groups.append(grp)

    # Step 3: convert groups to Cue instances with stable IDs
    cues: list[Cue] = []
    for idx, grp in enumerate(merged_groups):
        start = grp[0].start
        end = max(start + 0.1, grp[-1].end)
        text = _join_words(grp)
        cues.append(
            Cue(
                id=idx,
                start=round(start, 3),
                end=round(end, 3),
                text=text,
                words=grp,
                target_text=None,
                flags=[],
            )
        )
    return cues


def align(segments: list[AsrSegment], audio: Path, cfg: Config) -> list[Word]:
    backend = get_align_backend(cfg)
    return backend.align(segments, audio, cfg)


def run(job: Job, cfg: Config) -> StageResult:
    start_t = time.monotonic()
    work_job = cfg.work_dir / job.job_id
    asr_file = work_job / "10_asr.jsonl"
    if not asr_file.exists():
        raise FileNotFoundError(f"missing 10_asr.jsonl for job {job.job_id}")

    segments = read_jsonl(asr_file, model=AsrSegment)
    audio_path = Path(job.input_path)

    # 15_words.jsonl
    words = align(segments, audio_path, cfg)
    write_jsonl(work_job / "15_words.jsonl", words)

    # 20_cues.jsonl
    cues = split_cues(words, cfg)
    count = write_jsonl(work_job / "20_cues.jsonl", cues)

    return StageResult(
        stage="segment",
        ok=True,
        count=count,
        duration_sec=round(time.monotonic() - start_t, 2),
    )
