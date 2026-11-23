#!/usr/bin/env bash
# 把一件事交给某个模型去做。
#
# 用法:
#   scripts/agents/ask.sh <角色> <任务文件>            只读：出方案、审稿、整理文字
#   scripts/agents/ask.sh <角色> <任务文件> --write    可写：在独立的 git worktree 和分支里写代码
#
# 角色: plan | ux | copy-cn | backend-hard | backend-easy | chores
# 结果写到 .agents/out/，最后一条回复会打印到终端。每次调用的开始和结束都记进 .agents/events.jsonl，供监控使用。
set -euo pipefail

if [ $# -lt 2 ]; then
  sed -n '2,10p' "$0"; exit 2
fi
role="$1"; task="$2"; mode="${3:-}"
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$here/models.env"

case "$role" in
  plan)         model="$MODEL_PLAN" ;;
  ux)           model="$MODEL_UX" ;;
  copy-cn)      model="$MODEL_COPY_CN" ;;
  backend-hard) model="$MODEL_BACKEND_HARD" ;;
  backend-easy) model="$MODEL_BACKEND_EASY" ;;
  chores)       model="$MODEL_CHORES" ;;
  *) echo "未知角色: $role" >&2; exit 2 ;;
esac
[ -f "$task" ] || { echo "找不到任务文件: $task" >&2; exit 2; }

root="$(git rev-parse --show-toplevel)"
ts="$(date +%Y%m%d-%H%M%S)"
id="$ts-$role-$$"
outdir="$root/.agents/out"; mkdir -p "$outdir"
out="$outdir/$ts-$role.md"
log="$outdir/$ts-$role.log"
title="$(head -1 "$task" | sed 's/^#* *//')"
task_rel="${task#"$root"/}"

# 记录事件；监控出问题不影响派活
log_event() { python3 "$here/monitor.py" log "$@" --root "$root" >/dev/null 2>&1 || true; }
status="fail"
finish() { log_event end --id "$id" --status "$status" --out "$out"; }

echo ">> $role → $model" >&2

# Antigravity（agy:模型名）：只用于只读咨询
if [[ "$model" == agy:* ]]; then
  [ "$mode" = "--write" ] && { echo "agy 角色只用于只读咨询，写代码请用 Codex 里的模型" >&2; exit 2; }
  log_event start --id "$id" --role "$role" --model "$model" --mode read --task "$task_rel" --title "$title" --via ask.sh --pid $$
  trap finish EXIT
  prompt="$(cat "$task")

---
规则：这是只读咨询。不要执行任何终端命令，不要创建或修改文件，只用读文件和搜索工具看代码。
把完整内容直接写在这条回复里。"
  # 非交互模式下，需要确认的操作（运行命令、写文件）会被自动拒绝，所以它改不了东西；
  # 但一旦被拒绝，这次调用就会中止且没有输出，所以失败时重试一次。
  ok=""
  for attempt in 1 2; do
    if (cd "$root" && agy -p "$prompt" --model "${model#agy:}" --sandbox --print-timeout 0) >"$out" 2>"$log" && [ -s "$out" ]; then
      ok=1; break
    fi
    echo "第 $attempt 次没有拿到输出：$(tail -1 "$log")" >&2
  done
  [ -n "$ok" ] || { echo "执行失败，日志: $log" >&2; exit 1; }
  status="ok"
  echo "---- 回执（$out）----"; cat "$out"; exit 0
fi

if [ "$mode" = "--write" ]; then
  if [ -n "$(git -C "$root" status --porcelain)" ]; then
    echo "主工作区有未提交的改动。先提交，派出去的活才能基于最新代码。" >&2; exit 1
  fi
  branch="agent/$role-$ts"
  wt="$root/.agents/worktrees/$role-$ts"
  git -C "$root" worktree add -q -b "$branch" "$wt" HEAD
  log_event start --id "$id" --role "$role" --model "$model" --mode write --task "$task_rel" --title "$title" \
    --branch "$branch" --worktree "$wt" --via ask.sh --pid $$
  trap finish EXIT
  if ! codex exec -m "$model" -C "$wt" -s workspace-write --ephemeral -o "$out" - <"$task" >/dev/null 2>"$log"; then
    echo "执行失败，日志: $log" >&2; tail -20 "$log" >&2; exit 1
  fi
  git -C "$wt" add -A
  git -C "$wt" commit -qm "agent($role/$model): $title" || echo "（没有产生改动）" >&2
  status="ok"
  echo "分支: $branch"
  echo "工作区: $wt"
  echo "改动:"; git -C "$root" diff --stat "HEAD...$branch"
else
  log_event start --id "$id" --role "$role" --model "$model" --mode read --task "$task_rel" --title "$title" --via ask.sh --pid $$
  trap finish EXIT
  if ! codex exec -m "$model" -C "$root" -s read-only --ephemeral -o "$out" - <"$task" >/dev/null 2>"$log"; then
    echo "执行失败，日志: $log" >&2; tail -20 "$log" >&2; exit 1
  fi
  status="ok"
fi

echo "---- 回执（$out）----"
cat "$out"

# 写代码的活回来后顺手查一次冲突，结果直接给主控看
if [ "$mode" = "--write" ]; then
  python3 "$here/monitor.py" check 2>/dev/null | sed -n '/^冲突风险/,$p' || true
fi
