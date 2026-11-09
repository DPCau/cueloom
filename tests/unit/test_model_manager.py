"""模型资产测试仅使用字节级假模型，不访问网络。"""

import builtins
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cueloom.config import Config
from cueloom.model_manager import ModelManager
from cueloom.models import Job
from cueloom.stages import asr


@pytest.fixture
def manager(tmp_path):
    (tmp_path / "configs").mkdir()
    entries = []
    for model_id, kind, status in [("small", "asr", "supported"),
                                    ("large", "asr", "supported"),
                                    ("aligner", "align", "planned")]:
        entries.append(dict(id=model_id, kind=kind, status=status, repo_id=f"test/{model_id}",
                            revision="a" * 40, license="MIT", runtime="faster-whisper",
                            required_files=["model.bin", "config.json"],
                            min_bytes={"model.bin": 16, "config.json": 2}))
    (tmp_path / "configs/model-catalog.yaml").write_text(yaml.safe_dump({"models": entries}))
    (tmp_path / "configs/default.yaml").write_text("asr:\n  model: large\n")
    return ModelManager(tmp_path)


def install(manager, model_id="small", base=None):
    path = base or manager._target(model_id)
    path.mkdir(parents=True, exist_ok=True)
    (path / "model.bin").write_bytes(b"w" * 32)
    (path / "config.json").write_text("{}")
    return path


def record(manager, model_id="small"):
    return next(r for r in manager.list_models() if r["id"] == model_id)


def test_list_missing_complete_partial_lfs(manager):
    assert record(manager)["state"] == "missing"
    path = install(manager)
    item = record(manager)
    assert item["state"] == "complete"
    assert item["size_bytes"] == 34
    assert item["path"] == str(path)
    assert item["supported"] is True
    (path / "model.bin").write_text("version https://git-lfs.github.com/spec/v1\n")
    assert "LFS pointer" in str(record(manager)["issues"])
    (path / "model.bin").write_bytes(b"w")
    assert record(manager)["state"] == "partial"
    install(manager)
    (path / ".incomplete").touch()
    assert record(manager)["state"] == "partial"
    (path / ".incomplete").unlink()
    (path / "download.incomplete").mkdir()
    assert record(manager)["state"] == "partial"
    (path / "config.json").unlink()
    assert record(manager)["state"] == "partial"


def test_planned_unmanaged_legacy(manager):
    install(manager, "aligner")
    install(manager, base=manager.models / "asr/manual")
    install(manager, base=manager.models / "align/models--legacy/snapshots/hash")
    assert record(manager, "aligner")["supported"] is False
    assert record(manager, "manual")["state"] == "unmanaged"
    assert record(manager, "models--legacy")["state"] == "legacy"
    with pytest.raises(ValueError, match="不支持"):
        manager.use_default("aligner")
    with pytest.raises(ValueError):
        manager.use_default("manual")


@pytest.mark.parametrize("model_id", ["..", "../small", "/tmp/foo", "asr/small", ".", ""])
def test_invalid_ids(manager, model_id):
    for action in [manager.download, manager.use_default, lambda value: manager.delete(value, value)]:
        with pytest.raises(ValueError):
            action(model_id)


@pytest.mark.parametrize("location", ["root", "kind", "model", "file", "nested", "downloads", "partial", "trash"])
def test_symlink_refused(manager, tmp_path, location):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("保留")
    models = manager.models
    if location == "root":
        models.symlink_to(outside, target_is_directory=True)
    elif location == "kind":
        models.mkdir()
        (models / "asr").symlink_to(outside, target_is_directory=True)
    elif location in {"model", "file", "nested"}:
        if location == "model":
            (models / "asr").mkdir(parents=True)
            (models / "asr/small").symlink_to(outside, target_is_directory=True)
        else:
            path = install(manager)
            if location == "file":
                (path / "model.bin").unlink()
                (path / "model.bin").symlink_to(outside / "secret")
            else:
                (path / "nested").symlink_to(outside, target_is_directory=True)
    else:
        install(manager)
        if location == "downloads":
            (models / ".downloads").symlink_to(outside, target_is_directory=True)
        elif location == "partial":
            (models / ".downloads").mkdir()
            (models / ".downloads/small.partial").symlink_to(outside, target_is_directory=True)
        else:
            (models / ".trash").symlink_to(outside, target_is_directory=True)
            with pytest.raises(ValueError):
                manager.delete("small", "small")
            assert (outside / "secret").read_text() == "保留"
            return
    with pytest.raises(ValueError):
        manager.list_models()
    assert (outside / "secret").read_text() == "保留"


def test_download_explicit_local_cache_and_no_activation(manager, monkeypatch):
    calls = []
    def download(**kwargs):
        calls.append(kwargs)
        install(manager, base=Path(kwargs["local_dir"]))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    assert manager.download("small")["state"] == "complete"
    assert manager.download("small")["state"] == "complete"
    assert len(calls) == 1
    assert calls[0]["revision"] == "a" * 40
    for field in ("cache_dir", "local_dir"):
        assert Path(calls[0][field]).is_relative_to(manager.models)
    assert manager._default_id() == "large"
    assert (manager.models / "manifest.json").is_file()


def test_failed_download_keeps_existing_and_partial(manager, monkeypatch):
    path = install(manager)
    (path / "config.json").unlink()
    def download(**kwargs):
        install(manager, base=Path(kwargs["local_dir"]))
        raise RuntimeError("模拟断网")
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    with pytest.raises(RuntimeError, match="模拟断网"):
        manager.download("small")
    assert (path / "model.bin").exists()
    assert (manager.models / ".downloads/small.partial/model.bin").exists()


def test_invalid_download_not_promoted(manager, monkeypatch):
    def download(**kwargs):
        Path(kwargs["local_dir"], "model.bin").write_bytes(b"x")
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    with pytest.raises(ValueError, match="校验失败"):
        manager.download("small")
    assert not manager._target("small").exists()
    assert record(manager)["state"] == "partial"


def test_download_replaces_partial_via_trash_and_planned_allowed(manager, monkeypatch):
    old = install(manager)
    (old / "config.json").unlink()
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        snapshot_download=lambda **kw: install(manager, base=Path(kw["local_dir"]))))
    manager.download("small")
    assert list((manager.models / ".trash").iterdir())
    assert manager.download("aligner")["supported"] is False


def test_default_preserves_config_and_delete_soft_only(manager):
    path = install(manager)
    local = manager.root / "configs/local.yaml"
    local.write_text("llm:\n  model: custom\nasr:\n  device: cpu\n")
    manager.use_default("small")
    data = yaml.safe_load(local.read_text())
    assert data["llm"]["model"] == "custom"
    assert data["asr"] == dict(device="cpu", backend="faster-whisper", model="small")
    with pytest.raises(ValueError):
        manager.delete("small", True)
    result = manager.delete("small", "small")
    assert not path.exists()
    assert Path(result["path"], "model.bin").exists()
    install(manager)
    manager.delete("small", "small")
    assert len(list((manager.models / ".trash").iterdir())) == 2


def test_active_default_refuses_delete(manager):
    install(manager, "large")
    pid = manager.root / "work/ctl/server.pid"
    pid.parent.mkdir(parents=True)
    pid.write_text(str(os.getpid()))
    with pytest.raises(RuntimeError, match="正在被服务使用"):
        manager.delete("large", "large")
    assert manager._target("large").exists()


def test_unmanaged_delete_and_missing_default(manager):
    path = install(manager, base=manager.models / "asr/manual")
    assert Path(manager.delete("manual", "manual")["path"]).exists()
    assert not path.exists()
    with pytest.raises(FileNotFoundError):
        manager.use_default("small")


def test_scanning_does_not_import_hub(manager, monkeypatch):
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name in {"huggingface_hub", "faster_whisper"}:
            raise AssertionError("扫描不允许导入模型库")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    manager.list_models()
    with pytest.raises(FileNotFoundError):
        manager.resolve_model_path("small")


def config(manager, backend="faster-whisper"):
    return Config(root=manager.root, work_dir=manager.root / "work", out_dir=manager.root / "out",
                  raw={"asr": {"backend": backend, "model": "small"}})


def test_asr_missing_dependency_no_mock(manager, monkeypatch):
    original = builtins.__import__
    def missing(name, *args, **kwargs):
        if name == "faster_whisper":
            raise ImportError("未安装")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", missing)
    cfg = config(manager)
    assert isinstance(asr.get_backend(cfg), asr.FasterWhisperBackend)
    with pytest.raises(ImportError, match="faster-whisper"):
        asr.transcribe(Path("fake.wav"), cfg)
    assert isinstance(asr.get_backend(config(manager, "mock")), asr.MockAsrBackend)


def test_explicit_mock_marks_stage_warning(manager):
    audio = manager.root / "fake.wav"
    audio.touch()
    result = asr.run(Job(job_id="mock-test", input_path=str(audio), target_lang="zh-CN"),
                     config(manager, "mock"))
    assert result.ok
    assert any("asr_mock_fallback" in warning for warning in result.warnings)


def test_asr_local_only_and_errors_not_mocked(manager, monkeypatch):
    calls = []
    class Whisper:
        def __init__(self, path, **kwargs):
            calls.append((path, kwargs))
        def transcribe(self, *args, **kwargs):
            return iter([]), SimpleNamespace(language="en")
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=Whisper))
    cfg = config(manager)
    with pytest.raises(FileNotFoundError):
        asr.transcribe(Path("fake.wav"), cfg)
    assert not calls
    local = install(manager)
    assert asr.transcribe(Path("fake.wav"), cfg) == ("en", [])
    assert calls[0][0] == str(local)
    assert calls[0][1]["local_files_only"] is True
    def broken(*args, **kwargs):
        raise RuntimeError("权重损坏")
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=broken))
    with pytest.raises(RuntimeError, match="权重损坏"):
        asr.transcribe(Path("fake.wav"), cfg)
