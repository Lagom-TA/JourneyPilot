#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
#  Constants
# ─────────────────────────────────────────────────────────────────────────────
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
BACKEND_DIR="$ROOT_DIR/backend"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$ROOT_DIR/.venv}"
FRONTEND_PORT="${FRONTEND_PORT:-8080}"
BACKEND_PORT=""

# Canonical runtime state for run.sh and E2E discovery. Exactly one
# instance may be recorded here at a time; start refuses rather than overwrite it.
PORTS_FILE="$ROOT_DIR/tmp/journeypilot.ports"
LOG_DIR="$ROOT_DIR/tmp/logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

BACKEND_PID=""
FRONTEND_PID=""
SPINNER_PID=""

# 这个脚本不定义任何策略：窗口、预算、端口都来自同一个配置 schema。
#   JOURNEYPILOT_RUN_DEADLINE__DELIVERY_SECONDS=900 ./run.sh start

# ─────────────────────────────────────────────────────────────────────────────
#  Colors & Icons  (disabled when stdout is not a terminal)
# ─────────────────────────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  CYAN=$'\033[0;36m'
  GREEN=$'\033[0;32m'
  YELLOW=$'\033[1;33m'
  RED=$'\033[0;31m'
  MAGENTA=$'\033[0;35m'
  DIM=$'\033[2m'
  BOLD=$'\033[1m'
  RESET=$'\033[0m'
else
  CYAN="" GREEN="" YELLOW="" RED="" MAGENTA="" DIM="" BOLD="" RESET=""
fi

OK="✓"
FAIL="✗"
WARN="⚠"
SPIN=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')

# ─────────────────────────────────────────────────────────────────────────────
#  UI Primitives
# ─────────────────────────────────────────────────────────────────────────────

print_banner() {
  local title="$1"
  local cmd="${2:-}"
  local line
  printf -v line '%0.s─' {1..42}
  echo
  if [[ -n "$cmd" ]]; then
    printf "${MAGENTA}${BOLD}▌ %s${RESET}  ${DIM}%s${RESET}  ${CYAN}%s${RESET}\n" \
      "$title" "$line" "$cmd"
  else
    printf "${MAGENTA}${BOLD}▌ %s${RESET}  ${DIM}%s${RESET}\n" "$title" "$line"
  fi
  echo
}

print_section() {
  printf "\n${CYAN}▸ %s${RESET}\n" "$1"
}

# print_item <label> <status: ok|warn|fail> [message]
print_item() {
  local label="$1"
  local status="$2"
  local msg="${3:-}"
  local icon color
  case "$status" in
    ok)   icon="$OK";   color="$GREEN"  ;;
    warn) icon="$WARN"; color="$YELLOW" ;;
    fail) icon="$FAIL"; color="$RED"    ;;
    *)    icon="·";     color="$DIM"    ;;
  esac
  printf "  ${DIM}│${RESET}  %-14s ${color}%s${RESET}  %s\n" "$label" "$icon" "$msg"
}

# ─────────────────────────────────────────────────────────────────────────────
#  Spinner  (braille dot animation, background subshell + \r redraw)
# ─────────────────────────────────────────────────────────────────────────────

start_spinner() {
  local msg="$1"
  # Capture color vars for use inside subshell
  local _cyan="$CYAN" _dim="$DIM" _reset="$RESET"
  (
    local i=0
    while true; do
      printf "\r  ${_dim}│${_reset}  ${_cyan}%s${_reset}  %s" "${SPIN[$i]}" "$msg"
      i=$(( (i + 1) % 10 ))
      sleep 0.1
    done
  ) &
  SPINNER_PID=$!
}

stop_spinner() {
  if [[ -n "$SPINNER_PID" ]] && kill -0 "$SPINNER_PID" 2>/dev/null; then
    kill "$SPINNER_PID" 2>/dev/null || true
    wait "$SPINNER_PID" 2>/dev/null || true
    SPINNER_PID=""
    printf "\r\033[K"   # clear the spinner line
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
#  Runtime State
# ─────────────────────────────────────────────────────────────────────────────

write_runtime_state() {
  mkdir -p "$(dirname "$PORTS_FILE")"
  # 纯 key=value 数据文件, 不是 shell 脚本: 读取方一律按行解析, 绝不 source。
  {
    printf 'BACKEND_PID=%s\nFRONTEND_PID=%s\nBACKEND_PORT=%s\nFRONTEND_PORT=%s\n' \
      "$BACKEND_PID" "$FRONTEND_PID" "$BACKEND_PORT" "$FRONTEND_PORT"
    printf 'WRITTEN_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date)"
    printf 'API_BASE=http://127.0.0.1:%s/api\n' "$BACKEND_PORT"
    printf 'APP_URL=http://127.0.0.1:%s\n' "$FRONTEND_PORT"
  } > "$PORTS_FILE"
}

read_runtime_state() {
  # Reset before parsing so missing keys don't retain stale values
  BACKEND_PID="" FRONTEND_PID="" BACKEND_PORT="" FRONTEND_PORT="8080"
  [[ -f "$PORTS_FILE" ]] || return 0

  # 按行解析而不是 source: 这个文件由上一次 run.sh 写入, 但它在仓库工作区里、
  # 可被任何进程改写。source 一个可写文件等于把「谁写谁执行」的权限交给它,
  # 而这里只需要四个数字。
  local key value
  while IFS='=' read -r key value; do
    case "$key" in
      BACKEND_PID)   BACKEND_PID="$value"   ;;
      FRONTEND_PID)  FRONTEND_PID="$value"  ;;
      BACKEND_PORT)  BACKEND_PORT="$value"  ;;
      FRONTEND_PORT) FRONTEND_PORT="$value" ;;
    esac
  done < "$PORTS_FILE"
}

# start 前置守卫: canonical state 里记录的实例还活着时, 拒绝再拉起第二套。
# 第二套服务的 write_runtime_state 会覆盖 tmp/journeypilot.ports, 第一套从此永久
# 失去 stop 授权 (stop 只终止 canonical state 记录的进程树) —— 与端口漂移同一类
# 缺陷, 同样 fail-fast。刻意只读到局部变量: 绝不把别人的 PID 灌进全局, 否则 EXIT
# trap 的 cleanup 会把仍在服务的进程当成本次命令的子进程误杀。
refuse_running_instance() {
  [[ -f "$PORTS_FILE" ]] || return 0

  local key value
  local rec_backend_pid="" rec_frontend_pid=""
  local rec_backend_port="" rec_frontend_port=""
  while IFS='=' read -r key value; do
    case "$key" in
      BACKEND_PID)   rec_backend_pid="$value"   ;;
      FRONTEND_PID)  rec_frontend_pid="$value"  ;;
      BACKEND_PORT)  rec_backend_port="$value"  ;;
      FRONTEND_PORT) rec_frontend_port="$value" ;;
    esac
  done < "$PORTS_FILE"

  local live=""
  if managed_pid_owns_port "$rec_backend_pid" "$rec_backend_port"; then
    live="backend pid ${rec_backend_pid} on :${rec_backend_port}"
  elif managed_pid_owns_port "$rec_frontend_pid" "$rec_frontend_port"; then
    live="frontend pid ${rec_frontend_pid} on :${rec_frontend_port}"
  fi
  [[ -n "$live" ]] || return 0

  print_section "Pre-flight"
  print_item "instance" fail "already running — refusing to start a second one"
  printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$live"
  printf "  ${DIM}│${RESET}      ${DIM}Stop it first: ./run.sh stop   (or ./run.sh restart)${RESET}\n"
  printf "  ${DIM}│${RESET}      ${DIM}Recorded in: %s${RESET}\n" "$PORTS_FILE"
  echo
  return 1
}

# ─────────────────────────────────────────────────────────────────────────────
#  Process-tree termination
# ─────────────────────────────────────────────────────────────────────────────
# 服务 PID 指向实际启动的后端或前端进程；退出时连同其子进程一起停止。

# 深度优先展平 pid 及其所有后代 (趁进程树未断时抓全, 避免 kill 父后失去链路)。
_collect_descendants() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    _collect_descendants "$child"
  done
  printf '%s\n' "$pid"
}

# 进程的内核启动时刻 (/proc/<pid>/stat 第 22 字段)。同一个 PID 在不同时刻属于不同
# 进程时这个值必然不同, 所以它是「这还是我当初看到的那个进程吗」的唯一可靠判据。
# comm 字段可能含空格和括号, 所以从最后一个 ") " 之后开始数: 那里是第 3 字段。
_pid_start_time() {
  local pid="$1" rest
  if [[ -r "/proc/$pid/stat" ]]; then
    rest="$(cat "/proc/$pid/stat" 2>/dev/null)" || return 1
    rest="${rest##*) }"
    awk '{print $20}' <<< "$rest"
    return
  fi

  # macOS has no /proc.  lstart is the kernel-reported process birth time and
  # stays stable for the life of the PID, so it provides the same identity check
  # for the local development platform this script explicitly supports.
  rest="$(ps -o lstart= -p "$pid" 2>/dev/null)" || return 1
  rest="$(awk '{$1=$1; print}' <<< "$rest")"
  [[ -n "$rest" ]] || return 1
  printf '%s\n' "$rest"
}

# 这个 PID 是不是当初被登记的那一个 (存活 + 启动时刻一致)。
_pid_is_same_process() {
  local pid="$1" expected="$2" now
  kill -0 "$pid" 2>/dev/null || return 1
  now="$(_pid_start_time "$pid")" || return 1
  [[ "$now" == "$expected" ]]
}

# 级联终止整棵进程树: 每一轮重新采样后代并求并集, 逐个 TERM (每个 PID 只发一次),
# 宽限至多 1.5s, 再对存活者补 KILL。返回 1 表示 root 本就不在运行。
#
# 为什么必须重新采样: 收到 TERM 之前 fork 出来的后代可能不在任何一次快照里,
# 存活复检与补 KILL 必须每一轮重新看一遍当前的后代集合。
#
# 为什么求并集而不是每轮重新取: 父进程一退出, 它的子进程立刻被 reparent 到 init,
# 从 root 再也走不到。并集是唯一能同时覆盖「新出现的」与「已脱链的」两种后代的读法。
#
# 为什么每个 PID 只发一次 TERM: 第二次 TERM 对正在优雅退出的进程是另一条消息。
#
# 为什么记启动时刻: 并集里会留下已经不是后代的 PID, 这是唯一可能误杀的通道 ——
# PID 被回收给别的进程之后再收到我们的信号。发信号前比一次启动时刻, 就把这个风险
# 从「不可见」变成「判得出来」。
stop_tree() {
  local root="$1"
  if ! kill -0 "$root" 2>/dev/null; then
    return 1
  fi

  # macOS still ships Bash 3.2, which has indexed but not associative arrays.
  # Keep PID and start-time arrays aligned and use a tiny linear membership
  # check; these trees contain only a handful of wrapper processes.
  # Index zero is an inert sentinel.  Bash 3.2 with ``set -u`` treats expansion
  # of a declared-but-empty array as an unbound-variable error.
  local -a started_pids=("")
  local -a started_times=("")
  local -a signalled_pids=("")
  local pid start waited alive index known_pid found

  waited=0
  while :; do
    for pid in $(_collect_descendants "$root"); do
      found=0
      for known_pid in "${started_pids[@]}"; do
        if [[ "$known_pid" == "$pid" ]]; then
          found=1
          break
        fi
      done
      if (( found == 0 )); then
        start="$(_pid_start_time "$pid")" || continue
        started_pids+=("$pid")
        started_times+=("$start")
      fi
    done
    for index in "${!started_pids[@]}"; do
      pid="${started_pids[$index]}"
      found=0
      for known_pid in "${signalled_pids[@]}"; do
        if [[ "$known_pid" == "$pid" ]]; then
          found=1
          break
        fi
      done
      if (( found == 0 )) \
        && _pid_is_same_process "$pid" "${started_times[$index]}"; then
        signalled_pids+=("$pid")
        kill -TERM "$pid" 2>/dev/null || true
      fi
    done
    alive=0
    for index in "${!started_pids[@]}"; do
      if _pid_is_same_process \
        "${started_pids[$index]}" "${started_times[$index]}"; then
        alive=1
        break
      fi
    done
    if (( alive == 0 )); then
      break
    fi
    if (( waited >= 15 )); then
      break
    fi
    sleep 0.1
    waited=$(( waited + 1 ))
  done

  for index in "${!started_pids[@]}"; do
    pid="${started_pids[$index]}"
    if _pid_is_same_process "$pid" "${started_times[$index]}"; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done

  # 端口现在是 fail-fast 的: restart 紧接着就要重新绑定同一个端口, 所以 stop_tree
  # 必须等到整棵树真的消失 (fd 随进程回收才释放监听) 再返回, 不能 KILL 完就走。
  # 这一段同样继续采样: 被 KILL 的父进程也可能已经留下了一个后代。
  waited=0
  while (( waited < 20 )); do
    for pid in $(_collect_descendants "$root"); do
      found=0
      for known_pid in "${started_pids[@]}"; do
        if [[ "$known_pid" == "$pid" ]]; then
          found=1
          break
        fi
      done
      if (( found == 0 )); then
        start="$(_pid_start_time "$pid")" || continue
        started_pids+=("$pid")
        started_times+=("$start")
        kill -KILL "$pid" 2>/dev/null || true
      fi
    done
    alive=0
    for index in "${!started_pids[@]}"; do
      if _pid_is_same_process \
        "${started_pids[$index]}" "${started_times[$index]}"; then
        alive=1
        break
      fi
    done
    if (( alive == 0 )); then
      break
    fi
    sleep 0.1
    waited=$(( waited + 1 ))
  done
  return 0
}

# A PID from runtime state grants stop authority only when its live process tree
# owns the recorded listening port. This rejects stale or reused PIDs.
managed_pid_owns_port() {
  local root="$1"
  local port="$2"
  local pid

  [[ "$root" =~ ^[0-9]+$ ]] || return 1
  [[ "$port" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$root" 2>/dev/null || return 1
  # lsof 是 start/stop/status 的显式硬依赖 (见各 cmd_* 的 require_command lsof)。
  # 缺失时必须响亮地失败: 把「无法判定归属」静默降级成「不是我们的进程」, 会让
  # stop 谎报 not running 并删掉 runtime state, 活着的服务从此永远变成孤儿。
  require_command lsof "needed to verify which process owns a recorded port"

  for pid in $(_collect_descendants "$root"); do
    if lsof -nP -a -p "$pid" -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null \
      | grep -q .; then
      return 0
    fi
  done
  return 1
}

# 受管进程的三态判定 (纯只读, 自身从不 kill):
#   dead   —— PID 已不存在, 记录可以安全丢弃
#   owned  —— PID 存活且进程树正在监听记录的端口, 身份已确认, 可以终止
#   unsure —— PID 存活但身份无法确认 (启动中尚未 bind / 监听已崩但树还在 / PID 被
#             复用成别人的进程)。既不能当作已停止, 也不能凭存活就下杀手。
managed_pid_state() {
  local root="$1"
  local port="$2"

  if [[ ! "$root" =~ ^[0-9]+$ ]] || ! kill -0 "$root" 2>/dev/null; then
    printf 'dead'
    return 0
  fi
  if managed_pid_owns_port "$root" "$port"; then
    printf 'owned'
    return 0
  fi
  printf 'unsure'
}

# ─────────────────────────────────────────────────────────────────────────────
#  Cleanup  (trap INT TERM EXIT)
# ─────────────────────────────────────────────────────────────────────────────

cleanup() {
  local exit_code=$?
  trap - INT TERM EXIT
  stop_spinner

  local owned_services=0
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    stop_tree "$FRONTEND_PID" || true
    owned_services=1
  fi
  if [[ -n "${BACKEND_PID:-}" ]]; then
    stop_tree "$BACKEND_PID" || true
    owned_services=1
  fi
  if [[ "$owned_services" -eq 1 ]] && [[ -f "$PORTS_FILE" ]]; then
    rm -f "$PORTS_FILE" 2>/dev/null || true
  fi
  exit "$exit_code"
}
trap cleanup INT TERM EXIT

# ─────────────────────────────────────────────────────────────────────────────
#  Utilities
# ─────────────────────────────────────────────────────────────────────────────

require_command() {
  local cmd="$1"
  local reason="${2:-}"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    printf "${RED}${FAIL}${RESET}  required command not found: ${BOLD}%s${RESET}\n" "$cmd"
    if [[ -n "$reason" ]]; then
      printf "  ${DIM}%s${RESET}\n" "$reason"
    fi
    echo
    exit 1
  fi
}

# --frozen: lockfile 是本仓库与 CI 的共同事实。没有它, `uv run` 在 pyproject 与
# uv.lock 不一致时会重新解析并写回 lockfile, 本地跑一次 run.sh 就能让环境与 CI 漂移。
run_in_env() {
  (cd "$ROOT_DIR" && uv run --frozen --project "$BACKEND_DIR" "$@")
}

check_python_env_exists() {
  run_in_env python --version >/dev/null 2>&1
}

check_backend_runtime_imports() {
  run_in_env python -c "
import sys
sys.path.insert(0, r'$BACKEND_DIR')
import fastapi, openai, uvicorn, yaml, mcp
from main import app
from travel_agent.config.loader import get_settings
" 2>/dev/null
}

# 尽力而为地描述端口占用者, 帮操作者区分「自家上一次实例」和「外部进程」。
# 输出 "vite (pid 12345)"; 判不出来 (无 lsof / 属于其它用户) 就输出空串。
describe_port_holder() {
  local port="$1"
  local pid="" name=""

  command -v lsof >/dev/null 2>&1 || return 0
  pid="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1)" || true
  [[ -n "$pid" ]] || return 0
  name="$(ps -p "$pid" -o comm= 2>/dev/null)" || true
  printf '%s (pid %s)' "${name:-unknown}" "$pid"
}

# 目标端口被占用一律 fail-fast, 绝不 +1 漂移。漂移会在另一个端口拉起第二套服务,
# 而 run.sh 只 kill 自己记录的 PID (从不按端口 kill), canonical state 又被后一次
# start 覆盖 —— 前一套服务就再也停不掉了。宁可拒绝启动, 让操作者显式收拾现场。
refuse_busy_port() {
  local label="$1"
  local port="$2"
  local how_to_change="$3"
  local holder
  holder="$(describe_port_holder "$port")"

  print_item "$label" fail ":${port} is already in use — refusing to start"
  if [[ -n "$holder" ]]; then
    printf "  ${DIM}│${RESET}      ${DIM}holder: %s${RESET}\n" "$holder"
  fi
  printf "  ${DIM}│${RESET}      ${DIM}If it is a previous JourneyPilot instance: ./run.sh stop${RESET}\n"
  printf "  ${DIM}│${RESET}      ${DIM}If it is a foreign process: free :%s, or %s${RESET}\n" \
    "$port" "$how_to_change"
  echo
  return 1
}

resolve_backend_port() {
  local resolved
  resolved="$(run_in_env python -c "
import sys
sys.path.insert(0, r'$BACKEND_DIR')
from travel_agent.config.loader import get_settings
print(get_settings().server.port)
" 2>/dev/null | tail -n 1 || true)"
  BACKEND_PORT="${resolved:-8001}"

  if port_is_busy "$BACKEND_PORT"; then
    refuse_busy_port "backend port" "$BACKEND_PORT" "change server.port in config.yaml"
    return 1
  fi
}

resolve_frontend_port() {
  if port_is_busy "$FRONTEND_PORT"; then
    refuse_busy_port "frontend port" "$FRONTEND_PORT" "run with FRONTEND_PORT=<free port>"
    return 1
  fi
}

port_is_busy() {
  local port="$1"
  run_in_env python - "$port" >/dev/null 2>&1 <<'PY'
import socket
import sys

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.settimeout(0.25)
try:
    busy = sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0
finally:
    sock.close()
raise SystemExit(0 if busy else 1)
PY
}

backend_is_ready() {
  command -v curl >/dev/null 2>&1 || return 1
  local port="${1:-$BACKEND_PORT}"
  local base_url="http://127.0.0.1:${port}"
  curl --silent --fail "${base_url}/api/health/ready" >/dev/null 2>&1 || return 1
  curl --silent --fail "${base_url}/openapi.json" 2>/dev/null \
    | grep -q '"title":"JourneyPilot API"'
}

frontend_is_ready() {
  command -v curl >/dev/null 2>&1 || return 1
  local port="${1:-$FRONTEND_PORT}"
  curl --silent --fail "http://127.0.0.1:${port}/" >/dev/null 2>&1
}

# 端口发现: 只读、无副作用, 供 status 在 runtime state 缺失或过期时使用。
# 刻意内联在 run.sh 里 —— 测试目录不是运行时依赖, 删掉 frontend/e2e/ 不影响 run.sh。
discover_ports() {
  local key value
  if [[ -f "$PORTS_FILE" ]]; then
    while IFS='=' read -r key value; do
      case "$key" in
        BACKEND_PORT)  BACKEND_PORT="$value"  ;;
        FRONTEND_PORT) FRONTEND_PORT="$value" ;;
      esac
    done < "$PORTS_FILE"
  fi

  local port
  if [[ -z "${BACKEND_PORT:-}" ]] || ! backend_is_ready; then
    for port in $(seq 8001 8020); do
      if backend_is_ready "$port"; then
        BACKEND_PORT="$port"
        break
      fi
    done
  fi

  if [[ -z "${FRONTEND_PORT:-}" ]] || ! frontend_is_ready; then
    for port in $(seq 8080 8090); do
      if frontend_is_ready "$port"; then
        FRONTEND_PORT="$port"
        break
      fi
    done
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
#  Step Functions
# ─────────────────────────────────────────────────────────────────────────────

step_config() {
  print_section "Pre-flight"

  if [[ ! -f "$ROOT_DIR/config.yaml" ]]; then
    if [[ -f "$BACKEND_DIR/config.example.yaml" ]]; then
      cp "$BACKEND_DIR/config.example.yaml" "$ROOT_DIR/config.yaml"
      print_item "config" ok "created from backend/config.example.yaml"
      printf "  ${DIM}│${RESET}  ${YELLOW}Edit config.yaml and fill in your API keys before proceeding.${RESET}\n"
    else
      print_item "config" warn "backend/config.example.yaml not found — skipping"
    fi
  else
    print_item "config" ok "config.yaml"
  fi
}

step_infra() {
  print_section "Infrastructure"

  if ! command -v docker >/dev/null 2>&1; then
    print_item "docker" warn "not found — Postgres & Redis must be running manually"
    return 0
  fi

  if ! docker info >/dev/null 2>&1; then
    print_item "docker" warn "daemon not running — attempting to start"
    if [[ "$(uname -s)" == "Darwin" ]]; then
      open -a Docker >/dev/null 2>&1 || true
    else
      (command -v systemctl >/dev/null 2>&1 && systemctl start docker >/dev/null 2>&1) || true
      (command -v service >/dev/null 2>&1 && service docker start >/dev/null 2>&1) || true
    fi

    local waited=0 max_wait=30
    start_spinner "waiting for Docker daemon..."
    while (( waited < max_wait )); do
      docker info >/dev/null 2>&1 && break
      sleep 1
      waited=$(( waited + 1 ))
    done
    stop_spinner

    if ! docker info >/dev/null 2>&1; then
      print_item "docker" warn "daemon still not ready — start Docker Desktop manually"
      return 0
    fi
  fi

  local compose_file="$ROOT_DIR/infra/compose.yml"
  if [[ ! -f "$compose_file" ]]; then
    print_item "docker" warn "infra/compose.yml not found"
    return 0
  fi

  # 输出不能丢：这一步失败时（撞名、端口被占、镜像拉不动）它是唯一说明原因的地方。
  # 没有守卫的话 set -e 会让整个 start 在这里无声退出。
  local compose_out
  if ! compose_out=$(docker compose -f "$compose_file" up -d postgres redis 2>&1); then
    print_item "docker" fail "compose up 失败 — 未启动任何服务"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$line"
    done <<< "$compose_out"
    return 1
  fi

  local waited=0 max_wait=60
  local pg_status="starting" rd_status="starting"
  local pg_time=0 rd_time=0
  local pg_done=0 rd_done=0

  start_spinner "waiting for Postgres & Redis..."
  while (( waited < max_wait )); do
    pg_status=$(docker inspect --format='{{.State.Health.Status}}' journeypilot-postgres 2>/dev/null || echo "missing")
    rd_status=$(docker inspect --format='{{.State.Health.Status}}' journeypilot-redis   2>/dev/null || echo "missing")

    [[ "$pg_status" == "healthy" && "$pg_done" -eq 0 ]] && { pg_time=$waited; pg_done=1; }
    [[ "$rd_status" == "healthy" && "$rd_done" -eq 0 ]] && { rd_time=$waited; rd_done=1; }
    [[ "$pg_done" -eq 1 && "$rd_done" -eq 1 ]] && break

    sleep 2
    waited=$(( waited + 2 ))
  done
  stop_spinner

  if [[ "$pg_status" == "healthy" ]]; then
    print_item "postgres" ok "healthy  ${pg_time}s"
  else
    print_item "postgres" warn "not healthy after ${max_wait}s  (${pg_status})"
  fi

  if [[ "$rd_status" == "healthy" ]]; then
    print_item "redis" ok "healthy  ${rd_time}s"
  else
    print_item "redis" warn "not healthy after ${max_wait}s  (${rd_status})"
  fi
}

# 依赖分组：随 config 的默认值走。默认 `embedding.provider: qwen3` 需要
# local-embedding 组（Dockerfile 的 DEPENDENCY_GROUPS 默认值同此）；只装 core
# 会让启动期能力预检直接拒绝启动。cross-encoder 由用户按提示自己加。
UV_SYNC_ARGS=(--frozen --group local-embedding)

step_python() {
  print_section "Environment"

  start_spinner "uv sync ${UV_SYNC_ARGS[*]}..."
  local sync_ok=0
  (cd "$ROOT_DIR" && uv sync --project "$BACKEND_DIR" "${UV_SYNC_ARGS[@]}" >/dev/null 2>&1) && sync_ok=1 || true
  stop_spinner

  if [[ "$sync_ok" -eq 0 ]]; then
    print_item "python" fail "uv sync failed"
    printf "  ${DIM}│${RESET}  ${DIM}Run manually: cd %s && uv sync --project backend %s${RESET}\n" "$ROOT_DIR" "${UV_SYNC_ARGS[*]}"
    return 1
  fi

  if ! check_python_env_exists; then
    print_item "python" fail ".venv not runnable after sync"
    return 1
  fi

  start_spinner "checking imports..."
  local import_ok=0
  check_backend_runtime_imports && import_ok=1 || true
  stop_spinner

  if [[ "$import_ok" -eq 0 ]]; then
    print_item "imports" fail "missing dependencies — see uv sync output"
    return 1
  fi

  print_item "python" ok ".venv OK"
  print_item "imports" ok "verified"
}

step_mcp() {
  local mcp_out
  mcp_out=$(run_in_env python "$BACKEND_DIR/scripts/check_mcp.py" 2>&1 || true)

  local bad_lines
  bad_lines=$(echo "$mcp_out" | awk '/^[[:alnum:]_.-]+[[:space:]]+status=(error|misconfigured|pending)/ { print }' 2>/dev/null || true)

  if [[ -n "$bad_lines" ]]; then
    local warn_count
    warn_count=$(echo "$bad_lines" | wc -l | tr -d '[:space:]')
    print_item "mcp" warn "${warn_count} server(s) misconfigured — check config.yaml"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$line"
    done <<< "$bad_lines"
  else
    print_item "mcp" ok "all servers configured"
  fi
}

step_frontend_deps() {
  local vite_bin="$FRONTEND_DIR/node_modules/.bin/vite"
  local lock_file="$FRONTEND_DIR/package-lock.json"
  local lock_stamp="$FRONTEND_DIR/node_modules/.package-lock.json"

  # npm ci 而不是 npm install: install 会按当前 npm 版本重写 package-lock.json,
  # 本地跑一次就可能让 lockfile 与 CI 的 `npm ci` 不一致。lockfile 比已安装的树
  # 新时也重装, 否则改了依赖却还在跑旧的 node_modules。
  if [[ ! -x "$vite_bin" ]] || { [[ -f "$lock_file" ]] && [[ "$lock_file" -nt "$lock_stamp" ]]; }; then
    start_spinner "npm ci..."
    local npm_out npm_ok=0
    npm_out=$(npm --prefix "$FRONTEND_DIR" ci 2>&1) && npm_ok=1 || true
    stop_spinner
    if (( npm_ok == 0 )); then
      print_item "frontend" fail "npm ci 失败"
      printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$(echo "$npm_out" | tail -5)"
      return 1
    fi
    print_item "frontend" ok "npm ci done"
  else
    print_item "frontend" ok "node_modules OK"
  fi
}

step_migrate() {
  # 必须在 backend 之前：API 进程不建表。被拒绝时原样打出 CLI 输出，
  # 那里面有「差在哪」和「下一条能敲的命令」。
  print_section "Database"

  local out status
  start_spinner "journeypilot migrate..."
  out=$( (cd "$ROOT_DIR" && uv run --frozen --project "$BACKEND_DIR" python "$BACKEND_DIR/journeypilot.py" migrate 2>&1) ) && status=0 || status=$?
  stop_spinner

  if (( status != 0 )); then
    print_item "database" fail "migration refused — 数据库未被改动"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$line"
    done <<< "$out"
    return 1
  fi

  local revision
  revision=$(echo "$out" | sed -n 's/^迁移完成：revision \([^,]*\).*/\1/p' | tail -1)
  print_item "database" ok "revision ${revision:-head}"
}

step_start_backend() {
  print_section "Services"
  (umask 077 && mkdir -p "$LOG_DIR")
  local python_bin
  python_bin="$(run_in_env python -c 'import sys; print(sys.executable)')" || return 1

  (
    cd "$ROOT_DIR"
    # run.sh 管理服务进程；需要自动重载时直接运行 python backend/main.py。
    export JOURNEYPILOT_SERVER__PORT="$BACKEND_PORT"
    exec "$python_bin" -c "
import sys
sys.path.insert(0, r'$BACKEND_DIR')
import uvicorn
from main import app
from travel_agent.config.loader import get_settings
cfg = get_settings()
uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, reload=False, log_level=cfg.server.log_level)
"
  ) >> "$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!

  local waited=0 max_wait=90
  start_spinner "starting backend..."
  while (( waited < max_wait )); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      stop_spinner
      print_item "backend" fail "exited during startup — see $BACKEND_LOG"
      return 1
    fi
    if backend_is_ready; then
      break
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  stop_spinner

  if (( waited >= max_wait )) && ! backend_is_ready; then
    print_item "backend" fail "not ready after ${max_wait}s — see $BACKEND_LOG"
    return 1
  fi

  print_item "backend" ok ":${BACKEND_PORT}   pid ${BACKEND_PID}"
}

step_start_frontend() {
  (umask 077 && mkdir -p "$LOG_DIR")
  (
    cd "$FRONTEND_DIR"
    export VITE_PROXY_TARGET="http://127.0.0.1:${BACKEND_PORT}"
    exec "$FRONTEND_DIR/node_modules/.bin/vite" --host "${FRONTEND_HOST:-127.0.0.1}" --port "$FRONTEND_PORT" --strictPort
  ) >> "$FRONTEND_LOG" 2>&1 &
  FRONTEND_PID=$!

  # 前端开始监听后再记录运行状态。
  local waited=0 max_wait=60
  start_spinner "starting frontend..."
  while (( waited < max_wait )); do
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      stop_spinner
      print_item "frontend" fail "exited during startup — see $FRONTEND_LOG"
      return 1
    fi
    if frontend_is_ready; then
      break
    fi
    sleep 1
    waited=$(( waited + 1 ))
  done
  stop_spinner

  if (( waited >= max_wait )) && ! frontend_is_ready; then
    print_item "frontend" fail "not ready after ${max_wait}s — see $FRONTEND_LOG"
    return 1
  fi

  print_item "frontend" ok ":${FRONTEND_PORT}   pid ${FRONTEND_PID}   live"
}

# ─────────────────────────────────────────────────────────────────────────────
#  Commands
# ─────────────────────────────────────────────────────────────────────────────

cmd_start() {
  require_command uv
  require_command npm
  require_command lsof "needed to verify no other instance already owns the ports"

  local t0
  t0=$(date +%s)

  print_banner "JOURNEYPILOT" "start"

  refuse_running_instance || exit 1

  step_config
  step_infra || exit 1
  step_python || exit 1
  # 端口先解析再迁移: 端口被占时应该在动数据库之前就被拒绝, 而不是先跑完一次
  # 迁移再失败, 留下一次无意义的副作用。
  resolve_backend_port || exit 1
  resolve_frontend_port || exit 1
  step_migrate || exit 1
  step_mcp
  step_frontend_deps || exit 1
  step_start_backend || exit 1
  step_start_frontend || exit 1

  write_runtime_state

  local elapsed=$(( $(date +%s) - t0 ))

  print_section "Open in browser"
  printf "  ${DIM}│${RESET}  %-14s ${CYAN}${BOLD}http://localhost:%s${RESET}\n" "app" "$FRONTEND_PORT"
  printf "  ${DIM}│${RESET}  %-14s ${CYAN}http://localhost:%s/docs${RESET}\n" "api docs" "$BACKEND_PORT"
  printf "  ${DIM}│${RESET}  %-14s ${DIM}http://localhost:%s${RESET}\n" "backend" "$BACKEND_PORT"
  printf "  ${DIM}│${RESET}  %-14s ${GREEN}live${RESET}  ${DIM}前端直连真实后端${RESET}\n" "mode"
  printf "  ${DIM}│${RESET}  %-14s ${DIM}%s${RESET}\n" "ports file" "$PORTS_FILE"
  if [[ "${BACKEND_PORT}" != "8001" ]] || [[ "${FRONTEND_PORT}" != "8080" ]]; then
    print_item "port note" warn "using non-default ports — read $PORTS_FILE"
  fi

  printf "\n  ${GREEN}ready in %ds${RESET}  ${DIM}·  Ctrl+C to stop  ·  ./run.sh logs${RESET}\n\n" "$elapsed"

  supervise_services
}

supervise_services() {
  local service pid log status=0
  while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
    sleep 1
  done

  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    service="backend" pid="$BACKEND_PID" log="$BACKEND_LOG"
  else
    service="frontend" pid="$FRONTEND_PID" log="$FRONTEND_LOG"
  fi
  wait "$pid" || status=$?
  print_item "$service" fail "exited unexpectedly (status $status) — see $log"
  return 1
}

cmd_stop() {
  require_command lsof "needed to verify process ownership before stopping anything"

  print_banner "JOURNEYPILOT" "stop"
  read_runtime_state

  # 与 status 同一个纪律: 立刻把记录值搬进局部变量并清空全局 PID。否则本函数一旦
  # 提前返回 (或被 Ctrl+C), EXIT trap 的 cleanup 会绕过身份校验直接 kill 这些 PID
  # 并删掉 PORTS_FILE —— 正是下面要拒绝做的事。
  local rec_backend_pid="${BACKEND_PID:-}" rec_frontend_pid="${FRONTEND_PID:-}"
  local rec_backend_port="${BACKEND_PORT:-}" rec_frontend_port="${FRONTEND_PORT:-}"
  BACKEND_PID=""
  FRONTEND_PID=""

  print_section "Services"

  local stopped=0 unsure=0

  case "$(managed_pid_state "$rec_frontend_pid" "$rec_frontend_port")" in
    owned)
      stop_tree "$rec_frontend_pid" || true
      print_item "frontend" ok "stopped  pid ${rec_frontend_pid}"
      stopped=1
      ;;
    unsure)
      print_item "frontend" fail \
        "pid ${rec_frontend_pid} alive but not listening on :${rec_frontend_port:-?}"
      unsure=1
      ;;
    dead)
      print_item "frontend" warn "not running"
      ;;
    *)
      # 三态之外的任何输出都按 unsure 处理。这不是理论洁癖: managed_pid_state 是在
      # $( ) 里调用的, 里面的 require_command 只能 exit 掉子 shell, 输出就变成空串。
      # 「没判出来」若落进 not running 分支, 就会重新变成删记录 + 留孤儿。
      print_item "frontend" fail "pid ${rec_frontend_pid:-?} 状态无法判定"
      unsure=1
      ;;
  esac

  case "$(managed_pid_state "$rec_backend_pid" "$rec_backend_port")" in
    owned)
      stop_tree "$rec_backend_pid" || true
      print_item "backend" ok "stopped  pid ${rec_backend_pid}"
      stopped=1
      ;;
    unsure)
      print_item "backend" fail \
        "pid ${rec_backend_pid} alive but not listening on :${rec_backend_port:-?}"
      unsure=1
      ;;
    dead)
      print_item "backend" warn "not running"
      ;;
    *)
      print_item "backend" fail "pid ${rec_backend_pid:-?} 状态无法判定"
      unsure=1
      ;;
  esac

  echo
  if (( unsure == 1 )); then
    # runtime state 是操作者能再次停掉这些进程的唯一凭据。身份判不出来时宁可留下
    # 一份可能过期的记录: 过期记录还能再 stop 一次, 被删掉的记录会让活着的服务
    # 永远变成孤儿。也绝不凭「PID 还活着」就 kill —— PID 可能已被复用成别人的进程,
    # 端口归属才是身份证明。
    printf "  ${RED}${FAIL}  ownership unconfirmed — refusing to guess${RESET}\n"
    printf "  ${DIM}  runtime state kept: %s${RESET}\n" "$PORTS_FILE"
    printf "  ${DIM}  Still starting up? retry: ./run.sh stop${RESET}\n"
    printf "  ${DIM}  Otherwise inspect it, then stop it yourself:${RESET}\n"
    printf "  ${DIM}    ps -o pid,ppid,args -p <pid>${RESET}\n\n"
    return 1
  fi

  rm -f "$PORTS_FILE" 2>/dev/null || true

  if (( stopped == 1 )); then
    printf "  ${GREEN}${OK}  services stopped${RESET}\n\n"
  else
    printf "  ${DIM}no services were running${RESET}\n\n"
  fi
}

cmd_restart() {
  # 停不掉就不许再起: 否则 start 会在 fail-fast 的端口上被拒 (好), 或者把仍活着的
  # 那套服务的记录覆盖掉 (坏)。stop 的退出码就是 restart 的准入条件。
  cmd_stop || exit 1
  # Restore cleanup trap that cmd_stop may have disrupted via the EXIT path
  trap cleanup INT TERM EXIT
  cmd_start
}

cmd_status() {
  require_command lsof "needed to attribute a listening port to a recorded pid"

  print_banner "JOURNEYPILOT" "status"
  read_runtime_state

  # A stale or missing state file must not force status back to the configured
  # default. Reuse the same health-validated discovery as start; never use
  # discovery to acquire stop authority over a process.
  discover_ports

  # status 是纯只读命令。立即把服务 PID 移入局部变量，避免脚本退出时全局 cleanup
  # 把刚刚检查过的常驻服务当成当前命令的子进程误杀。
  local status_backend_pid="$BACKEND_PID"
  local status_frontend_pid="$FRONTEND_PID"
  if ! managed_pid_owns_port "$status_backend_pid" "${BACKEND_PORT:-}"; then
    status_backend_pid=""
  fi
  if ! managed_pid_owns_port "$status_frontend_pid" "${FRONTEND_PORT:-}"; then
    status_frontend_pid=""
  fi
  BACKEND_PID=""
  FRONTEND_PID=""

  print_section "Services"

  if backend_is_ready; then
    print_item "backend" ok "running   pid ${status_backend_pid:-unknown}   :${BACKEND_PORT:-8001}"
  else
    print_item "backend" fail "API unavailable   :${BACKEND_PORT:-8001}"
  fi

  if frontend_is_ready; then
    print_item "frontend" ok "running   pid ${status_frontend_pid:-unknown}   :${FRONTEND_PORT:-8080}"
  else
    print_item "frontend" fail "page unavailable   :${FRONTEND_PORT:-8080}"
  fi

  # docker 缺失时不要谎报「container not found」—— 那是「没装 docker」, 不是
  # 「容器没起」, 两者的下一步动作完全不同。
  if ! command -v docker >/dev/null 2>&1; then
    print_item "postgres" warn "docker not installed — compose stack not checked"
    print_item "redis" warn "docker not installed — compose stack not checked"
    echo
    return 0
  fi

  local pg_status rd_status pg_port rd_port
  # docker inspect 在容器不存在时退出码非 0, 而且会先往 stdout 吐一个空行;
  # pipefail 下直接赋值会让 set -e 提前退出, 所以统一 || true 再兜底。
  pg_status=$(docker inspect --format='{{.State.Health.Status}}' journeypilot-postgres 2>/dev/null | head -1 || true)
  rd_status=$(docker inspect --format='{{.State.Health.Status}}' journeypilot-redis    2>/dev/null | head -1 || true)
  pg_status="${pg_status:-unknown}"
  rd_status="${rd_status:-unknown}"
  # 实际发布的宿主端口, 而不是写死 compose 默认值: 端口被改过时 status 不该说谎。
  pg_port=$(docker port journeypilot-postgres 5432 2>/dev/null | head -1 | sed 's/.*://' || true)
  rd_port=$(docker port journeypilot-redis    6379 2>/dev/null | head -1 | sed 's/.*://' || true)
  pg_port="${pg_port:-55433}"
  rd_port="${rd_port:-16379}"

  if [[ "$pg_status" == "healthy" ]]; then
    print_item "postgres" ok "healthy   :${pg_port} (compose host)"
  elif [[ "$pg_status" == "unknown" ]]; then
    print_item "postgres" warn "container not found"
  else
    print_item "postgres" fail "${pg_status}   :${pg_port} (compose host)"
  fi

  if [[ "$rd_status" == "healthy" ]]; then
    print_item "redis" ok "healthy   :${rd_port} (compose host)"
  elif [[ "$rd_status" == "unknown" ]]; then
    print_item "redis" warn "container not found"
  else
    print_item "redis" fail "${rd_status}   :${rd_port} (compose host)"
  fi

  echo
}

cmd_logs() {
  local target="${1:-backend}"
  print_banner "JOURNEYPILOT" "logs · ${target}"

  local log_file
  case "$target" in
    backend)  log_file="$BACKEND_LOG"  ;;
    frontend) log_file="$FRONTEND_LOG" ;;
    *)
      printf "  ${RED}${FAIL}${RESET}  unknown target: ${BOLD}%s${RESET}  (use 'backend' or 'frontend')\n\n" "$target"
      exit 1
      ;;
  esac

  if [[ ! -f "$log_file" ]]; then
    printf "  ${WARN}  log file not found: ${DIM}%s${RESET}\n" "$log_file"
    printf "  ${DIM}Start the project first: ./run.sh start${RESET}\n\n"
    exit 1
  fi

  printf "  ${DIM}%s${RESET}\n\n" "$log_file"

  # Ctrl+C should only stop tail, not kill backend/frontend
  trap - INT TERM EXIT
  tail -f "$log_file"
}

cmd_check() {
  require_command uv

  print_banner "JOURNEYPILOT" "check"
  print_section "Environment"
  local status=0

  # Python env
  start_spinner "uv sync ${UV_SYNC_ARGS[*]}..."
  local sync_ok=0
  (cd "$ROOT_DIR" && uv sync --project "$BACKEND_DIR" "${UV_SYNC_ARGS[@]}" >/dev/null 2>&1) && sync_ok=1 || true
  stop_spinner

  if [[ "$sync_ok" -eq 1 ]] && check_python_env_exists; then
    print_item "python" ok ".venv OK"
  else
    print_item "python" fail ".venv not runnable — run: uv sync --project backend ${UV_SYNC_ARGS[*]}"
    status=1
  fi

  # Runtime imports
  start_spinner "checking imports..."
  local import_ok=0
  check_backend_runtime_imports && import_ok=1 || true
  stop_spinner

  if [[ "$import_ok" -eq 1 ]]; then
    print_item "imports" ok "all critical imports OK"
  else
    print_item "imports" fail "some imports failed — run: uv sync --project backend ${UV_SYNC_ARGS[*]}"
    status=1
  fi

  # config validate: 严格解析。未知的 JOURNEYPILOT_* 变量、类型错误、越界值都会
  # 在这里被拒 —— 否则它们要等到 start 的后半段才炸, 报错还指向别处。
  start_spinner "config validate..."
  local cfg_out cfg_status
  cfg_out=$( (cd "$ROOT_DIR" && uv run --frozen --project "$BACKEND_DIR" python "$BACKEND_DIR/journeypilot.py" config validate 2>&1) ) \
    && cfg_status=0 || cfg_status=$?
  stop_spinner

  if (( cfg_status == 0 )); then
    print_item "config" ok "config.yaml valid"
  else
    print_item "config" fail "config.yaml rejected — see below"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$line"
    done <<< "$cfg_out"
    status=1
  fi

  start_spinner "config docs --check..."
  local docs_out docs_status
  docs_out=$( (cd "$ROOT_DIR" && uv run --frozen --project "$BACKEND_DIR" python "$BACKEND_DIR/journeypilot.py" config docs --check 2>&1) ) \
    && docs_status=0 || docs_status=$?
  stop_spinner

  if (( docs_status == 0 )); then
    print_item "config docs" ok "generated files match"
  else
    print_item "config docs" fail "generated files are out of date — see below"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$line"
    done <<< "$docs_out"
    status=1
  fi

  # MCP servers
  start_spinner "checking MCP servers..."
  local mcp_out
  mcp_out=$(run_in_env python "$BACKEND_DIR/scripts/check_mcp.py" 2>&1 || true)
  stop_spinner

  local bad_lines
  bad_lines=$(echo "$mcp_out" | awk '/^[[:alnum:]_.-]+[[:space:]]+status=(error|misconfigured|pending)/ { print }' 2>/dev/null || true)

  if [[ -n "$bad_lines" ]]; then
    local warn_count
    warn_count=$(echo "$bad_lines" | wc -l | tr -d '[:space:]')
    print_item "mcp" warn "${warn_count} server(s) misconfigured"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$line"
    done <<< "$bad_lines"
  else
    print_item "mcp" ok "all servers configured"
  fi

  # doctor 只读、不加锁，所以 check 可以跑它；migrate 不能挪进 check。
  start_spinner "journeypilot doctor..."
  local doctor_out doctor_status
  doctor_out=$( (cd "$ROOT_DIR" && uv run --frozen --project "$BACKEND_DIR" python "$BACKEND_DIR/journeypilot.py" doctor 2>&1) ) \
    && doctor_status=0 || doctor_status=$?
  stop_spinner

  if (( doctor_status == 0 )); then
    print_item "database" ok "$(echo "$doctor_out" | sed -n 's/^判定 *\(.*\)$/\1/p' | tail -1)"
  else
    print_item "database" fail "see below — run: uv run --frozen --project backend python backend/journeypilot.py doctor"
    while IFS= read -r line; do
      [[ -z "$line" ]] && continue
      printf "  ${DIM}│${RESET}      ${DIM}%s${RESET}\n" "$line"
    done <<< "$doctor_out"
    status=1
  fi

  echo
  return "$status"
}

cmd_help() {
  print_banner "JOURNEYPILOT"
  printf "  ${BOLD}Usage:${RESET}  ./run.sh <command>\n\n"
  printf "  ${CYAN}Commands:${RESET}\n"
  printf "    ${BOLD}start${RESET}    Start backend + frontend (live)  ${DIM}(default)${RESET}\n"
  printf "    ${BOLD}stop${RESET}     Stop backend + frontend\n"
  printf "    ${BOLD}restart${RESET}  Stop then start\n"
  printf "    ${BOLD}status${RESET}   Show service status\n"
  printf "    ${BOLD}logs${RESET}     Tail logs  ${DIM}[backend|frontend]${RESET}\n"
  printf "    ${BOLD}check${RESET}    Validate environment without starting\n"
  printf "    ${BOLD}help${RESET}     Show this help\n"
  echo
  printf "  ${CYAN}Environment:${RESET}\n"
  printf "    ${DIM}JOURNEYPILOT_*${RESET}          config overrides, e.g. ${DIM}JOURNEYPILOT_DATABASE__PORT=55433${RESET}\n"
  printf "    ${DIM}FRONTEND_HOST${RESET}           vite dev-server bind address  ${DIM}(default 127.0.0.1)${RESET}\n"
  printf "    ${DIM}JOURNEYPILOT_SERVER__HOST${RESET}  API bind address  ${DIM}(config default 0.0.0.0; prefer 127.0.0.1 when untrusted)${RESET}\n"
  printf "    ${DIM}JOURNEYPILOT_SERVER__RELOAD${RESET}  backend auto-reload  ${DIM}(run.sh forces false)${RESET}\n"
  echo
  printf "  ${DIM}Unknown JOURNEYPILOT_* names are rejected by 'config validate'.${RESET}\n"
  echo
}

# ─────────────────────────────────────────────────────────────────────────────
#  Subcommand Router
# ─────────────────────────────────────────────────────────────────────────────

# Sourced rather than executed: define the functions and run nothing. This is
# what lets infra/scripts/stop_tree_harness.sh drive the real stop_tree instead of a
# copy of it — the function holds every kill this repo issues, and a copy that
# drifted from it would verify the wrong code.
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
  return 0
fi

COMMAND="${1:-start}"
shift 2>/dev/null || true

case "$COMMAND" in
  start)          cmd_start ;;
  stop)           cmd_stop ;;
  restart)        cmd_restart ;;
  status)         cmd_status ;;
  logs)           cmd_logs "${1:-backend}" ;;
  check)          cmd_check ;;
  help|--help|-h) cmd_help ;;
  *)
    print_banner "JOURNEYPILOT"
    printf "  ${RED}${FAIL}${RESET}  unknown command: ${BOLD}%s${RESET}\n\n" "$COMMAND"
    printf "  Run ${BOLD}./run.sh help${RESET} for usage.\n\n"
    exit 1
    ;;
esac
