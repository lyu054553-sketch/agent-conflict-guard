"""Deliver new conflict risks to the orchestrator model.

Two channels:
  hook   Claude Code hook (PostToolUse / UserPromptSubmit). The alert is returned as
         `additionalContext`, so it lands in the orchestrator's context on its next step.
  t3     `t3 thread send <thread> -`. T3 Code queues the alert as the thread's next turn,
         so this works for any provider acting as orchestrator.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import store
from .detect import collect
from .gitstate import main_root

ROUTED_LEVELS = ("high", "medium")
LEVEL_CN = {"high": "高", "medium": "中", "low": "低"}


def format_alert(conflicts: list[dict], orchestrator: str = "Claude Opus 5.5") -> str:
    lines = [f"【冲突监控】发现 {len(conflicts)} 个新的冲突风险。你是主控（{orchestrator}），由你来处理："]
    for i, c in enumerate(conflicts, 1):
        lines.append(f"{i}. [{LEVEL_CN[c['level']]}] {c['kind']}：{c['title']}")
        lines.append(f"   涉及：{'；'.join(c['who'])}")
        lines.append(f"   文件：{', '.join(c['files'][:12])}")
        lines.append(f"   建议：{c['suggestion']}")
    lines.append("处理要求：先暂停涉及这些文件的新派活和合并；决定每个文件由谁负责；需要用户取舍时停下来问。"
                 "处理完运行 python3 scripts/agents/monitor.py check 复查。")
    return "\n".join(lines)


def new_alerts(root: str, conflicts: list[dict], channel: str) -> list[dict]:
    routable = [c for c in conflicts if c["level"] in ROUTED_LEVELS]
    fresh = set(store.take_new(root, [c["fp"] for c in routable], channel))
    return [c for c in routable if c["fp"] in fresh]


def hook(stdin=sys.stdin, stdout=sys.stdout, t3_db: Path | None = None) -> None:
    """Claude Code hook entry point. Never raises: a broken monitor must not block the orchestrator."""
    try:
        payload = json.load(stdin) if not stdin.isatty() else {}
    except Exception:
        payload = {}
    event = payload.get("hook_event_name") or "PostToolUse"
    try:
        root = main_root(payload.get("cwd"))
        if not root:
            return
        fresh = new_alerts(root, collect(root, t3_db)["conflicts"], "hook")
    except Exception:
        return
    if fresh:
        out = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": format_alert(fresh)}}
        stdout.write(json.dumps(out, ensure_ascii=False) + "\n")


def t3_bin() -> str | None:
    found = shutil.which("t3")
    if found:
        return found
    default = Path.home() / ".t3" / "bin" / "t3"
    return str(default) if default.exists() else None


def send_to_t3(thread_id: str, text: str, binary: str | None = None, runner=subprocess.run) -> bool:
    binary = binary or t3_bin()
    if not binary:
        return False
    r = runner([binary, "thread", "send", thread_id, "-"], input=text, text=True, capture_output=True, timeout=30)
    return r.returncode == 0


def watch(root: str, thread_id: str, interval: float = 5.0, once: bool = False, sender=send_to_t3) -> None:
    """Poll for conflicts and send new ones to a T3 thread (the orchestrator's thread)."""
    while True:
        try:
            fresh = new_alerts(root, collect(root)["conflicts"], "t3")
            if fresh and not sender(thread_id, format_alert(fresh)):
                # Delivery failed: forget these so the next poll retries them.
                seen = store.load(root, "t3")
                for c in fresh:
                    seen.pop(c["fp"], None)
                store.store_path(root, "t3").write_text(json.dumps(seen))
                print("发送到 T3 会话失败，下次轮询重试", file=sys.stderr)
            elif fresh:
                print(f"已把 {len(fresh)} 个冲突发给 T3 会话 {thread_id}")
        except Exception as e:
            print(f"检查失败：{e}", file=sys.stderr)
        if once:
            return
        time.sleep(interval)
