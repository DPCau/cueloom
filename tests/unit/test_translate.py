"""Unit tests for Stage 3 translation batching, caching, and contracts."""

from __future__ import annotations

import tempfile
from pathlib import Path

from cueloom.config import load_config
from cueloom.llm.cache import cache_key
from cueloom.models import Cue, GlossaryEntry, Job
from cueloom.stages.translate import build_batches, translate_cues


def test_context_window_with_noncontiguous_ids(tmp_path, monkeypatch) -> None:
    from cueloom.stages import translate

    cfg = load_config()
    cfg.work_dir = tmp_path
    cfg.llm.cache = False
    cfg.llm.batch_max_items = 1
    captured = []

    class Client:
        def complete_json(self, system, payload, schema):
            captured.append(payload)
            return {"items": payload["items"]}

    monkeypatch.setattr(translate, "_get_client", lambda _: Client())
    cues = [Cue(id=i, start=n, end=n + 1, text=str(i)) for n, i in enumerate((10, 30, 50))]
    job = Job(job_id="context", input_path="demo.wav", target_lang="zh-CN")
    cfg.llm.context_window = 1
    translate_cues(cues, [], cfg, job)
    assert captured[1]["context_before"] == ["10"]
    assert captured[1]["context_after"] == ["50"]
    captured.clear()
    cfg.llm.context_window = 0
    translate_cues(cues, [], cfg, job)
    assert all(not p["context_before"] and not p["context_after"] for p in captured)


def test_cache_key_invalidation() -> None:
    k1 = cache_key("m1", "p1", "g1", "en", "zh-CN", "hello")
    k2 = cache_key("m1", "p1", "g1", "en", "zh-CN", "hello")
    k3 = cache_key("m2", "p1", "g1", "en", "zh-CN", "hello")
    k4 = cache_key("m1", "p2", "g1", "en", "zh-CN", "hello")

    assert k1 == k2
    assert k1 != k3
    assert k1 != k4


def test_build_batches() -> None:
    cfg = load_config()
    cfg.llm.batch_max_items = 2
    cues = [
        Cue(id=0, start=0.0, end=1.0, text="First cue"),
        Cue(id=1, start=1.0, end=2.0, text="Second cue"),
        Cue(id=2, start=2.0, end=3.0, text="Third cue"),
    ]
    batches = build_batches(cues, cfg)
    assert len(batches) == 2
    assert len(batches[0]) == 2
    assert len(batches[1]) == 1


def test_translate_cues_with_mock_and_cache() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = load_config()
        cfg.work_dir = Path(tmpdir) / "work"
        job = Job(
            job_id="test_job",
            input_path="dummy.wav",
            target_lang="zh-CN",
            source_lang="en",
        )
        cues = [
            Cue(id=0, start=0.5, end=2.0, text="welcome to the channel."),
            Cue(id=1, start=2.2, end=4.5, text="today we build an agent with cueloom."),
        ]
        glossary = [GlossaryEntry(src="CueLoom", tgt="CueLoom", do_not_translate=True)]

        # Pass 1: uncached
        cues, records = translate_cues(cues, glossary, cfg, job)
        assert len(records) == 2
        assert cues[0].target_text == "欢迎来到本频道。"
        assert records[0]["cached"] is False
        assert (cues[0].start, cues[0].end) == (0.5, 2.0)

        # Pass 2: cached
        cues2 = [
            Cue(id=0, start=0.5, end=2.0, text="welcome to the channel."),
            Cue(id=1, start=2.2, end=4.5, text="today we build an agent with cueloom."),
        ]
        _, records2 = translate_cues(cues2, glossary, cfg, job)
        assert records2[0]["cached"] is True
        assert records2[1]["cached"] is True
