"""请求边界与路径护栏，不信任代理声明。"""

from __future__ import annotations

import hmac
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from starlette.requests import Request


class ControlError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status


def safe_under(root: Path, *parts: str) -> Path:
    if any(not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", p) or ".." in p for p in parts):
        raise ControlError("invalid_path", "路径标识无效")
    path = root.joinpath(*parts)
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ControlError("invalid_path", "不允许符号链接")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ControlError("invalid_path", "路径越界")
    return path


def loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def authorize(request: Request, token: str) -> dict:
    local = bool(request.client and loopback(request.client.host))
    if any(
        h in request.headers
        for h in ("forwarded", "x-forwarded-for", "x-real-ip", "x-forwarded-proto")
    ):
        local = False
    host = request.headers.get("host", "")
    try:
        parsed = urlsplit("//" + host)
        valid_host = bool(
            len(request.headers.getlist("host")) == 1
            and re.fullmatch(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::[0-9]{1,5})?", host)
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
        )
        _ = parsed.port
    except ValueError:
        valid_host = False
    if not valid_host or (local and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}):
        raise ControlError("csrf_rejected", "Host 不受信任", 403)
    authenticated = local or bool(
        len(token) >= 32
        and hmac.compare_digest(
            request.headers.get("authorization", "").encode("utf-8"),
            ("Bearer " + token).encode("utf-8"),
        )
    )
    if not authenticated:
        raise ControlError("unauthorized", "远程访问需要 Bearer token", 401)
    if not local and request.url.scheme != "https":
        raise ControlError("unauthorized", "远程访问必须使用 HTTPS 或回环安全隧道", 401)
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{host}":
        raise ControlError("csrf_rejected", "必须使用同源请求", 403)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("x-cueloom-client") != "web":
            raise ControlError("csrf_rejected", "缺少 X-Cueloom-Client: web", 403)
    return {"authenticated": True, "local": local, "mode": "local" if local else "token"}
