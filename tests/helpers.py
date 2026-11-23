"""Test fixtures: throwaway git repositories and a fake T3 Code state database."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Keep tests independent of the machine: no real T3 data, no real model catalog.
os.environ["ACG_T3_DB"] = "/nonexistent/acg-test/statev2.sqlite"
os.environ["ACG_MODEL_CATALOG"] = "/nonexistent/acg-test/models.json"
os.environ.setdefault("GIT_CONFIG_NOSYSTEM", "1")


class Repo:
    """A temporary git repository with helpers for branches and worktrees."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="acg-test-")
        self.path = str(Path(self.dir).resolve())
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        self.git("config", "commit.gpgsign", "false")
        self.write(".gitignore", ".agents/\n")

    def git(self, *args, cwd=None, check=True) -> str:
        r = subprocess.run(["git", *args], cwd=cwd or self.path, capture_output=True, text=True)
        if check and r.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr}")
        return r.stdout

    def write(self, rel: str, text: str, cwd: str | None = None) -> None:
        p = Path(cwd or self.path, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def commit(self, msg: str = "change", cwd: str | None = None) -> None:
        self.git("add", "-A", cwd=cwd)
        self.git("commit", "-qm", msg, cwd=cwd)

    def worktree(self, branch: str) -> str:
        path = str(Path(self.path, ".agents", "worktrees", branch.replace("/", "-")))
        self.git("worktree", "add", "-q", "-b", branch, path)
        return path

    def event(self, **rec) -> None:
        p = Path(self.path, ".agents", "events.jsonl")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def cleanup(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


BASE_CALC = "def add(a, b):\n    return a + b\n\n\ndef neg(a):\n    return -a\n"


def make_t3_db(path: str, project_root: str, threads: list[dict]) -> str:
    """Create a minimal T3 Code state database with the tables and columns the reader uses."""
    con = sqlite3.connect(path)
    con.executescript("""
        create table projection_projects (project_id text, title text, workspace_root text, deleted_at text);
        create table orchestration_v2_projection_threads (thread_id text, project_id text, title text,
            default_provider text, payload_json text, updated_at text, archived_at text, deleted_at text);
        create table orchestration_v2_projection_runs (run_id text, thread_id text, ordinal int, status text,
            requested_at text, completed_at text);
        create table orchestration_v2_projection_provider_sessions (thread_id text, payload_json text, updated_at text);
        create table orchestration_v2_projection_turn_items (thread_id text, ordinal int, type text, status text,
            updated_at text, payload_json text);
        create table orchestration_v2_projection_subagents (thread_id text, status text);
    """)
    con.execute("insert into projection_projects values ('p1', 'demo', ?, null)", (project_root,))
    for i, t in enumerate(threads):
        tid = t.get("id", f"t{i}")
        payload = {"modelSelection": {"model": t.get("model", "claude-opus-5-5")}, "worktreePath": t.get("worktree")}
        con.execute("insert into orchestration_v2_projection_threads values (?, 'p1', ?, ?, ?, ?, null, null)",
                    (tid, t.get("title", tid), t.get("provider", "claudeAgent"), json.dumps(payload), f"2026-01-01T00:0{i}:00Z"))
        con.execute("insert into orchestration_v2_projection_runs values (?, ?, 1, ?, '2026-01-01T00:00:00Z', ?)",
                    (f"r{i}", tid, t.get("status", "running"), t.get("completed_at")))
        con.execute("insert into orchestration_v2_projection_provider_sessions values (?, ?, '2026-01-01T00:00:00Z')",
                    (tid, json.dumps({"cwd": t.get("cwd", project_root)})))
        con.execute("insert into orchestration_v2_projection_turn_items values (?, 1, 'command_execution', 'completed', 'x', ?)",
                    (tid, json.dumps({"title": "Ran tests"})))
    con.commit()
    con.close()
    return path
