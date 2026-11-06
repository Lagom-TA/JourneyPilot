#!/usr/bin/env bash
#
# run.sh::stop_tree 的验证 harness。
#
# stop_tree 承担本仓库发出的全部 kill，分布在四个调用点，其中两个在恢复路径上。
# 这个 harness 就是对它的验证。
#
# 它 source run.sh（被 source 时 run.sh 会提前返回），驱动的是真实函数而不是
# 副本 —— 副本会漂移，验证的就是错误的代码。
#
# 运行：./infra/scripts/stop_tree_harness.sh
# 零成本：不调用任何 provider，不碰数据库，不启动任何服务。
# 它创建的每个进程都是它自己派生的 `sleep`。
#
# 场景 1 模拟什么、不模拟什么：父进程在退出过程中又派生了子进程 —— 本仓库里的
# 典型形态是 npm 把工作交给清理子进程。父进程在同一瞬间 fork 并退出的情形，无论
# 重新采样多少次都无法恢复：子进程在任何人能从 root 下观察到它之前就被 reparent
# 到 init，从 root 出发的遍历永远走不到它。这类残留真实存在，这里如实保留而不
# 掩盖；处理它仍然靠手工执行 `lsof -ti:PORT | xargs kill -9`。

set -uo pipefail
# 关闭作业控制：否则 shell 会为 harness 自己的 fixture 打印 "Killed  sleep 25"，
# 输出里就会混入 PASS/FAIL 以外的行。
set +m

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# shellcheck source=../../run.sh
source "$ROOT_DIR/run.sh"
set +e

PASSED=0
FAILED=0
SPAWNED=()

# 按 PID 登记 fixture 并把它移出作业表：cleanup 按 PID 终止，而被跟踪的作业会让
# shell 在 PASS 行之间打印 "Killed  sleep 25"。
spawn_note() {
  SPAWNED+=("$1")
  disown "$1" 2>/dev/null
}

pass() {
  printf '  PASS  %s\n' "$1"
  PASSED=$(( PASSED + 1 ))
}

fail() {
  printf '  FAIL  %s\n' "$1"
  FAILED=$(( FAILED + 1 ))
}

check() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    pass "$label"
  else
    fail "$label (expected '$expected', got '$actual')"
  fi
}

alive() {
  if kill -0 "$1" 2>/dev/null; then echo "alive"; else echo "gone"; fi
}

cleanup() {
  # 只有顶层 shell 做清理：EXIT trap 在每个子 shell 里也会触发，子 shell 中途回收
  # harness 自己的 fixture 会让结果失去意义。
  # macOS 的 Bash 3.2 没有 BASHPID；BASH_SUBSHELL 在该版本上可用，并且只在 harness
  # 的顶层 shell 中为 0。
  (( BASH_SUBSHELL == 0 )) || return 0
  local pid
  for pid in "${SPAWNED[@]:-}"; do
    if [[ -n "$pid" ]]; then
      kill -KILL "$pid" 2>/dev/null
    fi
  done
}
trap cleanup EXIT

printf '\nstop_tree harness (defect 25)\n\n'

# ─────────────────────────────────────────────────────────────────────────────
# 1. 父进程被发信号*之后*才 fork 出来的后代
# ─────────────────────────────────────────────────────────────────────────────
# 要证明的行为：stop_tree 在 TERM 发出之后仍会重新采样后代集合，存活复检与补发
# KILL 都基于最新的并集。TERM 之后才出生的子进程不在任何一次更早的快照里，它若
# 存活就会一直持有监听 socket 的 fd，下一次 `run.sh start` 就绑定不了端口。
#
# 直接在当前 shell 里派生，不经过 $( )：命令替换是子 shell，它的退出会同时干扰
# trap 和刚启动的作业。

GRANDCHILD_FILE="$(mktemp)"
bash -c "trap 'sleep 25 & echo \$! > $GRANDCHILD_FILE; sleep 1; exit 0' TERM
         while :; do sleep 0.2; done" >/dev/null 2>&1 &
late_fork_parent=$!
spawn_note "$late_fork_parent"
sleep 0.4

stop_tree "$late_fork_parent"

grandchild=$(cat "$GRANDCHILD_FILE" 2>/dev/null)
rm -f "$GRANDCHILD_FILE"
if [[ -z "$grandchild" ]]; then
  fail "late fork: the parent never spawned its post-TERM child (harness bug)"
else
  spawn_note "$grandchild"
  check "a child forked after TERM is reaped" "gone" "$(alive "$grandchild")"
fi
check "the late-forking parent is gone" "gone" "$(alive "$late_fork_parent")"

# ─────────────────────────────────────────────────────────────────────────────
# 2. 树外的进程不受影响
# ─────────────────────────────────────────────────────────────────────────────
# 并集必须保留已经不是后代的 PID（父进程一退出，子进程立刻被 reparent），而集合
# 里的 PID 在被回收后原则上可能收到信号。树外的任何进程都不允许被触碰。

sleep 25 &
bystander=$!
spawn_note "$bystander"

sleep 25 &
lone_root=$!
spawn_note "$lone_root"

sleep 0.2
stop_tree "$lone_root"

check "the tree root is gone" "gone" "$(alive "$lone_root")"
check "an unrelated process is untouched" "alive" "$(alive "$bystander")"
kill -KILL "$bystander" 2>/dev/null

# ─────────────────────────────────────────────────────────────────────────────
# 3. 普通进程树：父进程加两个子进程，没有 trap
# ─────────────────────────────────────────────────────────────────────────────
# 每一次真实的 stop 都走这条路径，它必须正常工作。

bash -c 'sleep 25 & sleep 25 & wait' >/dev/null 2>&1 &
plain_root=$!
spawn_note "$plain_root"
sleep 0.4

plain_children=$(pgrep -P "$plain_root" 2>/dev/null | tr '\n' ' ')
for child in $plain_children; do
  spawn_note "$child"
done

stop_tree "$plain_root"
plain_rc=$?

check "an ordinary tree stops cleanly" "0" "$plain_rc"
check "its root is gone" "gone" "$(alive "$plain_root")"
if [[ -z "$plain_children" ]]; then
  fail "ordinary tree: the root spawned no children (harness bug)"
fi
for child in $plain_children; do
  check "its child $child is gone" "gone" "$(alive "$child")"
done

# ─────────────────────────────────────────────────────────────────────────────
# 4. 本来就已经退出的 root
# ─────────────────────────────────────────────────────────────────────────────
# 返回 1 表示「它本来就没在运行」，四个调用点中有两个依赖这个读法。

sleep 0.1 &
dead_pid=$!
wait "$dead_pid" 2>/dev/null
stop_tree "$dead_pid"
dead_rc=$?

check "a dead root reports not-running" "1" "$dead_rc"

# ─────────────────────────────────────────────────────────────────────────────

printf '\n  %d passed, %d failed\n\n' "$PASSED" "$FAILED"
if (( FAILED > 0 )); then
  exit 1
fi
exit 0
