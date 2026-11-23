#!/usr/bin/env bash
# Install the multi-model kit and the conflict monitor into a project (once per project).
# Usage: kit/install.sh /path/to/your/project
set -euo pipefail
kit="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$kit/.." && pwd)"
dst="${1:?usage: kit/install.sh /path/to/your/project}"
[ -d "$dst/.git" ] || { echo "$dst is not a git repository" >&2; exit 1; }

mkdir -p "$dst/scripts/agents" "$dst/.claude/skills/ship"
cp "$kit/ask.sh" "$kit/review.sh" "$kit/models.env" "$kit/monitor.py" "$dst/scripts/agents/"
rm -rf "$dst/scripts/agents/conflict_guard"
cp -R "$repo/conflict_guard" "$dst/scripts/agents/conflict_guard"
find "$dst/scripts/agents/conflict_guard" -name '__pycache__' -type d -prune -exec rm -rf {} +
chmod +x "$dst/scripts/agents/"*.sh "$dst/scripts/agents/monitor.py"
cp "$kit/skills/ship/SKILL.md" "$dst/.claude/skills/ship/SKILL.md"

if [ -f "$dst/CLAUDE.md" ]; then
  grep -q '多模型协作约定' "$dst/CLAUDE.md" || { printf '\n' >>"$dst/CLAUDE.md"; cat "$kit/CLAUDE.md" >>"$dst/CLAUDE.md"; }
else
  cp "$kit/CLAUDE.md" "$dst/CLAUDE.md"
fi

# Merge the conflict-monitor hooks into .claude/settings.json without touching other settings.
python3 - "$kit/claude-hooks.json" "$dst/.claude/settings.json" <<'PY'
import json, sys, pathlib
tpl = json.loads(pathlib.Path(sys.argv[1]).read_text())
p = pathlib.Path(sys.argv[2])
cur = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
hooks = cur.setdefault("hooks", {})
for event, groups in tpl["hooks"].items():
    have = hooks.setdefault(event, [])
    for g in groups:
        cmd = g["hooks"][0]["command"]
        if not any(h.get("command") == cmd for x in have for h in x.get("hooks", [])):
            have.append(g)
p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n")
PY

grep -qx '.agents/' "$dst/.gitignore" 2>/dev/null || echo '.agents/' >>"$dst/.gitignore"
echo "Installed into $dst"
echo "Live dashboard:  cd $dst && python3 scripts/agents/monitor.py serve   →  http://127.0.0.1:4317"
