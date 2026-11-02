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

check_exit backend
check_exit frontend
check_direct_service backend
check_direct_service frontend
printf '%s\n' '服务退出监督检查通过'
