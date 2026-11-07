"""Integration test: timecode invariance across translation and output (docs/06 §1)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cueloom.config import load_config
from cueloom.io.jsonl import read_jsonl
from cueloom.io.subtitle import load as load_subtitle
from cueloom.models import Cue
from cueloom.pipeline import create_job, run


def test_timecode_invariance_across_all_stages() -> None:
    fixture_audio = Path(__file__).resolve().parents[1] / "fixtures" / "demo.wav"

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = load_config()
        cfg.work_dir = Path(tmpdir) / "work"
        cfg.out_dir = Path(tmpdir) / "out"

        job = create_job(
            input_path=fixture_audio,
            target_lang="zh-CN",
            bilingual=True,
            formats=["srt"],
        )
        res_job = run(job, cfg)
        assert res_job.status == "done"

        work_job = cfg.work_dir / job.job_id
        cues_st2 = read_jsonl(work_job / "20_cues.jsonl", model=Cue)

        # Invariant 1: cues in 20_cues.jsonl match emitted subtitles down to millisecond
        bi_srt = cfg.out_dir / job.job_id / f"{fixture_audio.stem}.en-zh-CN.srt"
        subs = load_subtitle(bi_srt)
        assert len(subs.events) == len(cues_st2)

        for ev, cue in zip(subs.events, cues_st2):
            cue_start_ms = int(round(cue.start * 1000))
            cue_end_ms = int(round(cue.end * 1000))
            assert abs(ev.start - cue_start_ms) <= 2, f"start drift: ev={ev.start} cue={cue_start_ms}"
            assert abs(ev.end - cue_end_ms) <= 2, f"end drift: ev={ev.end} cue={cue_end_ms}"
