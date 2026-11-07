"""Minimal Typer CLI. The human-facing entry point is ctl.sh, not a parameter maze."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cueloom import __version__
from cueloom.config import load_config
from cueloom.io.subtitle import load as load_subtitle
from cueloom.llm.client import probe
from cueloom.models import Job
from cueloom.pipeline import create_job, run as run_pipeline

app = typer.Typer(add_completion=False, help="CueLoom command line tools")


@app.command()
def version() -> None:
    typer.echo(f"cueloom {__version__}")


@app.command()
def doctor() -> None:
    """Check configuration and optionally probe the LLM endpoint."""
    cfg = load_config()
    summary = cfg.public_summary()
    typer.echo(f"host={cfg.host}:{cfg.port}  work={cfg.work_dir}  out={cfg.out_dir}")
    typer.echo(f"llm configured={summary['llm']['configured']} model={cfg.llm.model or '-'}")
    result = probe(cfg.llm)
    typer.echo(f"llm probe: {result}")
    raise typer.Exit(code=0 if result["ok"] else 1)


@app.command()
def validate(path: Path = typer.Argument(..., help="JSONL stage artifact or SRT/VTT/ASS file")) -> None:
    if not path.exists():
        typer.echo(f"missing: {path}", err=True)
        raise typer.Exit(code=2)
    try:
        if path.suffix.lower() == ".jsonl":
            count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
            typer.echo(f"ok: {count} JSONL records in {path.name}")
        else:
            subs = load_subtitle(path)
            typer.echo(f"ok: {len(subs.events)} cues in {path.name}")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"invalid: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@app.command()
def run(
    media: Path = typer.Argument(..., help="Local video/audio file"),
    to: str = typer.Option("zh-CN", "--to", help="Target language (e.g. zh-CN)"),
    source_lang: str | None = typer.Option(None, "--from", "-f", help="Source language (default auto)"),
    bilingual: bool = typer.Option(True, "--bilingual/--no-bilingual", help="Produce bilingual subtitles"),
    fmt: str = typer.Option("srt", "--format", help="Subtitle format: srt | vtt | ass"),
    from_stage: str | None = typer.Option(None, "--from-stage", help="Start from stage: asr|segment|translate|qc|emit"),
    job_id: str | None = typer.Option(None, "--job-id", help="Explicit job ID"),
) -> None:
    """Runs the 5-stage subtitle generation and translation pipeline."""
    if not media.exists():
        typer.echo(f"input file does not exist: {media}", err=True)
        raise typer.Exit(code=2)

    cfg = load_config()
    formats = [f.strip().lower() for f in fmt.split(",") if f.strip()]
    job = create_job(
        input_path=media,
        target_lang=to,
        source_lang=source_lang,
        bilingual=bilingual,
        formats=formats,
        job_id=job_id,
    )
    typer.echo(f"Starting pipeline job: {job.job_id}")
    typer.echo(f"Input: {media} -> target: {to} (bilingual={bilingual})")

    res_job = run_pipeline(job, cfg, from_stage=from_stage)
    if res_job.status == "done":
        typer.echo(f"Pipeline finished successfully! Status: {res_job.status}")
        out_dir = cfg.out_dir / res_job.job_id
        if out_dir.exists():
            for p in sorted(out_dir.iterdir()):
                if p.is_file():
                    typer.echo(f"  Artifact: {p}")
    else:
        typer.echo(f"Pipeline failed at stage '{res_job.stage}'. See work/{res_job.job_id}/job.json", err=True)
        raise typer.Exit(code=3)


@app.command()
def resume(
    job_id: str = typer.Argument(..., help="Existing job ID to resume"),
    from_stage: str = typer.Option("translate", "--from-stage", help="Stage to resume from"),
) -> None:
    """Resumes an existing pipeline job from a given stage."""
    cfg = load_config()
    job_file = cfg.work_dir / job_id / "job.json"
    if not job_file.exists():
        typer.echo(f"job {job_id} not found in {cfg.work_dir}", err=True)
        raise typer.Exit(code=2)

    data = json.loads(job_file.read_text(encoding="utf-8"))
    job = Job(**data)
    typer.echo(f"Resuming job {job_id} from stage '{from_stage}'")
    res_job = run_pipeline(job, cfg, from_stage=from_stage)
    if res_job.status == "done":
        typer.echo(f"Job {job_id} resumed and completed successfully.")
    else:
        typer.echo(f"Job {job_id} failed at stage '{res_job.stage}'.", err=True)
        raise typer.Exit(code=3)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
