"""Stage 1: audio extraction + VAD + ASR.

Outputs 10_asr.jsonl with AsrSegment records.
Supports FasterWhisperBackend (when installed) and MockAsrBackend (for tests/demos).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Protocol

from cueloom.config import Config
from cueloom.io.jsonl import write_jsonl
from cueloom.models import AsrSegment, Job, StageResult
from cueloom.model_manager import ModelManager


class AsrBackend(Protocol):
    def transcribe(
        self, audio: Path, cfg: Config, source_lang: str | None = None
    ) -> tuple[str, list[AsrSegment]]: ...


class FasterWhisperBackend:
    """Uses faster-whisper with PyAV audio decoding and Silero VAD."""

    def transcribe(
        self, audio: Path, cfg: Config, source_lang: str | None = None
    ) -> tuple[str, list[AsrSegment]]:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError(
                "faster-whisper is not installed. Install with `uv sync --extra asr` or "
                "set asr.backend: mock in configs/local.yaml"
            ) from exc

        asr_cfg = cfg.raw.get("asr", {}) or {}
        model_id = asr_cfg.get("model", "faster-whisper-large-v3")
        local_dir = ModelManager(cfg.root).resolve_model_path(model_id)
        device = asr_cfg.get("device", "auto")
        compute_type = asr_cfg.get("compute_type", "int8_float16")
        vad_filter = asr_cfg.get("vad_filter", True)
        min_silence = asr_cfg.get("vad_min_silence_ms", 500)
        speech_pad = asr_cfg.get("vad_speech_pad_ms", 400)

        # Map auto device on Apple Silicon / CPU
        if device == "auto":
            device = "cpu"
            compute_type = "int8"

        model = WhisperModel(str(local_dir), local_files_only=True, device=device, compute_type=compute_type)
        vad_params = dict(min_silence_duration_ms=min_silence, speech_pad_ms=speech_pad)
        segments_gen, info = model.transcribe(
            str(audio),
            language=source_lang,
            vad_filter=vad_filter,
            vad_parameters=vad_params,
            condition_on_previous_text=False,
            beam_size=5,
        )

        detected_lang = info.language or source_lang or "en"
        segments: list[AsrSegment] = []
        for i, s in enumerate(segments_gen):
            text = s.text.strip()
            if not text:
                continue
            segments.append(
                AsrSegment(
                    seg=i,
                    start=round(s.start, 3),
                    end=round(s.end, 3),
                    text=text,
                    lang=detected_lang,
                    avg_logprob=round(getattr(s, "avg_logprob", 0.0), 3),
                )
            )
        return detected_lang, segments


class MockAsrBackend:
    """Deterministic ASR backend for offline testing and prototype validation."""

    DEFAULT_SEGMENTS = [
        ("Welcome to the channel.", 0.20, 2.10, "en"),
        ("Today we build an agent with CueLoom.", 2.40, 5.20, "en"),
        ("It preserves timecodes and glossaries.", 5.50, 8.40, "en"),
        ("Let us inspect the output format in detail.", 8.70, 11.90, "en"),
    ]

    def transcribe(
        self, audio: Path, cfg: Config, source_lang: str | None = None
    ) -> tuple[str, list[AsrSegment]]:
        detected_lang = source_lang or "en"
        # If there is a companion .transcript.txt or .json, read it; otherwise use default sample
        transcript_file = audio.with_suffix(".transcript.txt")
        if transcript_file.exists():
            lines = [line.strip() for line in transcript_file.read_text(encoding="utf-8").splitlines() if line.strip()]
            segments = []
            curr_time = 0.5
            for i, line in enumerate(lines):
                duration = max(1.2, round(len(line) * 0.15, 2))
                segments.append(
                    AsrSegment(
                        seg=i,
                        start=round(curr_time, 3),
                        end=round(curr_time + duration, 3),
                        text=line,
                        lang=detected_lang,
                        avg_logprob=-0.15,
                    )
                )
                curr_time += duration + 0.35
            return detected_lang, segments

        segments = [
            AsrSegment(
                seg=i,
                start=start,
                end=end,
                text=text,
                lang=lang or detected_lang,
                avg_logprob=-0.12,
            )
            for i, (text, start, end, lang) in enumerate(self.DEFAULT_SEGMENTS)
        ]
        return detected_lang, segments


def filter_hallucinations(segments: list[AsrSegment], blacklist: list[str]) -> tuple[list[AsrSegment], list[str]]:
    if not blacklist:
        return segments, []
    filtered: list[AsrSegment] = []
    warnings: list[str] = []
    lower_blacklist = [b.lower() for b in blacklist if b.strip()]
    for s in segments:
        text_lower = s.text.lower()
        matched = [b for b in lower_blacklist if b in text_lower]
        if matched:
            warnings.append(f"segment {s.seg} dropped due to hallucination match: {matched}")
        else:
            filtered.append(s)
    return filtered, warnings


def get_backend(cfg: Config) -> AsrBackend:
    name = (cfg.raw.get("asr", {}) or {}).get("backend", "faster-whisper").lower()
    if name == "mock":
        return MockAsrBackend()
    if name == "faster-whisper":
        return FasterWhisperBackend()
    raise ValueError(f"unsupported asr backend: {name}")


def transcribe(path: Path, cfg: Config, source_lang: str | None = None) -> tuple[str, list[AsrSegment]]:
    backend = get_backend(cfg)
    return backend.transcribe(path, cfg, source_lang=source_lang)


def run(job: Job, cfg: Config) -> StageResult:
    start_t = time.monotonic()
    audio_path = Path(job.input_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"input file does not exist: {audio_path}")

    detected_lang, raw_segments = transcribe(audio_path, cfg, source_lang=job.source_lang)
    if not job.source_lang:
        job.source_lang = detected_lang

    asr_cfg = cfg.raw.get("asr", {}) or {}
    blacklist = asr_cfg.get("hallucination_blacklist", [])
    segments, warnings = filter_hallucinations(raw_segments, blacklist)
    if asr_cfg.get("backend", "faster-whisper").lower() == "mock":
        warnings.append("asr_mock_fallback: 已显式启用 mock，结果不是真实语音识别")

    work_job = cfg.work_dir / job.job_id
    work_job.mkdir(parents=True, exist_ok=True)
    out_file = work_job / "10_asr.jsonl"
    count = write_jsonl(out_file, segments)

    return StageResult(
        stage="asr",
        ok=True,
        count=count,
        duration_sec=round(time.monotonic() - start_t, 2),
        warnings=warnings,
    )
