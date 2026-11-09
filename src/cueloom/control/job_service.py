"""上传素材、单飞任务、字幕产物与内存后台任务。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

from cueloom import pipeline
from cueloom.control.config_service import ConfigProvider, atomic_write
from cueloom.control.guards import ControlError, safe_under

SUBTITLES = {".srt", ".vtt", ".ass"}
MEDIA = {".mp4", ".mkv", ".mov", ".wav", ".mp3", ".m4a", ".flac", ".webm", ".ogg"}


class TaskRegistry:
    def __init__(self):
        self.lock = threading.RLock()
        self.tasks = {}
        self.active = set()

    def start(self, kind, function, task_id=None):
        with self.lock:
            if kind in self.active:
                raise ControlError("busy", "同类任务正在运行", 409)
            tid = task_id or uuid4().hex
            self.active.add(kind)
            self.tasks[tid] = {
                "task_id": tid,
                "state": "running",
                "kind": kind,
                "bytes_done": None,
                "bytes_total": None,
                "message": "执行中",
            }

        def worker():
            try:
                result = function()
                with self.lock:
                    failed = isinstance(result, dict) and result.get("status") == "failed"
                    self.tasks[tid].update(
                        state="failed" if failed else "done",
                        result=result,
                        message="流水线失败，请检查任务阶段" if failed else "已完成",
                    )
            except Exception:
                with self.lock:
                    self.tasks[tid].update(state="failed", message="任务失败，请检查配置与本地资源")
            finally:
                with self.lock:
                    self.active.discard(kind)

        try:
            threading.Thread(target=worker, daemon=True, name=f"cueloom-{kind}").start()
        except Exception:
            with self.lock:
                self.active.discard(kind)
                self.tasks[tid].update(state="failed", message="无法启动后台线程")
            raise
        return {"task_id": tid, "state": "running"}

    def get(self, tid):
        with self.lock:
            if tid not in self.tasks:
                raise ControlError("not_found", "任务不存在", 404)
            return dict(self.tasks[tid])


class JobService:
    def __init__(self, provider: ConfigProvider, tasks: TaskRegistry):
        self.provider, self.tasks = provider, tasks
        self.active_job_id = None
        self.lock = threading.RLock()

    async def upload(self, request):
        root = self.provider.root / "inbox"
        try:
            name = unquote(request.headers.get("x-filename", ""), errors="strict")
        except UnicodeError:
            raise ControlError("invalid_path", "文件名编码无效") from None
        suffix = Path(name).suffix.lower()
        if (
            not name
            or len(name) > 255
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or len(name.encode("utf-8")) > 255
            or "/" in name
            or "\\" in name
            or suffix not in MEDIA
        ):
            raise ControlError("invalid_path", "素材名称或后缀无效")
        limit = int(os.environ.get("CUELOOM_MAX_UPLOAD_MB", "500")) * 1024 * 1024
        length = request.headers.get("content-length")
        if length and (not length.isdecimal() or int(length) > limit):
            raise ControlError("payload_too_large", "上传超过大小限额", 413)
        uid = uuid4().hex
        folder = safe_under(root, uid)
        folder.mkdir(parents=True)
        partial = folder / ".partial"
        size = 0
        try:
            with partial.open("xb") as stream:
                os.chmod(partial, 0o600)
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > limit:
                        raise ControlError("payload_too_large", "上传超过大小限额", 413)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if length is not None and int(length) != size:
                raise ControlError("invalid_config", "上传长度与声明不一致")
            if size == 0:
                raise ControlError("invalid_config", "不能上传空文件")
            partial.replace(folder / ("media" + suffix))
            info = {"upload_id": uid, "name": name, "size": size, "suffix": suffix}
            atomic_write(folder / "upload.json", json.dumps(info, ensure_ascii=False))
            return info
        except BaseException:
            shutil.rmtree(folder)
            raise

    def submit(self, payload):
        with self.lock:
            if self.active_job_id:
                raise ControlError("busy", "已有流水线正在运行", 409)
            cfg = self.provider.snapshot()
            if payload.demo and payload.upload_id is not None:
                raise ControlError("invalid_config", "演示素材与上传素材不能同时指定")
            if payload.demo:
                source = cfg.root / "tests/fixtures/demo.wav"
                cfg.raw.setdefault("asr", {})["backend"] = "mock"
                cfg.llm.base_url = ""
                cfg.llm._api_key = ""
            else:
                if not cfg.llm.configured:
                    raise ControlError("invalid_config", "非演示任务需要完整 LLM 配置")
                if (
                    cfg.raw.get("asr", {}).get("backend", "faster-whisper").lower()
                    != "faster-whisper"
                ):
                    raise ControlError("invalid_config", "Mock 仅可用于显式演示任务")
                folder = safe_under(cfg.root / "inbox", payload.upload_id or "")
                info = self.read_json(safe_under(folder, "upload.json"))
                source = safe_under(folder, "media" + info["suffix"])
            if not source.is_file():
                raise ControlError("not_found", "素材不存在", 404)
            jid = uuid4().hex
            job = pipeline.create_job(
                source,
                payload.target_lang,
                bilingual=payload.bilingual,
                formats=payload.formats,
                job_id=jid,
            )
            directory = safe_under(cfg.work_dir, jid)
            config_snapshot = cfg.model_dump(mode="json")
            # 密钥只保留在内存 Config 中，不参与可下载记录或公开摘要。
            config_snapshot.pop("root", None)
            config_snapshot.pop("work_dir", None)
            config_snapshot.pop("out_dir", None)
            config_snapshot["raw"].pop("llm", None)
            config_snapshot["llm"].pop("api_key_env", None)
            config_snapshot["job"] = {
                "target_lang": payload.target_lang,
                "bilingual": payload.bilingual,
                "formats": payload.formats,
                "demo": payload.demo,
            }
            digest = hashlib.sha256(
                json.dumps(config_snapshot, sort_keys=True).encode()
            ).hexdigest()
            atomic_write(
                directory / "control.json",
                json.dumps(
                    {
                        "demo": payload.demo,
                        "mock": payload.demo,
                        "config_digest": digest,
                        "asr_model_id": cfg.raw.get("asr", {}).get("model"),
                    }
                ),
            )
            pipeline._save_job_state(directory, job, [])
            self.active_job_id = jid

            def execute():
                try:
                    result = pipeline.run(job, cfg)
                    return {"job_id": jid, "status": result.status, "demo": payload.demo}
                except Exception:
                    job.status = "failed"
                    pipeline._save_job_state(directory, job, [])
                    raise
                finally:
                    with self.lock:
                        self.active_job_id = None

            try:
                task = self.tasks.start("pipeline", execute, jid)
            except Exception:
                self.active_job_id = None
                raise
            return {
                "job_id": jid,
                "status": "created",
                "demo": payload.demo,
                "mock": payload.demo,
                "note": "演示使用 Mock ASR 与 Mock LLM" if payload.demo else "真实任务",
                **task,
            }

    def recover_interrupted(self):
        cfg = self.provider.snapshot()
        for record in self.list_jobs():
            if record.get("status") in {"created", "running"}:
                path = safe_under(cfg.work_dir, record["job_id"], "job.json")
                data = self.read_json(path)
                data.update(status="interrupted", resume_hint="服务曾中断，请通过 CLI resume 续跑")
                atomic_write(path, json.dumps(data, ensure_ascii=False))

    @staticmethod
    def read_json(path):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ControlError("not_found", "记录不存在", 404) from None

    def detail(self, jid):
        cfg = self.provider.snapshot()
        data = self.read_json(safe_under(cfg.work_dir, jid, "job.json"))
        # 不将本机路径与历史异常正文暴露到网络。
        data.pop("input_path", None)
        control = safe_under(cfg.work_dir, jid, "control.json")
        if control.exists():
            data["demo"] = bool(self.read_json(control).get("demo"))
            data["mock"] = data["demo"]
        for result in data.get("stage_results", []):
            result["warnings"] = (
                ["阶段存在警告，请检查本机任务记录"] if result.get("warnings") else []
            )
        return data

    def list_jobs(self):
        root = self.provider.snapshot().work_dir
        rows = []
        if root.exists():
            for path in sorted(root.glob("*/job.json"), reverse=True):
                try:
                    rows.append(self.detail(path.parent.name))
                except ControlError:
                    continue
        return rows

    def artifact(self, jid, name):
        root = self.provider.snapshot().out_dir
        path = safe_under(root, jid, name)
        if path.suffix.lower() not in SUBTITLES or not path.is_file():
            raise ControlError("not_found", "字幕不存在", 404)
        return path

    def artifacts(self, jid):
        folder = safe_under(self.provider.snapshot().out_dir, jid)
        if not folder.is_dir():
            return []
        rows = []
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in SUBTITLES:
                try:
                    file = self.artifact(jid, path.name)
                except ControlError:
                    continue
                rows.append(
                    {
                        "name": file.name,
                        "size": file.stat().st_size,
                        "format": file.suffix[1:],
                        "url": f"/api/jobs/{jid}/artifacts/{file.name}",
                    }
                )
        return rows
