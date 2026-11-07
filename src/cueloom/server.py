"""Read-only FastAPI layer: health, redacted status, jobs and artifact listings.

No business logic lives here. Pipeline writes job.json; this layer only reads it.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from cueloom import __version__
from cueloom.config import load_config

CFG = load_config()
START = time.monotonic()
WEB_DIR = Path(__file__).resolve().parent / "web"
JOB_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass"}

app = FastAPI(
    title="CueLoom",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _job_files() -> list[Path]:
    if not CFG.work_dir.exists():
        return []
    return sorted(CFG.work_dir.glob("*/job.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def _read_job(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _valid_job_id(job_id: str) -> bool:
    return bool(JOB_ID_RE.fullmatch(job_id)) and ".." not in job_id


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    index = WEB_DIR / "index.html"
    if not index.exists():
        return "<h1>CueLoom</h1><p>Dashboard file missing.</p>"
    return index.read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__, "uptime_sec": round(time.monotonic() - START, 1)}


@app.get("/api/status")
def status() -> dict:
    return {
        "ok": True,
        "version": __version__,
        "uptime_sec": round(time.monotonic() - START, 1),
        "config": CFG.public_summary(),
        "jobs_count": len(_job_files()),
        "pipeline": {"implemented": True, "note": "five-stage pipeline ready"},
        "llm_probe": "skipped",
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    rows: list[dict] = []
    for path in _job_files():
        job = _read_job(path)
        if job is None:
            continue
        rows.append(
            {
                "job_id": job.get("job_id", path.parent.name),
                "status": job.get("status", "unknown"),
                "stage": job.get("stage"),
                "source_lang": job.get("source_lang"),
                "target_lang": job.get("target_lang"),
                "bilingual": job.get("bilingual", True),
                "created_at": job.get("created_at", ""),
            }
        )
    return rows


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    if not _valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="invalid job_id")
    path = CFG.work_dir / job_id / "job.json"
    job = _read_job(path)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/api/jobs/{job_id}/artifacts")
def job_artifacts(job_id: str) -> list[dict]:
    if not _valid_job_id(job_id):
        raise HTTPException(status_code=400, detail="invalid job_id")
    folder = CFG.out_dir / job_id
    if not folder.exists():
        return []
    rows: list[dict] = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in SUBTITLE_SUFFIXES:
            rows.append({"name": path.name, "size": path.stat().st_size, "format": path.suffix.lstrip(".")})
    return rows
