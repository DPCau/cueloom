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
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
  HOST="${CUELOOM_HOST:-127.0.0.1}"
  PORT="${CUELOOM_PORT:-8000}"
  BASE_URL="http://127.0.0.1:${PORT}"
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
  load_env
  if is_running; then echo "服务已在运行 (PID $(cat "$PID_FILE"))"; return 0; fi
  if [[ ! -x "$VENV_PY" ]]; then echo "缺少 .venv，请先选 6 初始化环境"; return 1; fi
  if port_busy; then echo "端口 $PORT 已被占用，请先停止占用进程"; return 1; fi
  mkdir -p "$WORK_DIR"
  local level
  level="$(printf '%s' "${CUELOOM_LOG_LEVEL:-info}" | tr '[:upper:]' '[:lower:]')"
  nohup "$VENV_PY" -m uvicorn cueloom.server:app --host "$HOST" --port "$PORT" \
    --log-level "$level" >> "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  if wait_health; then
    echo "已启动：$BASE_URL （PID $(cat "$PID_FILE")）"
  else
    echo "启动失败，请用菜单 5 查看日志"
    return 1
  fi
}

stop_service() {
  load_env
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
  load_env
  echo "--- CueLoom 状态 ---"
  if is_running; then echo "进程: 运行中 (PID $(cat "$PID_FILE"))"; else echo "进程: 未运行"; fi
  if curl -fsS "$BASE_URL/api/health" 2>/dev/null; then echo; else echo "健康接口: 不可达"; fi
  echo "监听: ${HOST}:${PORT}"
  echo ".env: $([[ -f "$ENV_FILE" ]] && echo 存在 || echo 不存在)"
  echo "venv: $([[ -x "$VENV_PY" ]] && echo 就绪 || echo 缺失)"
  echo "LLM: base_url=$([[ -n "${CUELOOM_LLM_BASE_URL:-}" ]] && echo 已设置 || echo 未设置) api_key=$([[ -n "${CUELOOM_LLM_API_KEY:-}" ]] && echo 已设置 || echo 未设置) model=$([[ -n "${CUELOOM_LLM_MODEL:-}" ]] && echo 已设置 || echo 未设置)"
}

logs_service() {
  if [[ -f "$LOG_FILE" ]]; then tail -n 80 "$LOG_FILE"; else echo "暂无日志"; fi
}

init_env() {
  if [[ ! -f "$ENV_FILE" ]]; then
    cp "$ROOT/.env.example" "$ENV_FILE"
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
  echo "五阶段流水线将在 M1 实现；当前只有骨架（docs/08-roadmap.md）。"
  echo "本次不会启动任何模型或产生产物。"
}

docker_menu() {
  echo ""
  echo "--- Docker 模式 ---"
  echo "注意：构建会在 Docker 引擎侧产生镜像 / 容器 / named volume，"
  echo "不会把产物写进本项目目录；测试结束请务必选 2 或 5 关闭清理。"
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
    echo " 7) Docker 模式       8) 运行一次流水线 (M1)"
    echo " 9) 测试 LLM 连接     0) 退出"
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
      0) echo "已退出菜单（服务状态保持原样；如需停止请选 2）"; break ;;
      *) echo "无效选择，请输入 0-9" ;;
    esac
  done
}

main
