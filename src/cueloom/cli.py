"""Minimal Typer CLI. The human-facing entry point is ctl.sh, not a parameter maze."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cueloom import __version__
from cueloom.config import load_config
from cueloom.io.subtitle import load as load_subtitle
from cueloom.llm.client import probe

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
            typer.echo(f"ok: {count} JSONL records")
        else:
            subs = load_subtitle(path)
            typer.echo(f"ok: {len(subs.events)} cues")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"invalid: {type(exc).__name__}: {exc}", err=True)
        raise typer.Exit(code=2) from exc


@app.command()
def run(
    media: Path = typer.Argument(..., help="Local video/audio file"),
    to: str = typer.Option(..., "--to", help="Target language"),
) -> None:
    """M1 will run the full pipeline. Kept as a stub so the CLI contract stays stable."""
    typer.echo(f"pipeline not implemented until M1 (input={media}, to={to})", err=True)
    raise typer.Exit(code=3)


def main() -> None:
    app()
