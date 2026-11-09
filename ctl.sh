#!/usr/bin/env bash
# CueLoom 唯一人工入口：交互式菜单，不需要记忆任何参数。
# 详见 docs/09-console-and-deploy.md
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

WORK_DIR="$ROOT/work/ctl"
PID_FILE="$WORK_DIR/server.pid"
LOG_FILE="$WORK_DIR/server.log"
ENV_FILE="$ROOT/.env"
VENV_PY="$ROOT/.venv/bin/python"

load_env() {
  local python="$VENV_PY" settings
  [[ -x "$python" ]] || python=python3
  settings="$("$python" - "$ENV_FILE" <<'PY'
import os
import re
import sys
from dotenv import dotenv_values

values = dotenv_values(sys.argv[1], interpolate=False)
def setting(key, default):
    return os.environ.get(key, values.get(key) or default)

host = setting("CUELOOM_HOST", "127.0.0.1")
port = setting("CUELOOM_PORT", "8000")
level = setting("CUELOOM_LOG_LEVEL", "info").lower()
if not re.fullmatch(r"[A-Za-z0-9._:-]+", host):
    sys.exit("CUELOOM_HOST 无效")
if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
    sys.exit("CUELOOM_PORT 必须在 1-65535 之间")
if level not in {"critical", "error", "warning", "info", "debug", "trace"}:
    sys.exit("CUELOOM_LOG_LEVEL 无效")
print(host)
print(int(port))
print(level)
PY
)" || return 1
  { read -r HOST; read -r PORT; read -r LOG_LEVEL; } <<< "$settings"
  BASE_URL="http://127.0.0.1:${PORT}"
  [[ "$HOST" != "::1" ]] || BASE_URL="http://[::1]:${PORT}"
}

is_running() {
  [[ -f "$PID_FILE" ]] || return 1
  kill -0 "$(cat "$PID_FILE")" 2>/dev/null
}

port_busy() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1
}

wait_health() {
  local i
  for i in {1..20}; do
    if curl -fsS "$BASE_URL/api/health" >/dev/null 2>&1; then return 0; fi
    sleep 0.5
  done
  return 1
}

start_service() {
  load_env || return 1
  if is_running; then echo "服务已在运行 (PID $(cat "$PID_FILE"))"; return 0; fi
  if [[ ! -x "$VENV_PY" ]]; then echo "缺少 .venv，请先选 6 初始化环境"; return 1; fi
  if port_busy; then echo "端口 $PORT 已被占用，请先停止占用进程"; return 1; fi
  mkdir -p "$WORK_DIR"
  nohup "$VENV_PY" -m uvicorn cueloom.server:app --host "$HOST" --port "$PORT" \
    --log-level "$LOG_LEVEL" --no-proxy-headers >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  if wait_health; then
    echo "已启动：$BASE_URL （PID $(cat "$PID_FILE")）"
  else
    echo "启动失败，请用菜单 5 查看日志"
    return 1
  fi
}

stop_service() {
  load_env || return 1
  if [[ ! -f "$PID_FILE" ]]; then echo "没有 PID 记录，服务可能未运行"; return 0; fi
  local pid i
  pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
    for i in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.3
    done
    if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || true; fi
  fi
  rm -f "$PID_FILE"
  echo "已停止服务（并清理 PID 文件）"
}

status_service() {
  load_env || return 1
  echo "--- CueLoom 状态 ---"
  if is_running; then echo "进程: 运行中 (PID $(cat "$PID_FILE"))"; else echo "进程: 未运行"; fi
  if curl -fsS "$BASE_URL/api/health" 2>/dev/null; then echo; else echo "健康接口: 不可达"; fi
  echo "监听: ${HOST}:${PORT}"
  echo ".env: $([[ -f "$ENV_FILE" ]] && echo 存在 || echo 不存在)"
  echo "venv: $([[ -x "$VENV_PY" ]] && echo 就绪 || echo 缺失)"
  echo "LLM 配置状态请在浏览器工作台查看（ctl 不读取密钥）"
  local job_cnt=0
  if [[ -d "$ROOT/work" ]]; then
    job_cnt="$(find "$ROOT/work" -maxdepth 2 -name "job.json" 2>/dev/null | wc -l | tr -d ' ')"
  fi
  echo "Job 记录数: $job_cnt"
}

logs_service() {
  if [[ -f "$LOG_FILE" ]]; then tail -n 80 "$LOG_FILE"; else echo "暂无日志"; fi
}

init_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    (umask 077; cp "$ROOT/.env.example" "$ENV_FILE")
    chmod 600 "$ENV_FILE"
    echo "已生成 .env，请填写 LLM 配置（该文件不会入库）"
  else
    echo ".env 已存在，保持不变"
  fi
  uv sync --frozen --extra dev
}

probe_llm() {
  if [[ ! -x "$VENV_PY" ]]; then echo "缺少 .venv，请先选 6 初始化环境"; return 1; fi
  "$VENV_PY" -c "from cueloom.config import load_config; from cueloom.llm.client import probe; print('LLM 探活:', probe(load_config().llm))"
}

run_pipeline() {
  if [[ ! -x "$VENV_PY" ]]; then echo "缺少 .venv，请先选 6 初始化环境"; return 1; fi
  echo ""
  echo "--- 运行字幕流水线 ---"
  echo " 1) 显式 Mock 演示 (tests/fixtures/demo.wav；不调用真实 ASR / LLM)"
  echo " 2) 输入自定义本地音视频文件路径"
  echo " 0) 返回"
  read -r -p "请输入数字 [1]: " sub_c || return 0
  sub_c="${sub_c:-1}"
  local media_file=""
  local target_lang="zh-CN"
  case "$sub_c" in
    1)
      media_file="$ROOT/tests/fixtures/demo.wav"
      if [[ ! -f "$media_file" ]]; then echo "演示素材不存在: $media_file"; return 1; fi
      echo "显式演示：使用 Mock ASR 与 Mock LLM，不联网、不下载权重"
      "$VENV_PY" - "$ROOT" <<'PY'
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from cueloom.control.config_service import ConfigProvider
from cueloom.control.job_service import JobService, TaskRegistry

provider = ConfigProvider(Path(sys.argv[1]))
tasks = TaskRegistry()
service = JobService(provider, tasks)
result = service.submit(SimpleNamespace(
    demo=True, upload_id=None, target_lang="zh-CN", bilingual=True, formats=["srt"],
))
print(json.dumps(result, ensure_ascii=False))
while True:
    task = tasks.get(result["task_id"])
    if task["state"] != "running":
        print(json.dumps(task, ensure_ascii=False))
        sys.exit(0 if task["state"] == "done" else 1)
    time.sleep(0.1)
PY
      return $?
      ;;
    2)
      read -r -p "请输入本地文件路径: " media_file || return 0
      if [[ ! -f "$media_file" ]]; then echo "文件不存在: $media_file"; return 1; fi
      read -r -p "目标语言 [zh-CN]: " input_lang || true
      target_lang="${input_lang:-zh-CN}"
      ;;
    0) return 0 ;;
    *) echo "无效选择"; return 0 ;;
  esac
  echo "开始执行流水线: $media_file -> $target_lang ..."
  "$VENV_PY" - "$media_file" "$target_lang" <<'PY'
import sys
from cueloom.config import load_config
from cueloom.cli import app

cfg = load_config()
if cfg.raw.get("asr", {}).get("backend", "faster-whisper").lower() != "faster-whisper":
    sys.exit("真实素材禁止使用 Mock ASR；请先配置 faster-whisper 和本地模型")
if not cfg.llm.configured:
    sys.exit("真实素材需要完整 LLM 配置，禁止静默退回 Mock LLM")
app(["run", sys.argv[1], "--to", sys.argv[2], "--bilingual"])
PY
}

open_browser() {
  load_env || return 1
  if command -v open >/dev/null 2>&1; then
    open "$BASE_URL/"
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$BASE_URL/"
  else
    echo "请在浏览器打开 $BASE_URL/"
  fi
}

models_menu() {
  if [[ ! -x "$VENV_PY" ]]; then echo "缺少 .venv，请先选 6 初始化环境"; return 1; fi
  local action model_id confirm
  echo "--- 模型管理（复用 ModelManager）---"
  echo " 1) 列表 / 扫描    2) 显式下载模型"
  echo " 3) 切换默认模型   4) 删除模型（移入 .trash）"
  echo " 5) 安装可选下载依赖（不安装 ASR、不下载权重）   0) 返回"
  read -r -p "请输入数字: " action || return 0
  case "$action" in
    0) return 0 ;;
    1) model_id=""; confirm="" ;;
    2|3|4)
      read -r -p "请输入完整模型 id: " model_id || return 0
      confirm=""
      if [[ "$action" == "2" ]]; then
        read -r -p "确认联网下载此模型权重? [y/N] " confirm || return 0
        [[ "$confirm" == "y" || "$confirm" == "Y" ]] || return 0
      elif [[ "$action" == "4" ]]; then
        read -r -p "再次输入完整模型 id 确认删除: " confirm || return 0
      fi
      ;;
    5)
      read -r -p "确认安装 models 可选依赖? [y/N] " confirm || return 0
      [[ "$confirm" == "y" || "$confirm" == "Y" ]] || return 0
      uv sync --frozen --extra dev --extra models
      return $?
      ;;
    *) echo "无效选择"; return 0 ;;
  esac
  "$VENV_PY" - "$ROOT" "$action" "$model_id" "$confirm" <<'PY'
import json
import sys
from cueloom.model_manager import ModelManager

manager = ModelManager(sys.argv[1])
action, model_id, confirm = sys.argv[2:]
try:
    if action == "1":
        result = manager.list_models()
    elif action == "2":
        result = manager.download(model_id)
    elif action == "3":
        result = manager.use_default(model_id)
    else:
        result = manager.delete(model_id, confirm)
    print(json.dumps(result, ensure_ascii=False, indent=2))
except ImportError:
    sys.exit("缺少模型下载依赖，请先在模型菜单选 5 安装 models extra")
except (ValueError, OSError, RuntimeError) as exc:
    sys.exit(str(exc))
PY
}

docker_menu() {
  echo ""
  echo "--- Docker 模式 ---"
  echo "注意：构建会在 Docker 引擎侧产生镜像 / 容器 / named volume，"
  echo "模型与下载缓存写入宿主 ./models；任务、产物与上传素材使用 named volume。"
  echo "容器配置只读；必须设置强 CUELOOM_WEB_TOKEN，转发访问不视为本机免登录。"
  echo "仅发布到宿主回环；非本机访问仍须 HTTPS 或受信安全隧道。"
  echo " 1) 启动 (up -d --build)   2) 停止 (down)"
  echo " 3) 查看容器状态           4) 查看日志"
  echo " 5) 彻底清理 (down -v + 删镜像)   0) 返回"
  read -r -p "请输入数字: " d || return 0
  case "$d" in
    1)
      read -r -p "确认构建并启动? [y/N] " ok || return 0
      [[ "$ok" == "y" || "$ok" == "Y" ]] || return 0
      [[ -f "$ENV_FILE" ]] || { echo "请先选 6 生成 .env"; return 1; }
      docker compose up -d --build
      ;;
    2) docker compose down ;;
    3) docker compose ps ;;
    4) docker compose logs --tail=80 ;;
    5)
      read -r -p "确认删除卷与本地镜像 cueloom:local? [y/N] " ok || return 0
      [[ "$ok" == "y" || "$ok" == "Y" ]] || return 0
      docker compose down -v
      docker rmi cueloom:local 2>/dev/null || true
      echo "已清理"
      ;;
    0) return 0 ;;
    *) echo "无效选择" ;;
  esac
}

main() {
  while true; do
    echo ""
    echo "========== CueLoom =========="
    echo " 1) 启动服务          2) 停止服务"
    echo " 3) 查看状态          4) 重启服务"
    echo " 5) 查看日志          6) 初始化环境"
    echo " 7) Docker 模式       8) 流水线（显式 Mock 演示 / 真实素材）"
    echo " 9) 测试 LLM 连接    10) 打开浏览器"
    echo "11) 模型管理          0) 退出"
    read -r -p "请输入数字: " choice || break
    case "$choice" in
      1) start_service || true ;;
      2) stop_service || true ;;
      3) status_service || true ;;
      4) stop_service || true; start_service || true ;;
      5) logs_service || true ;;
      6) init_env || true ;;
      7) docker_menu || true ;;
      8) run_pipeline || true ;;
      9) probe_llm || true ;;
      10) open_browser || true ;;
      11) models_menu || true ;;
      0) echo "已退出菜单（服务状态保持原样；如需停止请选 2）"; break ;;
      *) echo "无效选择，请输入 0-11" ;;
    esac
  done
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main
fi
