"""Integration test: breakpoint resumption from intermediate stages (docs/02 §5)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cueloom.config import load_config
from cueloom.pipeline import create_job, run
from cueloom.stages import asr, segment


def test_resume_from_translate_stage() -> None:
    fixture_audio = Path(__file__).resolve().parents[1] / "fixtures" / "demo.wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = load_config()
        cfg.work_dir = Path(tmpdir) / "work"
        cfg.out_dir = Path(tmpdir) / "out"

        job = create_job(input_path=fixture_audio, target_lang="zh-CN")

        # Pre-run stages 1 & 2 only
        r1 = asr.run(job, cfg)
        assert r1.ok is True
        r2 = segment.run(job, cfg)
        assert r2.ok is True

        work_job = cfg.work_dir / job.job_id
        assert (work_job / "20_cues.jsonl").exists()
        assert not (work_job / "30_translated.jsonl").exists()

        # Resume from translate
        resumed_job = run(job, cfg, from_stage="translate")
        assert resumed_job.status == "done"
        assert resumed_job.stage == "emit"
        assert (work_job / "30_translated.jsonl").exists()
        assert (work_job / "40_qc.jsonl").exists()
        assert (cfg.out_dir / job.job_id / f"{fixture_audio.stem}.en-zh-CN.srt").exists()
