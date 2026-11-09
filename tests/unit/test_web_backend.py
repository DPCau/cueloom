"""控制面离线测试；不启动端口、不下载模型、不连接真实 LLM。"""

import json
import os
import threading
from urllib.parse import quote

import pytest
import yaml
from fastapi.testclient import TestClient

from cueloom import pipeline
from cueloom.server import create_app

HEADERS = {"X-Cueloom-Client": "web"}


@pytest.fixture
def backend(tmp_path, monkeypatch):
    for key in list(os.environ):
        if key.startswith("CUELOOM_"):
            monkeypatch.delenv(key)
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/default.yaml").write_text(
        yaml.safe_dump(
            {
                "asr": {"backend": "faster-whisper", "model": "tiny"},
                "segment": {"min_cps": 12, "max_cps": 17},
                "output": {"formats": ["srt"], "bilingual": True},
            }
        )
    )
    (tmp_path / ".env").write_text(
        "# 保留注释\nUNKNOWN=keep\nCUELOOM_LLM_MODEL=old\nCUELOOM_LLM_MODEL=duplicate\n"
    )
    app = create_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 12345))
    return app, client, tmp_path


def configure(client):
    return client.put(
        "/api/config",
        headers=HEADERS,
        json={
            "llm": {
                "base_url": "https://llm.example/v1",
                "model": "test-model",
                "api_key": "secret-test-key",
            }
        },
    )


def test_llm_profiles_persistence_switch_and_secrets(backend, monkeypatch):
    app, client, root = backend
    first = {"name": "日常", "base_url": "https://one.example/v1", "model": "one", "api_key": "profile-secret-one"}
    r = client.post("/api/llm/profiles", headers=HEADERS, json=first)
    assert r.status_code == 201
    assert "profile-secret-one" not in r.text
    pid = r.json()["profiles"][0]["id"]
    assert app.state.provider.snapshot().llm.model != "one"
    assert (root / "configs/llm-profiles.json").stat().st_mode & 0o777 == 0o600
    assert client.post(f"/api/llm/profiles/{pid}/activate", headers=HEADERS).status_code == 200
    snapshot = app.state.provider.snapshot()
    from cueloom.control.config_service import ConfigProvider
    reopened = ConfigProvider(root)
    assert reopened.profiles_public()["profiles"][0]["active"]
    assert reopened.snapshot().llm.api_key == "profile-secret-one"
    remote = TestClient(app, base_url="https://service.example", client=("192.0.2.1", 1234))
    assert remote.get("/api/llm/profiles").status_code == 401
    assert snapshot.llm.api_key == "profile-secret-one"
    assert client.delete(f"/api/llm/profiles/{pid}", headers=HEADERS).status_code == 409
    assert client.put(f"/api/llm/profiles/{pid}", headers=HEADERS, json={"model": "updated"}).status_code == 200
    assert snapshot.llm.model == "one"
    assert not client.get("/api/llm/profiles").json()["profiles"][0]["active"]
    assert client.post(f"/api/llm/profiles/{pid}/activate", headers=HEADERS).status_code == 200
    assert app.state.provider.snapshot().llm.model == "updated"
    assert app.state.provider.snapshot().llm.api_key == "profile-secret-one"
    second = client.post("/api/llm/profiles/import-current", headers=HEADERS, json={"name": "备份"})
    assert second.status_code == 201
    assert "profile-secret-one" not in second.text
    other = next(p["id"] for p in second.json()["profiles"] if p["id"] != pid)
    client.post(f"/api/llm/profiles/{other}/activate", headers=HEADERS).raise_for_status()
    assert client.delete(f"/api/llm/profiles/{pid}", headers=HEADERS).status_code == 200
    monkeypatch.setenv("CUELOOM_LLM_MODEL", "external")
    assert client.post(f"/api/llm/profiles/{other}/activate", headers=HEADERS).status_code == 409
    app.state.provider.reload()
    assert app.state.provider.snapshot().llm.model == "external"


@pytest.mark.parametrize("payload", [
    {"name": "", "base_url": "https://ok.example", "model": "m"},
    {"name": "x", "base_url": "https://u:p@host", "model": "m"},
    {"name": "x", "base_url": "https://ok.example", "model": "m", "api_key": None},
])
def test_llm_profiles_validation(backend, payload):
    _, client, _ = backend
    assert client.post("/api/llm/profiles", headers=HEADERS, json=payload).status_code == 400


def test_unimplemented_settings_not_exposed(backend):
    _, client, _ = backend
    schema = {item["key"] for item in client.get("/api/config").json()["schema"]}
    for key in ("llm.max_concurrency", "output.max_cps_enforce"):
        assert key not in schema
        assert client.put("/api/config", headers=HEADERS, json={key: 2}).status_code == 400


def test_running_model_delete_uses_job_snapshot(backend):
    app, client, root = backend
    directory = root / "work" / "active"
    directory.mkdir(parents=True)
    (directory / "control.json").write_text(
        json.dumps({"demo": False, "asr_model_id": "tiny"})
    )
    app.state.jobs.active_job_id = "active"
    response = client.request(
        "DELETE", "/api/models/tiny", headers=HEADERS, json={"confirm": "tiny"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "model_in_use"


def test_config_persistence_snapshot_and_redaction(backend, monkeypatch):
    app, client, root = backend
    assert configure(client).status_code == 200
    snapshot = app.state.provider.snapshot()
    assert snapshot.llm.api_key == "secret-test-key"
    body = client.get("/api/config").json()
    assert "secret-test-key" not in json.dumps(body)
    assert body["config"]["llm"]["api_key_configured"]
    assert (
        client.put("/api/config", headers=HEADERS, json={"segment.max_cps": 20}).status_code == 200
    )
    assert (
        client.put("/api/config", headers=HEADERS, json={"llm.api_key": "new-key"}).status_code
        == 200
    )
    assert snapshot.llm.api_key == "secret-test-key"
    monkeypatch.setenv("CUELOOM_LLM_API_KEY", "external-key")
    assert snapshot.llm.api_key == "secret-test-key"
    body = client.put("/api/config", headers=HEADERS, json={"llm.api_key": "disk-key"}).json()
    assert body["overridden_by_env"] == ["llm.api_key"]
    assert app.state.provider.snapshot().llm.api_key == "external-key"
    text = (root / ".env").read_text()
    assert "# 保留注释" in text and "UNKNOWN=keep" in text
    assert text.count("CUELOOM_LLM_MODEL=") == 1
    for file in (".env", ".env.bak", "configs/local.yaml"):
        assert (root / file).stat().st_mode & 0o777 == 0o600
    assert "api_key" not in (root / "configs/local.yaml").read_text()


@pytest.mark.parametrize(
    "payload",
    [
        {"llm.model": "bad\nkey"},
        {"unknown": 1},
        {"llm.base_url": "https://user:password@example.com"},
        {"output.formats": ["mp4"]},
        {"llm.api_key": None},
        {"segment.max_cps": 1},
        {"output.formats": [["srt"]]},
        {"llm.base_url": "https://[broken"},
    ],
)
def test_config_rejects_invalid(backend, payload):
    _, client, _ = backend
    assert client.put("/api/config", headers=HEADERS, json=payload).status_code == 400


def test_auth_remote_all_business_routes_and_proxy(backend, monkeypatch):
    app, client, _ = backend
    remote = TestClient(app, base_url="https://service.example", client=("192.0.2.1", 1234))
    for path in (
        "/api/config",
        "/api/status",
        "/api/jobs",
        "/api/models",
        "/api/tasks/x",
        "/api/jobs/x/artifacts/x.srt",
    ):
        assert remote.get(path).status_code == 401
    assert remote.get("/api/health").status_code == 200
    assert remote.get("/api/auth").json()["authenticated"] is False
    monkeypatch.setenv("CUELOOM_WEB_TOKEN", "x" * 40)
    assert (
        remote.get("/api/config", headers={"Authorization": "Bearer " + "x" * 40}).status_code
        == 200
    )
    assert remote.get("/api/config", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 401
    assert client.get("/api/config", headers={"X-Forwarded-For": "192.0.2.1"}).status_code == 401
    assert client.get("/api/config", headers={"Host": "evil.example"}).status_code == 403
    assert client.get("/api/config", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.put("/api/config", json={}).status_code == 403
    assert client.get("/api/auth").json()["password_enabled"] is False
    insecure = TestClient(app, base_url="http://service.example", client=("192.0.2.1", 1234))
    assert (
        insecure.get("/api/config", headers={"Authorization": "Bearer " + "x" * 40}).status_code
        == 401
    )


def test_upload_chinese_unique_limit_and_paths(backend, monkeypatch):
    _, client, root = backend
    headers = {**HEADERS, "X-Filename": quote("中文素材.wav")}
    first = client.post("/api/uploads", headers=headers, content=b"wave")
    second = client.post("/api/uploads", headers=headers, content=b"wave")
    assert first.status_code == 201
    assert first.json()["name"] == "中文素材.wav"
    assert first.json()["upload_id"] != second.json()["upload_id"]
    assert (
        client.post(
            "/api/uploads", headers={**HEADERS, "X-Filename": "../x.wav"}, content=b"x"
        ).status_code
        == 400
    )
    monkeypatch.setenv("CUELOOM_MAX_UPLOAD_MB", "0")
    assert client.post("/api/uploads", headers=headers, content=b"x").status_code == 413
    assert len(list((root / "inbox").iterdir())) == 2
    assert not list(root.rglob(".partial"))


def test_jobs_single_flight_snapshot_and_safe_download(backend, monkeypatch):
    app, client, root = backend
    configure(client)
    upload = client.post(
        "/api/uploads", headers={**HEADERS, "X-Filename": "source.wav"}, content=b"wav"
    ).json()
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    captured = []

    def run(job, cfg):
        captured.append(cfg)
        entered.set()
        release.wait(5)
        job.status = "done"
        pipeline._save_job_state(cfg.work_dir / job.job_id, job, [])
        finished.set()
        return job

    monkeypatch.setattr(pipeline, "run", run)
    response = client.post(
        "/api/jobs", headers=HEADERS, json={"upload_id": upload["upload_id"], "demo": False}
    )
    assert response.status_code == 202
    try:
        assert entered.wait(2)
        assert (
            client.post(
                "/api/jobs", headers=HEADERS, json={"upload_id": upload["upload_id"]}
            ).status_code
            == 409
        )
        client.put("/api/config", headers=HEADERS, json={"llm.api_key": "changed-key"})
        assert captured[0].llm.api_key == "secret-test-key"
        jid = response.json()["job_id"]
        folder = root / "out" / jid
        folder.mkdir(parents=True)
        (folder / "ok.srt").write_text("subtitle")
        (folder / "bad.srt").symlink_to(root / ".env")
        assert len(client.get(f"/api/jobs/{jid}/artifacts").json()) == 1
        assert client.get(f"/api/jobs/{jid}/artifacts/ok.srt").text == "subtitle"
        assert client.get(f"/api/jobs/{jid}/artifacts/bad.srt").status_code == 400
        assert "input_path" not in client.get(f"/api/jobs/{jid}").json()
    finally:
        release.set()
        assert finished.wait(2)


def test_real_job_requires_config_and_demo_explicit(backend, monkeypatch):
    app, client, root = backend
    assert client.post("/api/jobs", headers=HEADERS, json={"upload_id": "fake"}).status_code == 400
    folder = root / "tests/fixtures"
    folder.mkdir(parents=True)
    (folder / "demo.wav").write_bytes(b"wav")
    done = threading.Event()

    def run(job, cfg):
        assert cfg.raw["asr"]["backend"] == "mock" and not cfg.llm.configured
        done.set()
        return job

    monkeypatch.setattr(pipeline, "run", run)
    response = client.post("/api/jobs", headers=HEADERS, json={"demo": True})
    assert response.status_code == 202 and response.json()["mock"] is True
    assert done.wait(2)


def test_probe_redacts_and_throttles(backend, monkeypatch):
    _, client, _ = backend
    configure(client)

    def fake_probe(cfg):
        assert cfg.timeout_sec <= 5
        return {"ok": False, "reason": "secret-test-key"}

    monkeypatch.setattr("cueloom.server.probe", fake_probe)
    result = client.post("/api/llm/probe", headers=HEADERS)
    assert result.status_code == 200 and "secret-test-key" not in result.text
    assert client.post("/api/llm/probe", headers=HEADERS).status_code == 429


def test_model_manager_wiring(backend):
    app, client, _ = backend
    calls, done = [], threading.Event()

    class FakeManager:
        def list_models(self):
            return [{"id": "tiny", "managed": True}]

        def download(self, mid):
            calls.append(("download", mid))
            done.set()
            return {"id": mid}

        def delete(self, mid, confirm):
            calls.append(("delete", mid, confirm))
            return {"deleted": True}

        def use_default(self, mid):
            calls.append(("default", mid))
            return {"id": mid}

    app.state.model_manager = FakeManager()
    assert client.get("/api/models").json()[0]["id"] == "tiny"
    response = client.post("/api/models/tiny/download", headers=HEADERS)
    assert response.status_code == 202 and done.wait(2)
    assert client.get("/api/tasks/" + response.json()["task_id"]).status_code == 200
    assert (
        client.request(
            "DELETE", "/api/models/tiny", headers=HEADERS, json={"confirm": "tiny"}
        ).status_code
        == 200
    )
    assert client.post("/api/models/tiny/default", headers=HEADERS).status_code == 200
    assert ("delete", "tiny", "tiny") in calls


def test_read_only_and_startup_guards(backend, monkeypatch):
    app, client, root = backend
    monkeypatch.setenv("CUELOOM_CONFIG_READ_ONLY", "1")
    assert client.get("/api/config").json()["editable"] is False
    assert configure(client).status_code == 409
    monkeypatch.delenv("CUELOOM_CONFIG_READ_ONLY")
    folder = root / "work/interrupted"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({"job_id": "interrupted", "status": "running"}))
    with TestClient(app):
        pass
    assert json.loads((folder / "job.json").read_text())["status"] == "interrupted"
    monkeypatch.setenv("CUELOOM_HOST", "0.0.0.0")
    remote_app = create_app(root)
    with pytest.raises(RuntimeError, match="32"):
        with TestClient(remote_app):
            pass


def test_download_single_flight(backend):
    app, client, _ = backend
    entered, release, done = threading.Event(), threading.Event(), threading.Event()

    class FakeManager:
        def list_models(self):
            return [{"id": "tiny", "managed": True}]

        def download(self, mid):
            entered.set()
            release.wait(5)
            done.set()
            return {"id": mid}

    app.state.model_manager = FakeManager()
    try:
        response = client.post("/api/models/tiny/download", headers=HEADERS)
        assert response.status_code == 202 and entered.wait(2)
        assert client.post("/api/models/tiny/download", headers=HEADERS).status_code == 409
    finally:
        release.set()
        assert done.wait(2)


def test_pipeline_atomic_and_secret_exception(backend, monkeypatch):
    app, client, root = backend
    configure(client)
    cfg = app.state.provider.snapshot()
    job = pipeline.create_job(root / "fake.wav", "zh-CN", job_id="test")

    def fail(job, cfg):
        raise RuntimeError("Bearer " + cfg.llm.api_key)

    monkeypatch.setitem(pipeline.STAGE_DISPATCH, "asr", fail)
    pipeline.run(job, cfg)
    text = (root / "work/test/job.json").read_text()
    assert "secret-test-key" not in text and json.loads(text)["status"] == "failed"
    assert not list((root / "work/test").glob(".job-*"))


def test_inherited_dotenv_environment_hot_reload(backend, monkeypatch):
    from cueloom.control.config_service import ConfigProvider

    _, _, root = backend
    (root / ".env").write_text('CUELOOM_LLM_MODEL="inherited"\n')
    monkeypatch.setenv("CUELOOM_LLM_MODEL", "inherited")
    provider = ConfigProvider(root)
    assert not provider.overridden("llm.model")
    provider.save({"llm.model": "updated"})
    assert os.environ["CUELOOM_LLM_MODEL"] == "updated"
    assert provider.snapshot().llm.model == "updated"
    (root / ".env").write_text("")
    provider.reload()
    assert "CUELOOM_LLM_MODEL" not in os.environ


@pytest.mark.parametrize(
    "host",
    [
        "localhost.",
        "evil.example",
        "127.0.0.1:bad",
        "localhost:80/path",
        "localhost:80?x",
        "localhost:80#x",
        "user@localhost",
        "localhost:99999",
    ],
)
def test_rebinding_and_malformed_hosts(backend, host):
    _, client, _ = backend
    assert client.get("/api/config", headers={"Host": host}).status_code == 403


def test_ipv6_local_and_remote_forwarding_cannot_authenticate(backend, monkeypatch):
    app, _, _ = backend
    ipv6 = TestClient(app, base_url="http://localhost:8000", client=("::1", 1234))
    assert ipv6.get("/api/config", headers={"Host": "[::1]:8000"}).status_code == 200
    remote = TestClient(app, base_url="https://localhost", client=("192.0.2.2", 1234))
    for headers in ({"X-Real-IP": "127.0.0.1"}, {"Forwarded": "for=127.0.0.1;proto=https"}):
        assert remote.get("/api/jobs", headers=headers).status_code == 401
    monkeypatch.setenv("CUELOOM_WEB_TOKEN", "x" * 40)
    assert (
        remote.get("/api/config", headers={"Authorization": "Bearer " + "x" * 39}).status_code
        == 401
    )


def test_upload_stream_limit_and_disconnect_cleanup(backend, monkeypatch):
    import asyncio

    from starlette.requests import Request

    from cueloom.control.guards import ControlError

    app, _, root = backend
    monkeypatch.setenv("CUELOOM_MAX_UPLOAD_MB", "0")
    messages = iter([{"type": "http.request", "body": b"too large", "more_body": False}])

    async def receive():
        return next(messages)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/uploads",
            "headers": [(b"x-filename", b"x.wav")],
        },
        receive,
    )
    with pytest.raises(ControlError, match="上传超过"):
        asyncio.run(app.state.jobs.upload(request))
    assert not list((root / "inbox").iterdir())
    monkeypatch.setenv("CUELOOM_MAX_UPLOAD_MB", "1")
    messages = iter(
        [
            {"type": "http.request", "body": b"partial", "more_body": True},
            {"type": "http.disconnect"},
        ]
    )
    with pytest.raises(Exception):
        asyncio.run(app.state.jobs.upload(request))
    assert not list((root / "inbox").iterdir())


def test_config_secret_clear_omit_and_literal_interpolation(backend):
    app, client, root = backend
    configure(client)
    literal = "key-${UNKNOWN}-'quoted'-\\value"
    assert (
        client.put("/api/config", headers=HEADERS, json={"llm.api_key": literal}).status_code == 200
    )
    assert app.state.provider.snapshot().llm.api_key == literal
    client.put("/api/config", headers=HEADERS, json={"llm.model": "next"})
    assert app.state.provider.snapshot().llm.api_key == literal
    response = client.put("/api/config", headers=HEADERS, json={"llm.api_key": ""})
    assert not response.json()["config"]["llm"]["api_key_configured"]
    assert app.state.provider.snapshot().llm.api_key == ""


def test_demo_runs_five_stages_offline(backend):
    import shutil
    from pathlib import Path

    app, client, root = backend
    fixture = root / "tests/fixtures"
    fixture.mkdir(parents=True)
    shutil.copyfile(Path(__file__).parents[1] / "fixtures/demo.wav", fixture / "demo.wav")
    response = client.post(
        "/api/jobs", headers=HEADERS, json={"demo": True, "formats": ["srt", "vtt", "ass"]}
    )
    assert response.status_code == 202
    jid = response.json()["job_id"]
    # 用同步事件观察执行结束，不启动监听端口或真实模型。
    original_get = app.state.tasks.get
    thread = next((t for t in threading.enumerate() if t.name == "cueloom-pipeline"), None)
    if thread:
        thread.join(10)
        assert not thread.is_alive()
    task = original_get(jid)
    assert task["state"] == "done"
    detail = client.get(f"/api/jobs/{jid}").json()
    assert detail["status"] == "done" and detail["demo"] and detail["mock"]
    assert len(detail["stage_results"]) == 5
    artifacts = client.get(f"/api/jobs/{jid}/artifacts").json()
    assert {a["format"] for a in artifacts} == {"srt", "vtt", "ass"}
    assert all(client.get(a["url"]).status_code == 200 for a in artifacts)
