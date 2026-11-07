"""Five-stage pipeline orchestrator.

Coordinates:
01 asr -> 02 segment -> 03 translate -> 04 qc -> 05 emit.
Supports resume, per-stage failure isolation, and atomic job.json updates.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from cueloom.config import Config
from cueloom.models import Job, StageResult
from cueloom.stages import asr, emit, qc, segment, translate

STAGES = ("asr", "segment", "translate", "qc", "emit")

STAGE_DISPATCH: dict[str, Callable[[Job, Config], StageResult]] = {
    "asr": asr.run,
    "segment": segment.run,
    "translate": translate.run,
    "qc": qc.run,
    "emit": emit.run,
}

STAGE_PREREQUISITES: dict[str, str] = {
    "segment": "10_asr.jsonl",
    "translate": "20_cues.jsonl",
    "qc": "30_translated.jsonl",
    "emit": "20_cues.jsonl",
}


def make_job_id(input_path: Path) -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    stem = "".join(c if c.isalnum() else "_" for c in input_path.stem)[:16]
    h = hashlib.sha256(str(input_path.resolve()).encode("utf-8")).hexdigest()[:6]
    return f"{stem}_{timestamp}_{h}"


def create_job(
    input_path: Path,
    target_lang: str,
    source_lang: str | None = None,
    bilingual: bool = True,
    formats: list[str] | None = None,
    job_id: str | None = None,
) -> Job:
    jid = job_id or make_job_id(input_path)
    return Job(
        job_id=jid,
        input_path=str(input_path.resolve()),
        source_lang=source_lang,
        target_lang=target_lang,
        bilingual=bilingual,
        formats=formats or ["srt"],  # type: ignore[arg-type]
        created_at=datetime.now(timezone.utc).isoformat(),
        status="created",
    )


def _save_job_state(work_job_dir: Path, job: Job, results: list[StageResult]) -> None:
    work_job_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        **job.model_dump(mode="json"),
        "stage_results": [r.model_dump(mode="json") for r in results],
    }
    (work_job_dir / "job.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run(job: Job, cfg: Config, from_stage: str | None = None) -> Job:
    work_job = cfg.work_dir / job.job_id
    work_job.mkdir(parents=True, exist_ok=True)

    if from_stage:
        if from_stage not in STAGES:
            raise ValueError(f"unknown stage: {from_stage}. Allowed: {STAGES}")
        start_idx = STAGES.index(from_stage)
        prereq = STAGE_PREREQUISITES.get(from_stage)
        if prereq and not (work_job / prereq).exists():
            raise FileNotFoundError(
                f"Cannot resume from '{from_stage}': missing upstream artifact '{prereq}'"
            )
    else:
        start_idx = 0

    # Load existing stage results if resuming
    existing_results: list[StageResult] = []
    job_json = work_job / "job.json"
    if job_json.exists():
        try:
            data = json.loads(job_json.read_text(encoding="utf-8"))
            for r in data.get("stage_results", []):
                if r.get("stage") in STAGES[:start_idx]:
                    existing_results.append(StageResult(**r))
        except Exception:
            pass

    results: list[StageResult] = list(existing_results)
    job.status = "running"
    _save_job_state(work_job, job, results)

    for stage_name in STAGES[start_idx:]:
        job.stage = stage_name
        handler = STAGE_DISPATCH[stage_name]
        try:
            result = handler(job, cfg)
        except Exception as exc:
            result = StageResult(stage=stage_name, ok=False, warnings=[f"{type(exc).__name__}: {exc}"])

        results.append(result)
        _save_job_state(work_job, job, results)

        if not result.ok:
            job.status = "failed"
            _save_job_state(work_job, job, results)
            return job

    job.status = "done"
    job.stage = "emit"
    _save_job_state(work_job, job, results)
    return job
