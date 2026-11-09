"""项目内模型资产管理；扫描与加载不会触发联网。"""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yaml

_LOCK = threading.RLock()
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class ModelManager:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.models = self.root / "models"
        self._safe(self.models)
        data = yaml.safe_load((self.root / "configs/model-catalog.yaml").read_text())
        entries = data["models"]
        self.catalog = {}
        for entry in entries:
            model_id = entry["id"]
            self._validate_id(model_id)
            if entry["kind"] not in {"asr", "align"} or model_id in self.catalog:
                raise ValueError("模型注册表类型或 id 无效")
            if not re.fullmatch(r"[a-fA-F0-9]{40}", entry["revision"]):
                raise ValueError("模型 revision 必须固定到 commit hash")
            for name in entry["required_files"]:
                path = Path(name)
                if path.is_absolute() or ".." in path.parts or not path.parts:
                    raise ValueError("模型必需文件路径无效")
            self.catalog[model_id] = entry

    @staticmethod
    def _validate_id(model_id: str) -> None:
        if not isinstance(model_id, str) or not _ID.fullmatch(model_id) or model_id in {".", ".."}:
            raise ValueError("模型 id 无效")

    def _safe(self, path: Path) -> Path:
        # 连模型根自身也不允许重定向；目录内链接同样拒绝，避免递归环与别名误删。
        if not path.is_relative_to(self.models):
            raise ValueError("模型路径越界")
        for part in (path, *path.parents):
            if part == self.root:
                break
            if part.is_symlink():
                raise ValueError(f"模型路径不允许符号链接: {part}")
        resolved = path.resolve()
        if not resolved.is_relative_to(self.models):
            raise ValueError("模型路径逃逸")
        return path

    def _tree(self, path: Path) -> list[Path]:
        self._safe(path)
        files = []
        if path.exists() and not path.is_dir():
            raise ValueError(f"模型目录无效: {path}")
        if path.exists():
            for child in path.iterdir():
                self._safe(child)
                if child.is_dir():
                    files.extend(self._tree(child))
                elif child.is_file():
                    files.append(child)
                else:
                    raise ValueError(f"模型目录含特殊文件: {child}")
        return files

    def _target(self, model_id: str) -> Path:
        self._validate_id(model_id)
        if model_id not in self.catalog:
            raise ValueError(f"未注册的模型: {model_id}")
        return self._safe(self.models / self.catalog[model_id]["kind"] / model_id)

    def _inspect(self, path: Path, entry: dict | None) -> tuple[str, int, list[str]]:
        files = self._tree(path)
        size = sum(f.stat().st_size for f in files)
        if path.name.startswith("models--") or any("snapshots" in f.relative_to(path).parts for f in files):
            return "legacy", size, ["Hub 缓存布局需要迁移"]
        if entry is None:
            return "unmanaged", size, ["未注册，不允许加载"]
        issues = []
        if any(f.name.endswith((".incomplete", ".partial")) for f in path.rglob("*") if path.exists()):
            issues.append("存在未完成下载标记")
        for name in entry["required_files"]:
            file = self._safe(path / name)
            if not file.is_file():
                issues.append(f"缺少文件: {name}")
                continue
            minimum = entry.get("min_bytes", {}).get(name, 1)
            if file.stat().st_size < minimum:
                issues.append(f"文件过小: {name}")
            if file.stat().st_size < 1024:
                with file.open("rb") as stream:
                    if b"version https://git-lfs" in stream.read(1024):
                        issues.append(f"LFS pointer: {name}")
        return ("partial" if issues else "complete"), size, issues

    def _default_id(self) -> str | None:
        value = None
        for filename in ("default.yaml", "local.yaml"):
            path = self.root / "configs" / filename
            if path.exists():
                data = yaml.safe_load(path.read_text()) or {}
                value = (data.get("asr") or {}).get("model", value)
        return value

    def list_models(self) -> list[dict]:
        with _LOCK:
            records = []
            default = self._default_id()
            seen = set()
            for model_id, entry in self.catalog.items():
                path = self._target(model_id)
                state, size, issues = self._inspect(path, entry)
                partial = self._safe(self.models / ".downloads" / f"{model_id}.partial")
                if not path.exists():
                    if partial.exists():
                        _, size, _ = self._inspect(partial, entry)
                        state, issues = "partial", ["下载尚未安装"]
                    else:
                        state, issues = "missing", ["尚未安装"]
                records.append(dict(id=model_id, kind=entry["kind"], path=str(path),
                                    state=state, size_bytes=size, supported=entry["status"] == "supported",
                                    status=entry["status"], managed=True, license=entry["license"],
                                    is_default=model_id == default, issues=issues,
                                    family=entry.get("family", model_id),
                                    family_name=entry.get("family_name", model_id),
                                    variant=entry.get("variant", model_id),
                                    description=entry.get("description", ""),
                                    runtime=entry.get("runtime", "")))
                seen.add((entry["kind"], model_id))
            for kind in ("asr", "align"):
                parent = self._safe(self.models / kind)
                if parent.exists():
                    for path in sorted(parent.iterdir()):
                        self._safe(path)
                        if (kind, path.name) in seen or not path.is_dir():
                            continue
                        self._validate_id(path.name)
                        state, size, issues = self._inspect(path, None)
                        records.append(dict(id=path.name, kind=kind, path=str(path), state=state,
                                            size_bytes=size, supported=False, managed=False,
                                            is_default=False, issues=issues))
            return records

    def _manifest(self) -> None:
        records = self.list_models()
        self._safe(self.models).mkdir(parents=True, exist_ok=True)
        target = self._safe(self.models / "manifest.json")
        temp = self.models / f".manifest-{uuid4().hex}.tmp"
        try:
            temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)

    def resolve_model_path(self, model_id: str) -> Path:
        path = self._target(model_id)
        entry = self.catalog[model_id]
        if entry["kind"] != "asr" or entry["status"] != "supported":
            raise ValueError(f"模型尚不支持运行: {model_id}")
        state, _, issues = self._inspect(path, entry)
        if state != "complete":
            raise FileNotFoundError(f"本地模型未就绪: {model_id} ({'; '.join(issues)})；请显式下载模型")
        return path

    def download(self, model_id: str) -> dict:
        with _LOCK:
            target = self._target(model_id)
            entry = self.catalog[model_id]
            if entry["status"] == "deprecated":
                raise ValueError("已弃用模型不允许下载")
            if self._inspect(target, entry)[0] == "complete":
                return next(r for r in self.list_models() if r["id"] == model_id and r["managed"])
            partial = self._safe(self.models / ".downloads" / f"{model_id}.partial")
            self._tree(partial)
            cache = self._safe(self.models / ".downloads" / ".hub-cache")
            self._tree(cache)
            partial.mkdir(parents=True, exist_ok=True)
            cache.mkdir(parents=True, exist_ok=True)
            # 仅用户显式下载时导入，显式指定所有缓存路径，不修改全局环境。
            from huggingface_hub import snapshot_download

            kwargs = {}
            if os.environ.get("CUELOOM_HF_ENDPOINT"):
                kwargs["endpoint"] = os.environ["CUELOOM_HF_ENDPOINT"]
            snapshot_download(repo_id=entry["repo_id"], revision=entry["revision"],
                              local_dir=str(partial), cache_dir=str(cache),
                              allow_patterns=entry["required_files"], max_workers=4, **kwargs)
            state, _, issues = self._inspect(partial, entry)
            if state != "complete":
                raise ValueError(f"下载模型校验失败: {issues}")
            target.parent.mkdir(parents=True, exist_ok=True)
            self._safe(target)
            self._tree(target)
            if target.exists():
                self._move_to_trash(target, model_id)
            partial.rename(target)
            self._manifest()
            return next(r for r in self.list_models() if r["id"] == model_id and r["managed"])

    def _move_to_trash(self, path: Path, model_id: str) -> Path:
        self._tree(path)
        trash = self._safe(self.models / ".trash")
        trash.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = self._safe(trash / f"{model_id}-{timestamp}-{uuid4().hex}")
        path.rename(destination)
        return destination

    def delete(self, model_id: str, confirm: str) -> dict:
        with _LOCK:
            self._validate_id(model_id)
            if confirm != model_id:
                raise ValueError("删除需要完整模型 id 二次确认")
            matches = [r for r in self.list_models() if r["id"] == model_id]
            if len(matches) != 1:
                raise ValueError("模型不存在或 id 不唯一")
            record = matches[0]
            path = self._safe(Path(record["path"]))
            if record["is_default"]:
                pid_file = self.root / "work/ctl/server.pid"
                if pid_file.exists():
                    try:
                        pid = int(pid_file.read_text().strip())
                        if pid <= 0:
                            raise ValueError("服务 PID 无效")
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        pass
                    except (ValueError, PermissionError):
                        raise RuntimeError("无法确认默认模型是否被服务占用") from None
                    else:
                        raise RuntimeError("默认模型正在被服务使用，请先停止服务或切换模型")
            if not path.exists():
                path = self._safe(self.models / ".downloads" / f"{model_id}.partial")
            if not path.is_dir():
                raise FileNotFoundError(f"模型未安装: {model_id}")
            destination = self._move_to_trash(path, model_id)
            self._manifest()
            return dict(id=model_id, path=str(destination), state="deleted")

    def use_default(self, model_id: str) -> dict:
        with _LOCK:
            path = self.resolve_model_path(model_id)
            local = self.root / "configs/local.yaml"
            if local.is_symlink() or local.parent.resolve() != self.root / "configs":
                raise ValueError("local.yaml 及其父目录不允许符号链接")
            data = yaml.safe_load(local.read_text()) if local.exists() else {}
            data = data or {}
            data.setdefault("asr", {}).update(backend="faster-whisper", model=model_id)
            temp = local.with_name(f".local-{uuid4().hex}.tmp")
            try:
                temp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
                temp.replace(local)
            finally:
                temp.unlink(missing_ok=True)
            return dict(id=model_id, path=str(path), is_default=True)
