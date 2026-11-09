"""白名单配置、脱敏快照与原子落盘。"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from dotenv import dotenv_values

from cueloom.config import Config, _merge, load_config, project_root
from cueloom.control.guards import ControlError


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ControlError("invalid_path", "配置路径不允许符号链接")
    fd, name = tempfile.mkstemp(prefix=".cueloom-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


ENV_KEYS = {
    "llm.base_url": "CUELOOM_LLM_BASE_URL",
    "llm.model": "CUELOOM_LLM_MODEL",
    "llm.api_key": "CUELOOM_LLM_API_KEY",
    "llm.max_concurrency": "CUELOOM_LLM_CONCURRENCY",
}
# 仅列出数据面已接线的参数。
RULES = {
    "llm.base_url": (str, None),
    "llm.model": (str, None),
    "llm.api_key": (str, None),
    "llm.timeout_sec": (int, (1, 300)),
    "llm.max_retries": (int, (1, 10)),
    "llm.batch_max_items": (int, (1, 200)),
    "llm.batch_max_tokens": (int, (1, 32000)),
    "llm.context_window": (int, (0, 20)),
    "llm.cache": (bool, None),
    "segment.max_cps": (int, (1, 100)),
    "segment.min_cps": (int, (1, 100)),
    "segment.max_chars_per_line": (int, (1, 200)),
    "segment.max_lines": (int, (1, 4)),
    "segment.min_duration_sec": (float, (0.1, 30)),
    "segment.max_duration_sec": (float, (0.1, 60)),
    "output.bilingual": (bool, None),
    "output.formats": (list, None),
    "output.bilingual_order": (str, ("source_first", "target_first")),
}


def flatten(data: dict) -> dict:
    out = {}
    for key, value in data.items():
        if isinstance(value, dict):
            out.update({f"{key}.{k}": v for k, v in flatten(value).items()})
        else:
            out[key] = value
    return out


def upsert_env(text: str, updates: dict) -> str:
    lines, seen = [], set()
    for line in text.splitlines():
        match = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        key = match[1] if match else None
        if key in updates:
            if key not in seen:
                lines.append(f"{key}={json.dumps(updates[key], ensure_ascii=False)}")
                seen.add(key)
        else:
            lines.append(line)
    lines.extend(
        f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in updates.items() if k not in seen
    )
    return "\n".join(lines) + "\n"


class ConfigProvider:
    def __init__(self, root: Path | None = None):
        self.root = (root or project_root()).resolve()
        self.lock = threading.RLock()
        disk = dotenv_values(self.root / ".env", interpolate=False)
        self._owned_env = {
            key: value
            for key, value in disk.items()
            if key in {*ENV_KEYS.values(), "CUELOOM_LLM_API_KEY_ENV"}
            and key in os.environ
            and os.environ[key] == value
        }
        self._cfg = load_config(self.root)

    def snapshot(self) -> Config:
        with self.lock:
            return self._cfg.model_copy(deep=True)

    def reload(self) -> Config:
        with self.lock:
            disk = dotenv_values(self.root / ".env", interpolate=False)
            for key, previous in list(self._owned_env.items()):
                if os.environ.get(key) != previous:
                    self._owned_env.pop(key)
                    continue
                value = disk.get(key)
                if value is None:
                    os.environ.pop(key, None)
                    self._owned_env.pop(key)
                else:
                    os.environ[key] = value
                    self._owned_env[key] = value
            self._cfg = load_config(self.root)
            return self.snapshot()

    def overridden(self, key: str) -> bool:
        env = ENV_KEYS.get(key)
        if key == "llm.api_key":
            env = self._cfg.llm.api_key_env
        return bool(env and env in os.environ and os.environ[env] != self._owned_env.get(env))

    def read_only(self) -> bool:
        return (
            os.environ.get("CUELOOM_CONFIG_READ_ONLY", "").lower() in {"1", "true"}
            or Path("/.dockerenv").exists()
        )

    def public(self) -> dict:
        with self.lock:
            cfg = self.snapshot()
            values = {k: v for k, v in flatten(cfg.raw).items() if k in RULES}
            for key in RULES:
                if key.startswith("llm.") and key != "llm.api_key":
                    values[key] = getattr(cfg.llm, key.split(".")[1])
            nested = {}
            schema = []
            for key, (kind, bounds) in RULES.items():
                section, field = key.split(".")
                if key != "llm.api_key":
                    nested.setdefault(section, {})[field] = values.get(key)
                schema.append(
                    {
                        "key": key,
                        "type": kind.__name__,
                        "target": ".env"
                        if key in {"llm.base_url", "llm.model", "llm.api_key"}
                        else "configs/local.yaml",
                        "sensitive": key == "llm.api_key",
                        "range": bounds if kind in {int, float} else None,
                        "enum": bounds if kind is str else None,
                        "restart_required": False,
                        "overridden_by_env": self.overridden(key),
                        "editable": not self.overridden(key) and not self.read_only(),
                    }
                )
            nested.setdefault("llm", {}).update(
                api_key_configured=bool(cfg.llm.api_key), configured=cfg.llm.configured
            )
            return {
                "config": nested,
                "schema": schema,
                "editable": not self.read_only(),
                "reason": "container_or_read_only" if self.read_only() else "",
                "restart_required": False,
                "note": "配置只对下一次任务生效，运行中任务使用快照",
            }

    def save(self, payload: dict) -> dict:
        changes = flatten(payload)
        with self.lock:
            if self.read_only():
                raise ControlError("read_only_mode", "当前部署的配置只读", 409)
            for key, value in changes.items():
                if key not in RULES:
                    raise ControlError("invalid_key", "包含不支持的配置字段")
                kind, bounds = RULES[key]
                valid = type(value) is kind or (kind is float and type(value) in {int, float})
                if not valid:
                    raise ControlError("invalid_config", "配置类型无效")
                if isinstance(value, str) and (
                    len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value)
                ):
                    raise ControlError("invalid_config", "字符串含控制字符或过长")
                if bounds and kind in {int, float} and not bounds[0] <= value <= bounds[1]:
                    raise ControlError("invalid_config", "配置超出范围")
                if bounds and kind is str and value not in bounds:
                    raise ControlError("invalid_config", "配置枚举无效")
                if key == "output.formats" and (
                    not value
                    or any(not isinstance(v, str) or v not in {"srt", "vtt", "ass"} for v in value)
                ):
                    raise ControlError("invalid_config", "字幕格式无效")
                if key == "llm.model" and (not value.strip() or len(value) > 256):
                    raise ControlError("invalid_config", "模型名称无效")
                if key == "llm.base_url":
                    try:
                        url = urlsplit(value)
                        _ = url.port
                    except ValueError:
                        raise ControlError("invalid_config", "LLM 地址无效") from None
                    if (
                        url.scheme not in {"http", "https"}
                        or not url.hostname
                        or url.username
                        or url.password
                        or url.query
                        or url.fragment
                        or url.path.rstrip("/").endswith("/chat/completions")
                    ):
                        raise ControlError(
                            "invalid_config", "LLM 地址必须为不含凭证的 HTTP(S) API 根地址"
                        )
            env_updates, local_updates = {}, {}
            for key, value in changes.items():
                if key in {"llm.base_url", "llm.model", "llm.api_key"}:
                    env_key = self._cfg.llm.api_key_env if key == "llm.api_key" else ENV_KEYS[key]
                    env_updates[env_key] = value
                else:
                    section, field = key.split(".")
                    local_updates.setdefault(section, {})[field] = value
            local = self.root / "configs/local.yaml"
            data = yaml.safe_load(local.read_text()) if local.exists() else {}
            data = _merge(data or {}, local_updates)
            segment = _merge(self._cfg.raw.get("segment", {}), local_updates.get("segment", {}))
            for low, high in (("min_cps", "max_cps"), ("min_duration_sec", "max_duration_sec")):
                if low in segment and high in segment and segment[low] > segment[high]:
                    raise ControlError("invalid_config", "参数最小值不能大于最大值")
            env = self.root / ".env"
            if env_updates:
                text = env.read_text() if env.exists() else ""
                if env.exists():
                    atomic_write(self.root / ".env.bak", text)
                atomic_write(env, upsert_env(text, env_updates))
            if local_updates:
                atomic_write(local, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
            self.reload()
            result = self.public()
            result["overridden_by_env"] = [k for k in changes if self.overridden(k)]
            return result

    def _profiles(self) -> dict:
        path = self.root / "configs/llm-profiles.json"
        if path.is_symlink():
            raise ControlError("invalid_path", "配置方案路径不允许符号链接")
        if not path.exists():
            return {"active_id": None, "profiles": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data.get("profiles"), dict):
                raise ValueError()
            return data
        except (ValueError, OSError):
            raise ControlError("invalid_config", "配置方案文件无法读取，请检查本地文件") from None

    def profiles_public(self) -> dict:
        with self.lock:
            data = self._profiles()
            cfg = self.snapshot().llm
            records = []
            for pid, item in data["profiles"].items():
                matches = all(item.get(key, "") == getattr(cfg, key) for key in ("base_url", "model", "api_key"))
                records.append({"id": pid, "name": item["name"], "base_url": item["base_url"],
                                "model": item["model"], "api_key_configured": bool(item.get("api_key")),
                                "selected": pid == data.get("active_id"),
                                "active": pid == data.get("active_id") and matches})
            return {"profiles": records, "editable": not self.read_only(),
                    "switchable": not self.read_only() and not any(
                        self.overridden(key) for key in ("llm.base_url", "llm.model", "llm.api_key"))}

    def save_profile(self, payload: dict, pid: str | None = None) -> dict:
        from uuid import uuid4
        with self.lock:
            if self.read_only():
                raise ControlError("read_only_mode", "当前部署的配置只读", 409)
            data = self._profiles()
            if pid is not None and pid not in data["profiles"]:
                raise ControlError("not_found", "配置方案不存在", 404)
            if set(payload) - {"name", "base_url", "model", "api_key"}:
                raise ControlError("invalid_key", "配置方案包含不支持的字段")
            item = dict(data["profiles"].get(pid, {}))
            item.update(payload)
            for key in ("name", "base_url", "model", "api_key"):
                value = item.get(key, "")
                if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise ControlError("invalid_config", "配置方案字段类型或字符无效")
                item[key] = value if key == "api_key" else value.strip()
            if not item["name"] or len(item["name"]) > 80 or not item["model"] or len(item["model"]) > 256:
                raise ControlError("invalid_config", "方案名称和模型名称不能为空或过长")
            try:
                url = urlsplit(item["base_url"])
                _ = url.port
                valid = url.scheme in {"http", "https"} and url.hostname and not (
                    url.username or url.password or url.query or url.fragment or
                    url.path.rstrip("/").endswith("/chat/completions"))
            except ValueError:
                valid = False
            if not valid:
                raise ControlError("invalid_config", "请填写不含凭证的 HTTP(S) API 根地址")
            if any(p["name"] == item["name"] and other != pid for other, p in data["profiles"].items()):
                raise ControlError("conflict", "配置方案名称已存在", 409)
            pid = pid or uuid4().hex
            data["profiles"][pid] = item
            atomic_write(self.root / "configs/llm-profiles.json", json.dumps(data, ensure_ascii=False, indent=2))
            return self.profiles_public()

    def activate_profile(self, pid: str) -> dict:
        with self.lock:
            if not self.profiles_public()["switchable"]:
                raise ControlError("read_only_mode", "配置只读或被环境变量覆盖，无法切换方案", 409)
            data = self._profiles()
            item = data["profiles"].get(pid)
            if item is None:
                raise ControlError("not_found", "配置方案不存在", 404)
            self.save({"llm": {key: item[key] for key in ("base_url", "model", "api_key")}})
            data["active_id"] = pid
            atomic_write(self.root / "configs/llm-profiles.json", json.dumps(data, ensure_ascii=False, indent=2))
            return self.profiles_public()

    def delete_profile(self, pid: str) -> dict:
        with self.lock:
            if self.read_only():
                raise ControlError("read_only_mode", "当前部署的配置只读", 409)
            data = self._profiles()
            if pid not in data["profiles"]:
                raise ControlError("not_found", "配置方案不存在", 404)
            if data.get("active_id") == pid:
                raise ControlError("conflict", "请先启用其他方案，再删除此方案", 409)
            del data["profiles"][pid]
            atomic_write(self.root / "configs/llm-profiles.json", json.dumps(data, ensure_ascii=False, indent=2))
            return self.profiles_public()

    def web_token(self) -> str:
        values = dotenv_values(self.root / ".env", interpolate=False)
        return os.environ.get("CUELOOM_WEB_TOKEN", values.get("CUELOOM_WEB_TOKEN") or "")
