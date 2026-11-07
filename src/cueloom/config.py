"""Configuration loading: env vars > .env > configs/local.yaml > configs/default.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class LlmConfig(BaseModel):
    base_url: str = ""
    model: str = ""
    api_key_env: str = "CUELOOM_LLM_API_KEY"
    timeout_sec: int = 60
    max_concurrency: int = 4
    max_retries: int = 3
    batch_max_items: int = 30
    batch_max_tokens: int = 1200
    context_window: int = 3
    reflection: bool = False
    cache: bool = True

    @property
    def api_key(self) -> str:
        return os.environ.get(self.api_key_env, "")

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)


class Config(BaseModel):
    root: Path
    work_dir: Path
    out_dir: Path
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    dashboard_refresh_sec: int = 5
    llm: LlmConfig = Field(default_factory=LlmConfig)
    raw: dict[str, Any] = Field(default_factory=dict)

    def public_summary(self) -> dict[str, Any]:
        """Redacted view for /api/status and the dashboard. Never contains key values."""
        asr = self.raw.get("asr", {}) or {}
        align = self.raw.get("align", {}) or {}
        segment = self.raw.get("segment", {}) or {}
        output = self.raw.get("output", {}) or {}
        return {
            "service": {
                "host": self.host,
                "port": self.port,
                "log_level": self.log_level,
                "dashboard_refresh_sec": self.dashboard_refresh_sec,
            },
            "llm": {
                "base_url": self.llm.base_url,
                "model": self.llm.model,
                "configured": self.llm.configured,
                "api_key_configured": bool(self.llm.api_key),
                "max_concurrency": self.llm.max_concurrency,
                "cache": self.llm.cache,
                "reflection": self.llm.reflection,
            },
            "asr": {"backend": asr.get("backend"), "model": asr.get("model")},
            "align": {"backend": align.get("backend")},
            "segment": {
                "max_cps": segment.get("max_cps"),
                "min_cps": segment.get("min_cps"),
                "llm_assist": segment.get("llm_assist", False),
            },
            "output": {"formats": output.get("formats", ["srt"]), "bilingual": output.get("bilingual", True)},
            "paths": {"work": str(self.work_dir), "out": str(self.out_dir)},
        }


def load_config(root: Path | None = None) -> Config:
    root = (root or project_root()).resolve()
    env_file = root / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)

    data: dict[str, Any] = {}
    default_file = root / "configs" / "default.yaml"
    if default_file.exists():
        data = yaml.safe_load(default_file.read_text(encoding="utf-8")) or {}
    local_file = root / "configs" / "local.yaml"
    if local_file.exists():
        data = _merge(data, yaml.safe_load(local_file.read_text(encoding="utf-8")) or {})

    llm_raw = data.get("llm", {}) or {}
    llm_fields = {k: v for k, v in llm_raw.items() if k in LlmConfig.model_fields}
    llm = LlmConfig(**llm_fields)
    llm.base_url = _env("CUELOOM_LLM_BASE_URL", llm.base_url)
    llm.model = _env("CUELOOM_LLM_MODEL", llm.model)
    llm.api_key_env = _env("CUELOOM_LLM_API_KEY_ENV", llm.api_key_env)
    llm.max_concurrency = int(_env("CUELOOM_LLM_CONCURRENCY", str(llm.max_concurrency)))

    server = data.get("server", {}) or {}
    work = Path(_env("CUELOOM_WORK_DIR", "work"))
    out = Path(_env("CUELOOM_OUT_DIR", "out"))

    return Config(
        root=root,
        work_dir=work if work.is_absolute() else root / work,
        out_dir=out if out.is_absolute() else root / out,
        host=_env("CUELOOM_HOST", str(server.get("host", "127.0.0.1"))),
        port=int(_env("CUELOOM_PORT", str(server.get("port", 8000)))),
        log_level=_env("CUELOOM_LOG_LEVEL", "INFO"),
        dashboard_refresh_sec=int(server.get("dashboard_refresh_sec", 5)),
        llm=llm,
        raw=data,
    )
