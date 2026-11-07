"""Five-stage orchestrator skeleton.

M0.5 keeps the state machine, stage ordering and job.json contract stable.
Real stage bodies arrive in M1; until then each stage returns a clear warning
instead of silently pretending to succeed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from cueloom.config import Config
from cueloom.models import Job, StageResult

STAGES = ("asr", "segment", "translate", "qc", "emit")


def _dispatch(stage: str, job: Job, cfg: Config) -> StageResult:
    return StageResult(
        stage=stage,
        ok=False,
        warnings=[f"stage '{stage}' is not implemented until M1 (docs/08-roadmap.md)"],
    )


def run(job: Job, cfg: Config, from_stage: str | None = None) -> Job:
    start = STAGES.index(from_stage) if from_stage else 0
    if from_stage and from_stage not in STAGES:
        raise ValueError(f"unknown stage: {from_stage}")

    results: list[StageResult] = []
    for stage in STAGES[start:]:
        job.stage = stage
        result = _dispatch(stage, job, cfg)
        results.append(result)
        if not result.ok:
            job.status = "not_implemented"
            break
    else:
        job.status = "done"

    work = cfg.work_dir / job.job_id
    work.mkdir(parents=True, exist_ok=True)
    if not job.created_at:
        job.created_at = datetime.now(timezone.utc).isoformat()
    payload = {
        **job.model_dump(mode="json"),
        "stage_results": [r.model_dump(mode="json") for r in results],
    }
    (work / "job.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return job
