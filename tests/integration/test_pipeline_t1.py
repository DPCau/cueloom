"""Integration test: 5-stage pipeline on fixture audio (T1) -> bilingual SRT (docs/06 §5)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cueloom.config import load_config
from cueloom.io.subtitle import load as load_subtitle
from cueloom.pipeline import create_job, run


def test_end_to_end_pipeline() -> None:
    fixture_audio = Path(__file__).resolve().parents[1] / "fixtures" / "demo.wav"
    assert fixture_audio.exists(), f"fixture audio missing: {fixture_audio}"

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = load_config()
        cfg.work_dir = Path(tmpdir) / "work"
        cfg.out_dir = Path(tmpdir) / "out"

        job = create_job(
            input_path=fixture_audio,
            target_lang="zh-CN",
            source_lang="en",
            bilingual=True,
            formats=["srt"],
        )

        res_job = run(job, cfg)
        assert res_job.status == "done"
        assert res_job.stage == "emit"

        work_job = cfg.work_dir / job.job_id
        # Check all stage JSONL artifacts exist
        assert (work_job / "10_asr.jsonl").exists()
        assert (work_job / "15_words.jsonl").exists()
        assert (work_job / "20_cues.jsonl").exists()
        assert (work_job / "30_translated.jsonl").exists()
        assert (work_job / "40_qc.jsonl").exists()
        assert (work_job / "job.json").exists()

        out_job = cfg.out_dir / job.job_id
        # Check emitted subtitle files
        src_srt = out_job / f"{fixture_audio.stem}.en.srt"
        tgt_srt = out_job / f"{fixture_audio.stem}.zh-CN.srt"
        bi_srt = out_job / f"{fixture_audio.stem}.en-zh-CN.srt"

        assert src_srt.exists()
        assert tgt_srt.exists()
        assert bi_srt.exists()

        # Check bilingual content
        subs = load_subtitle(bi_srt)
        assert len(subs.events) > 0
        first_event = subs.events[0]
        assert "\n" in first_event.text or "\\N" in first_event.text
        assert first_event.start < first_event.end
