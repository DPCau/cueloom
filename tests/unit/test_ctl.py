"""ctl 入口回归；不启动服务、Docker 或模型下载。"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(ROOT / "ctl.sh", tmp_path / "ctl.sh")
    shutil.copy(ROOT / ".env.example", tmp_path / ".env.example")
    return tmp_path


def shell(root, command, stdin="", extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("CUELOOM_")}
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", "-c", 'source "$1/ctl.sh"; VENV_PY="$2"; ' + command,
         "ctl-test", str(root), sys.executable],
        input=stdin, text=True, capture_output=True, env=env, timeout=15,
    )


def test_dotenv_is_data_only_and_does_not_export_secrets(sandbox):
    marker = sandbox / "executed"
    (sandbox / ".env").write_text(
        f'touch "{marker}"\n'
        f'CUELOOM_LLM_API_KEY="$(touch {marker})"\n'
        'export CUELOOM_HOST="127.0.0.1"\n'
        'CUELOOM_PORT="8123" # 注释\n'
        "CUELOOM_LOG_LEVEL='DEBUG'\n"
        "UNRELATED=should-not-export\n"
    )
    result = shell(sandbox, 'load_env; printf "%s|%s|%s|%s|%s|%s" '
                   '"$HOST" "$PORT" "$LOG_LEVEL" "$BASE_URL" '
                   '"${CUELOOM_LLM_API_KEY-unset}" "${UNRELATED-unset}"')
    assert result.returncode == 0, result.stderr
    assert result.stdout == "127.0.0.1|8123|debug|http://127.0.0.1:8123|unset|unset"
    assert not marker.exists()


def test_environment_precedence_and_ipv6(sandbox):
    (sandbox / ".env").write_text("CUELOOM_PORT=8123\n")
    result = shell(sandbox, 'load_env; printf "%s|%s" "$BASE_URL" "$LOG_LEVEL"',
                   extra_env={"CUELOOM_HOST": "::1", "CUELOOM_PORT": "9123",
                              "CUELOOM_LOG_LEVEL": "WARNING"})
    assert result.returncode == 0
    assert result.stdout == "http://[::1]:9123|warning"


@pytest.mark.parametrize("value", [
    "CUELOOM_PORT=0", "CUELOOM_PORT=65536", "CUELOOM_PORT=abc",
    "CUELOOM_PORT=${PORT}", "CUELOOM_HOST=$(touch injected)",
    "CUELOOM_LOG_LEVEL=info;touch injected",
])
def test_invalid_settings_fail_closed(sandbox, value):
    (sandbox / ".env").write_text(value + "\n")
    result = shell(sandbox, "load_env")
    assert result.returncode != 0
    assert not (sandbox / "injected").exists()


def test_init_creates_private_env_and_preserves_existing(sandbox):
    command = 'uv() { printf "%s\\n" "$*"; }; umask 022; init_env'
    result = shell(sandbox, command)
    assert result.returncode == 0
    assert (sandbox / ".env").stat().st_mode & 0o777 == 0o600
    assert "sync --frozen --extra dev" in result.stdout
    (sandbox / ".env").write_text("KEEP=original\n")
    assert shell(sandbox, command).returncode == 0
    assert (sandbox / ".env").read_text() == "KEEP=original\n"


def test_browser_menu_uses_local_url_without_starting_service(sandbox):
    result = shell(sandbox, 'open() { printf "browser=%s" "$1"; }; open_browser')
    assert result.returncode == 0
    assert result.stdout == "browser=http://127.0.0.1:8000/"
    assert not (sandbox / "work").exists()


def test_menu_dispatch(sandbox):
    result = shell(sandbox, 'open_browser() { echo browser; }; '
                   'models_menu() { echo models; }; main', "10\n11\n0\n")
    assert result.returncode == 0
    assert "\nbrowser\n" in result.stdout
    assert "\nmodels\n" in result.stdout


def fake_package(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return {"PYTHONPATH": str(root)}


@pytest.mark.parametrize("action,inputs,expected", [
    ("1", "", ["list"]),
    ("2", "test-model\ny\n", ["download", "test-model"]),
    ("3", "test-model\n", ["default", "test-model"]),
    ("4", "test-model\ntest-model\n", ["delete", "test-model", "test-model"]),
])
def test_model_menu_delegates_to_manager(sandbox, action, inputs, expected):
    env = fake_package(sandbox, {
        "cueloom/__init__.py": "",
        "cueloom/model_manager.py": '''
class ModelManager:
    def __init__(self, root): pass
    def list_models(self): return ["list"]
    def download(self, model_id): return ["download", model_id]
    def use_default(self, model_id): return ["default", model_id]
    def delete(self, model_id, confirm): return ["delete", model_id, confirm]
''',
    })
    result = shell(sandbox, "models_menu", action + "\n" + inputs, env)
    assert result.returncode == 0, result.stderr
    import json

    assert json.loads(result.stdout[result.stdout.index("[\n"):]) == expected


def test_model_download_requires_confirmation(sandbox):
    result = shell(sandbox, "models_menu", "2\ntest-model\nn\n")
    assert result.returncode == 0
    assert not (sandbox / "models").exists()


def test_models_extra_install_is_explicit(sandbox):
    result = shell(sandbox, 'uv() { printf "%s\\n" "$*"; }; models_menu', "5\ny\n")
    assert result.returncode == 0
    assert "sync --frozen --extra dev --extra models" in result.stdout
    assert "--extra asr" not in result.stdout


@pytest.mark.parametrize("backend,configured,message", [
    ("mock", True, "真实素材禁止使用 Mock ASR"),
    ("faster-whisper", False, "真实素材需要完整 LLM 配置"),
])
def test_real_media_never_silently_uses_mock(sandbox, backend, configured, message):
    media = sandbox / "real.wav"
    media.touch()
    env = fake_package(sandbox, {
        "cueloom/__init__.py": "",
        "cueloom/config.py": f'''from types import SimpleNamespace
def load_config():
    return SimpleNamespace(raw={{"asr": {{"backend": "{backend}"}}}},
                           llm=SimpleNamespace(configured={configured}))
''',
        "cueloom/cli.py": 'def app(args):\n    raise AssertionError("禁止执行流水线")\n',
    })
    result = shell(sandbox, "run_pipeline", f"2\n{media}\nzh-CN\n", env)
    assert result.returncode != 0
    assert message in result.stderr


def test_demo_explicitly_submits_to_job_service(sandbox):
    fixtures = sandbox / "tests/fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "demo.wav").touch()
    env = fake_package(sandbox, {
        "cueloom/__init__.py": "",
        "cueloom/control/__init__.py": "",
        "cueloom/control/config_service.py": '''class ConfigProvider:
    def __init__(self, root): pass
''',
        "cueloom/control/job_service.py": '''class TaskRegistry:
    def get(self, tid): return {"state": "done"}
class JobService:
    def __init__(self, provider, tasks): pass
    def submit(self, payload):
        assert payload.demo is True and payload.upload_id is None
        assert payload.formats == ["srt"] and payload.bilingual
        return {"task_id": "demo-test", "mock": True}
''',
    })
    result = shell(sandbox, "run_pipeline", "1\n", env)
    assert result.returncode == 0, result.stderr
    assert '"mock": true' in result.stdout
    assert "Mock ASR 与 Mock LLM" in result.stdout


def test_startup_and_compose_security_contract():
    script = (ROOT / "ctl.sh").read_text()
    assert '--log-level "$LOG_LEVEL" --no-proxy-headers' in script
    assert 'source "$ENV_FILE"' not in script
    assert "eval " not in script
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    service = compose["services"]["cueloom"]
    assert service["environment"]["CUELOOM_CONFIG_READ_ONLY"] == "1"
    assert service["environment"]["CUELOOM_HOST"] == "0.0.0.0"
    assert "--no-proxy-headers" in service["command"]
    assert service["ports"] == ["127.0.0.1:${CUELOOM_PORT:-8000}:8000"]
    assert "./models:/app/models" in service["volumes"]
    assert "cueloom-inbox:/app/inbox" in service["volumes"]
    assert "cueloom-models" not in compose["volumes"]
