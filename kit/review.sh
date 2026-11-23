#!/usr/bin/env bash
# 审查当前分支相对基线分支的改动。
#
# 用法:
#   scripts/agents/review.sh pre   [基线分支]   DeepSeek V4.1 Flash 预审（便宜，先挑低级问题）
#   scripts/agents/review.sh final [基线分支]   GPT-6.2-Sol 最终审查（流程里最多 2 轮）
set -euo pipefail

stage="${1:-}"; base="${2:-main}"
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$here/models.env"

case "$stage" in
  pre)   model="$MODEL_PRE_REVIEW" ;;
  final) model="$MODEL_FINAL_REVIEW" ;;
  *) sed -n '2,6p' "$0"; exit 2 ;;
esac

root="$(git rev-parse --show-toplevel)"
outdir="$root/.agents/out"; mkdir -p "$outdir"
ts="$(date +%Y%m%d-%H%M%S)"
out="$outdir/$ts-review-$stage.md"
id="$ts-review-$stage-$$"

log_event() { python3 "$here/monitor.py" log "$@" --root "$root" >/dev/null 2>&1 || true; }
status="fail"
log_event start --id "$id" --role "review-$stage" --model "$model" --mode read \
  --title "审查 $(git rev-parse --abbrev-ref HEAD) 相对 $base 的改动" --via review.sh --pid $$
trap 'log_event end --id "$id" --status "$status" --out "$out"' EXIT

echo ">> review $stage → $model（基线 $base）" >&2
codex review -c "model=\"$model\"" --base "$base" 2>"$out.log" | tee "$out"
status="ok"
