"""同源 Web API；业务操作委托给控制层。"""

from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from cueloom import __version__
from cueloom.control.config_service import ConfigProvider
from cueloom.control.guards import ControlError, authorize, loopback
from cueloom.control.job_service import JobService, TaskRegistry
from cueloom.llm.client import probe
from cueloom.model_manager import ModelManager

START = time.monotonic()
WEB_DIR = Path(__file__).resolve().parent / "web"


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    upload_id: str | None = None
    target_lang: str = Field(default="zh-CN", pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{2,8})*$")
    bilingual: bool = True
    formats: list[Literal["srt", "vtt", "ass"]] = Field(default=["srt"], min_length=1, max_length=3)
    demo: bool = False


class DeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    confirm: str


def create_app(root: Path | None = None) -> FastAPI:
    provider = ConfigProvider(root)
    tasks = TaskRegistry()
    jobs = JobService(provider, tasks)

    @asynccontextmanager
    async def lifespan(application):
        cfg = provider.snapshot()
        if cfg.host != "localhost" and not loopback(cfg.host) and len(provider.web_token()) < 32:
            raise RuntimeError("远程监听必须配置至少 32 字符的随机 CUELOOM_WEB_TOKEN")
        jobs.recover_interrupted()
        yield

    app = FastAPI(
        title="CueLoom",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.provider, app.state.tasks, app.state.jobs = provider, tasks, jobs
    app.state.model_manager = None
    manager_lock = threading.Lock()
    probe_lock = threading.Lock()
    last_probe = [float("-inf")]

    def error(exc):
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "hint": ""}},
            status_code=exc.status,
        )

    @app.middleware("http")
    async def security(request: Request, call_next):
        try:
            if request.url.path.startswith("/api/") and request.url.path not in {
                "/api/health",
                "/api/auth",
            }:
                request.state.auth = authorize(request, provider.web_token())
            response = await call_next(request)
        except ControlError as exc:
            response = error(exc)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        return error(exc)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error(ControlError("invalid_config", "请求参数不符合接口契约", 422))

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return error(ControlError("internal_error", "操作失败，请检查本机资源与配置", 500))

    @app.get("/", response_class=HTMLResponse)
    def dashboard():
        index = WEB_DIR / "index.html"
        return index.read_text(encoding="utf-8") if index.exists() else "<h1>CueLoom</h1>"

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/api/health")
    def health():
        return {
            "ok": True,
            "version": __version__,
            "uptime_sec": round(time.monotonic() - START, 1),
        }

    @app.get("/api/auth")
    def auth(request: Request):
        try:
            state = authorize(request, provider.web_token())
        except ControlError as exc:
            if exc.code != "unauthorized":
                raise
            state = {"authenticated": False, "local": False, "mode": "token"}
        return {
            **state,
            "token_configured": bool(provider.web_token()),
            "password_enabled": False,
            "password_supported": False,
            "proxy_headers_trusted": False,
        }

    @app.get("/api/status")
    def status():
        return {
            **health(),
            "config": provider.snapshot().public_summary(),
            "jobs_count": len(jobs.list_jobs()),
            "pipeline": {"implemented": True, "note": "五阶段字幕流水线"},
            "llm_probe": "skipped",
        }

    @app.get("/api/config")
    def config():
        return provider.public()

    @app.put("/api/config")
    def save_config(payload: dict):
        return provider.save(payload)

    @app.post("/api/config/reload")
    def reload_config():
        provider.reload()
        return provider.public()

    @app.post("/api/uploads", status_code=201)
    async def upload(request: Request):
        return await jobs.upload(request)

    @app.get("/api/jobs")
    def list_jobs():
        return jobs.list_jobs()

    @app.get("/api/jobs/active")
    def active_job():
        with jobs.lock:
            jid = jobs.active_job_id
            return {"job_id": jid, "job": jobs.detail(jid) if jid else None}

    @app.post("/api/jobs", status_code=202)
    def submit_job(payload: JobRequest):
        return jobs.submit(payload)

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str):
        return jobs.detail(job_id)

    @app.get("/api/jobs/{job_id}/artifacts")
    def artifacts(job_id: str):
        return jobs.artifacts(job_id)

    @app.get("/api/jobs/{job_id}/artifacts/{name}")
    def download_artifact(job_id: str, name: str):
        return FileResponse(
            jobs.artifact(job_id, name), filename=name, media_type="application/octet-stream"
        )

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str):
        return tasks.get(task_id)

    @app.get("/api/llm/profiles")
    def list_profiles():
        return provider.profiles_public()

    @app.post("/api/llm/profiles", status_code=201)
    def add_profile(payload: dict):
        return provider.save_profile(payload)

    @app.post("/api/llm/profiles/import-current", status_code=201)
    def import_current_profile(payload: dict):
        if set(payload) != {"name"}:
            raise ControlError("invalid_config", "仅需填写导入方案名称")
        cfg = provider.snapshot().llm
        return provider.save_profile({"name": payload["name"], "base_url": cfg.base_url,
                                      "model": cfg.model, "api_key": cfg.api_key})

    @app.put("/api/llm/profiles/{profile_id}")
    def edit_profile(profile_id: str, payload: dict):
        return provider.save_profile(payload, profile_id)

    @app.post("/api/llm/profiles/{profile_id}/activate")
    def activate_profile(profile_id: str):
        return provider.activate_profile(profile_id)

    @app.delete("/api/llm/profiles/{profile_id}")
    def delete_profile(profile_id: str):
        return provider.delete_profile(profile_id)

    @app.post("/api/llm/probe")
    def llm_probe():
        with probe_lock:
            now = time.monotonic()
            if now - last_probe[0] < 5:
                raise ControlError("busy", "探活间隔至少五秒", 429)
            last_probe[0] = now
        cfg = provider.snapshot().llm
        cfg.timeout_sec = min(cfg.timeout_sec, 5)
        cfg.max_retries = 0
        started = time.monotonic()
        try:
            result = probe(cfg)
            ok = bool(result.get("ok"))
        except Exception:
            ok = False
        return {
            "ok": ok,
            "category": "ok" if ok else ("upstream_error" if cfg.configured else "not_configured"),
            "latency_ms": round((time.monotonic() - started) * 1000),
            "model": cfg.model,
        }

    def manager():
        with manager_lock:
            if app.state.model_manager is None:
                app.state.model_manager = ModelManager(provider.root)
            return app.state.model_manager

    def model_call(function, *args):
        try:
            return function(*args)
        except FileNotFoundError:
            raise ControlError("not_found", "模型文件不存在", 404) from None
        except ValueError:
            raise ControlError("invalid_config", "模型操作参数或状态无效") from None
        except RuntimeError:
            raise ControlError("conflict", "模型正在使用或不可操作", 409) from None

    @app.get("/api/models")
    def models():
        return model_call(manager().list_models)

    @app.post("/api/models/rescan")
    def rescan():
        return model_call(manager().list_models)

    @app.post("/api/models/{model_id}/download", status_code=202)
    def model_download(model_id: str):
        with tasks.lock:
            if "download" in tasks.active:
                raise ControlError("busy", "模型下载正在运行", 409)
        instance = manager()
        if not any(
            r["id"] == model_id and r.get("managed") for r in model_call(instance.list_models)
        ):
            raise ControlError("not_found", "模型未注册", 404)
        return tasks.start(
            "download", lambda: {"id": model_call(instance.download, model_id)["id"]}
        )

    @app.delete("/api/models/{model_id}")
    def delete_model(model_id: str, payload: DeleteRequest):
        with jobs.lock:
            if jobs.active_job_id:
                control = jobs.read_json(
                    provider.snapshot().work_dir / jobs.active_job_id / "control.json"
                )
                if not control.get("demo") and control.get("asr_model_id") == model_id:
                    raise ControlError("model_in_use", "运行中的任务正在使用此模型", 409)
            return model_call(manager().delete, model_id, payload.confirm)

    @app.post("/api/models/{model_id}/default")
    def default_model(model_id: str):
        with provider.lock:
            if provider.read_only():
                raise ControlError("read_only_mode", "当前部署的配置只读", 409)
            result = model_call(manager().use_default, model_id)
            local = provider.root / "configs/local.yaml"
            if local.exists():
                local.chmod(0o600)
            provider.reload()
            return result

    return app


app = create_app()
