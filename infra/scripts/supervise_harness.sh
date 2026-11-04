#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

check_exit() (
  local failing="$1" output
  # shellcheck source=../../run.sh
  source "$ROOT/run.sh"
  trap - INT TERM EXIT
  output="$(mktemp)"

  if [[ "$failing" == "backend" ]]; then
    (sleep 0.1; exit 7) & BACKEND_PID=$!
    sleep 10 & FRONTEND_PID=$!
  else
    sleep 10 & BACKEND_PID=$!
    (sleep 0.1; exit 7) & FRONTEND_PID=$!
  fi
  trap 'kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true; wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true; rm -f "$output"' EXIT

  if supervise_services >"$output" 2>&1; then
    printf '%s\n' "$failing 退出后监督进程未报告失败" >&2
    return 1
  fi
  if ! grep -F "$failing" "$output" >/dev/null || ! grep -F 'status 7' "$output" >/dev/null; then
    printf '%s\n' "$failing 退出状态未正确报告" >&2
    return 1
  fi
)

check_direct_service() (
  local service="$1" temp_dir pid recorded
  # shellcheck source=../../run.sh
  source "$ROOT/run.sh"
  trap - INT TERM EXIT
  temp_dir="$(mktemp -d)"
  mkdir -p "$temp_dir/node_modules/.bin"
  printf '%s\n' '#!/usr/bin/env bash' 'printf "%s" "$$" > "$JP_TEST_PID_FILE"' 'exec sleep 10' > "$temp_dir/service"
  chmod +x "$temp_dir/service"
  ln -s "$temp_dir/service" "$temp_dir/node_modules/.bin/vite"
  export JP_TEST_PID_FILE="$temp_dir/pid"
  LOG_DIR="$temp_dir"
  BACKEND_LOG="$temp_dir/backend.log"
  FRONTEND_LOG="$temp_dir/frontend.log"
  BACKEND_PORT=8001
  FRONTEND_PORT=8080
  FRONTEND_DIR="$temp_dir"
  export LOG_DIR BACKEND_LOG FRONTEND_LOG BACKEND_PORT FRONTEND_PORT FRONTEND_DIR
  run_in_env() { printf '%s\n' "$temp_dir/service"; }
  backend_is_ready() { [[ -s "$JP_TEST_PID_FILE" ]]; }
  frontend_is_ready() { [[ -s "$JP_TEST_PID_FILE" ]]; }
  trap 'kill "${pid:-}" 2>/dev/null || true; wait "${pid:-}" 2>/dev/null || true; rm -rf "$temp_dir"' EXIT

  if [[ "$service" == backend ]]; then
    step_start_backend >/dev/null
    pid="$BACKEND_PID"
  else
    step_start_frontend >/dev/null
    pid="$FRONTEND_PID"
  fi
  recorded="$(< "$JP_TEST_PID_FILE")"
  if [[ "$recorded" != "$pid" ]]; then
    printf '%s\n' "$service PID 不是实际服务进程" >&2
    return 1
  fi
)

check_stop_race() (
  local temp_dir output
  # shellcheck source=../../run.sh
  source "$ROOT/run.sh"
  trap - INT TERM EXIT
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' EXIT
  PORTS_FILE="$temp_dir/ports"
  : > "$PORTS_FILE"
  read_runtime_state() {
    FRONTEND_PID=101 FRONTEND_PORT=8080 BACKEND_PID=102 BACKEND_PORT=8001
  }
  _pid_start_time() { printf 'start-%s\n' "$1"; }
  _pid_is_same_process() { [[ "$2" == "start-$1" ]]; }
  managed_pid_state() {
    if [[ "$1" == 102 && -e "$temp_dir/closing" ]]; then
      printf 'unsure'
    else
      printf 'owned'
    fi
  }
  stop_tree() {
    printf '%s\n' "$1" >> "$temp_dir/stopped"
    [[ "$1" != 101 ]] || : > "$temp_dir/closing"
  }

  output="$(cmd_stop)" || { printf '%s\n' "$output" >&2; return 1; }
  [[ "$(cat "$temp_dir/stopped")" == $'101\n102' ]] || {
    printf '%s\n' '停止前端后未继续安全停止已确认的后端' >&2
    return 1
  }
  [[ ! -e "$PORTS_FILE" ]] || {
    printf '%s\n' '停止服务后未清除运行状态' >&2
    return 1
  }
)

check_changed_identity() (
  local temp_dir stopped=0 unsure=0 pid
  # shellcheck source=../../run.sh
  source "$ROOT/run.sh"
  trap - INT TERM EXIT
  temp_dir="$(mktemp -d)"
  sleep 10 & pid=$!
  trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; rm -rf "$temp_dir"' EXIT
  _pid_is_same_process() { return 1; }
  stop_tree() { : > "$temp_dir/signalled"; }
  stop_recorded_service backend "$pid" 8001 owned previous-start >/dev/null
  [[ "$unsure" == 1 && ! -e "$temp_dir/signalled" ]] || {
    printf '%s\n' '进程身份改变时未拒绝停止' >&2
    return 1
  }
)

check_infra_reuse() (
  local temp_dir
  # shellcheck source=../../run.sh
  source "$ROOT/run.sh"
  trap - INT TERM EXIT
  temp_dir="$(mktemp -d)"
  trap 'rm -rf "$temp_dir"' EXIT
  docker() {
    case "$1" in
      info) return 0 ;;
      compose) printf '%s\n' "$@" > "$temp_dir/compose-args" ;;
      inspect) printf 'healthy\n' ;;
    esac
  }
  step_infra >/dev/null
  grep -Fx -- '--no-recreate' "$temp_dir/compose-args" >/dev/null || {
    printf '%s\n' '启动基础服务时未保留已有容器' >&2
    return 1
  }
)

check_exit backend
check_exit frontend
check_direct_service backend
check_direct_service frontend
check_stop_race
check_changed_identity
check_infra_reuse
printf '%s\n' '服务退出监督检查通过'
