"""Read-only view of T3 Code sessions from its local state database.

T3 Code ships nightly and its schema can change. Every read here is wrapped so that a schema
change degrades this one panel instead of breaking the monitor.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .models import display, is_cn

DONE = {"completed", "failed", "cancelled", "canceled", "interrupted", "stopped", "error", "errored", "aborted", "done"}


def default_db() -> Path:
    if os.environ.get("ACG_T3_DB"):
        return Path(os.environ["ACG_T3_DB"])
    home = Path(os.environ.get("T3CODE_HOME", Path.home() / ".t3"))
    return home / "userdata" / "statev2.sqlite"


def t3_threads(root: str, names: dict[str, str], db: Path | None = None) -> tuple[list[dict], str | None]:
    """Threads of the T3 project whose workspace is `root`. Returns (threads, error message or None)."""
    db = db or default_db()
    if not db.exists():
        return [], f"没有找到 T3 Code 的数据（{db}）"
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
        con.row_factory = sqlite3.Row
        want = str(Path(root).resolve())
        pids = [
            r["project_id"]
            for r in con.execute("select project_id, workspace_root from projection_projects where deleted_at is null")
            if r["workspace_root"] and str(Path(r["workspace_root"]).resolve()) == want
        ]
        if not pids:
            return [], "T3 Code 里还没有添加这个项目"
        marks = ",".join("?" * len(pids))
        threads = []
        rows = con.execute(
            "select thread_id, title, default_provider, payload_json, updated_at "
            "from orchestration_v2_projection_threads "
            f"where project_id in ({marks}) and deleted_at is null and archived_at is null "
            "order by updated_at desc limit 12",
            pids,
        ).fetchall()
        for t in rows:
            pl = json.loads(t["payload_json"] or "{}")
            model = (pl.get("modelSelection") or {}).get("model") or ""
            run = con.execute(
                "select status, completed_at from orchestration_v2_projection_runs "
                "where thread_id=? order by ordinal desc limit 1",
                (t["thread_id"],),
            ).fetchone()
            sess = con.execute(
                "select payload_json from orchestration_v2_projection_provider_sessions "
                "where thread_id=? order by updated_at desc limit 1",
                (t["thread_id"],),
            ).fetchone()
            cwd = pl.get("worktreePath") or (json.loads(sess["payload_json"]).get("cwd") if sess else None) or root
            steps = []
            for it in con.execute(
                "select type, status, updated_at, payload_json from orchestration_v2_projection_turn_items "
                "where thread_id=? and type not in ('user_message','assistant_message','reasoning') "
                "order by ordinal desc limit 5",
                (t["thread_id"],),
            ):
                ip = json.loads(it["payload_json"] or "{}")
                steps.append({"type": it["type"], "status": it["status"], "title": ip.get("title") or it["type"], "at": it["updated_at"]})
            subs = con.execute(
                "select count(*) from orchestration_v2_projection_subagents where thread_id=? "
                "and status not in ('completed','failed','cancelled','interrupted','stopped')",
                (t["thread_id"],),
            ).fetchone()[0]
            status = run["status"] if run else "idle"
            threads.append({
                "id": t["thread_id"], "title": t["title"], "provider": t["default_provider"],
                "model": model, "model_name": display(model, names), "cn": is_cn(model),
                "status": status, "active": bool(run) and status not in DONE and not run["completed_at"],
                "cwd": cwd, "worktree": pl.get("worktreePath"), "branch": pl.get("branch"),
                "updated": t["updated_at"], "steps": steps, "subagents": subs,
            })
        con.close()
        return threads, None
    except Exception as e:
        return [], f"读取 T3 数据失败：{e}"
