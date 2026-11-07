"""Stage 5: pure subtitle output (SRT/VTT/ASS).

Produces:
- <base>.<src>.<fmt>
- <base>.<tgt>.<fmt>
- <base>.<src>-<tgt>.<fmt> (if bilingual)
Verifies timecode invariants and pysubs2 read-back consistency.
Never outputs video, audio, or muxed containers.
"""

from __future__ import annotations

import time
from pathlib import Path

from cueloom.config import Config
from cueloom.io.jsonl import read_jsonl
from cueloom.io.subtitle import emit as emit_subtitle
from cueloom.io.subtitle import load as load_subtitle
from cueloom.models import Cue, Job, StageResult


def verify_emitted_subtitle(path: Path, expected_cues: list[Cue]) -> None:
    subs = load_subtitle(path)
    if len(subs.events) != len(expected_cues):
        raise ValueError(
            f"Emitted {path.name} event count mismatch: expected {len(expected_cues)}, got {len(subs.events)}"
        )
    for ev, cue in zip(subs.events, expected_cues):
        exp_start = int(round(cue.start * 1000))
        exp_end = int(round(cue.end * 1000))
        # Allow 2ms difference due to rounding
        if abs(ev.start - exp_start) > 2 or abs(ev.end - exp_end) > 2:
            raise ValueError(
                f"Emitted {path.name} timecode drift: event=({ev.start}, {ev.end}) vs cue=({exp_start}, {exp_end})"
            )


def emit(cues: list[Cue], job: Job, cfg: Config) -> list[Path]:
    if not cues:
        return []

    input_stem = Path(job.input_path).stem
    src_lang = job.source_lang or "src"
    tgt_lang = job.target_lang or "tgt"
    order = (cfg.raw.get("output", {}) or {}).get("bilingual_order", "source_first")

    out_job_dir = cfg.out_dir / job.job_id
    out_job_dir.mkdir(parents=True, exist_ok=True)
    emitted: list[Path] = []

    for fmt in job.formats:
        ext = fmt.lower()

        # 1. Source subtitle
        src_file = out_job_dir / f"{input_stem}.{src_lang}.{ext}"
        emit_subtitle(cues, src_file, mode="source")
        verify_emitted_subtitle(src_file, cues)
        emitted.append(src_file)

        # 2. Target subtitle
        tgt_file = out_job_dir / f"{input_stem}.{tgt_lang}.{ext}"
        emit_subtitle(cues, tgt_file, mode="target")
        verify_emitted_subtitle(tgt_file, cues)
        emitted.append(tgt_file)

        # 3. Bilingual subtitle
        if job.bilingual:
            bilingual_file = out_job_dir / f"{input_stem}.{src_lang}-{tgt_lang}.{ext}"
            emit_subtitle(cues, bilingual_file, mode="bilingual", order=order)
            verify_emitted_subtitle(bilingual_file, cues)
            emitted.append(bilingual_file)

    return emitted


def run(job: Job, cfg: Config) -> StageResult:
    start_t = time.monotonic()
    work_job = cfg.work_dir / job.job_id
    cues_file = work_job / "20_cues.jsonl"
    if not cues_file.exists():
        raise FileNotFoundError(f"missing 20_cues.jsonl for job {job.job_id}")

    cues = read_jsonl(cues_file, model=Cue)
    emitted = emit(cues, job, cfg)

    return StageResult(
        stage="emit",
        ok=True,
        count=len(emitted),
        duration_sec=round(time.monotonic() - start_t, 2),
    )
