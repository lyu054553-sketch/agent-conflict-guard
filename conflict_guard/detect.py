"""Collect the state of every parallel workspace and find conflict risks between them.

A *change set* is one place where code is being changed: the main checkout, or a linked
worktree (one per dispatched agent or isolated T3 thread). Conflict rules compare change sets.

Levels:
  high    a merge is certain to conflict, or two live writers share files / a directory
  medium  shared files where at least one side has stopped, or overlapping task scopes
  low     housekeeping (an agent that died mid-task)
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from itertools import combinations
from pathlib import Path

from . import store
from .events import pid_alive, read_agents
from .gitstate import branch_files, head_branch, list_worktrees, merge_conflicts, status_files
from .models import load_names
from .t3 import t3_threads

PATH_RE = re.compile(
    r"[\w.\-]+(?:/[\w.\-]+)+"
    r"|[\w\-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|kt|swift|sql|vue|css|html|md|json|yaml|yml|toml)"
)
LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2}


def fingerprint(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()[:12]


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b) and Path(a).resolve() == Path(b).resolve()


def build_changesets(root: str, head: str, agents: list[dict], t3: list[dict]) -> list[dict]:
    sets = [{
        "id": "main", "label": "主工作区", "path": root, "branch": head,
        "files": status_files(root), "active": True, "has_branch": False,
    }]
    for w in list_worktrees(root):
        owner = next((a for a in agents if _same(a.get("worktree"), w["path"])), None)
        thread = next((t for t in t3 if _same(t.get("worktree"), w["path"])), None)
        files = sorted(set(branch_files(root, w["branch"])) | set(status_files(w["path"])))
        if owner:
            label, active = f'{owner["model_name"]} · {owner["role_label"]}', owner["state"] == "running"
            owner["files"] = files
        elif thread:
            label, active = f'T3 会话「{thread["title"]}」· {thread["model_name"]}', thread["active"]
            thread["files"] = files
        else:
            label, active = f'worktree {w["branch"]}', False
        sets.append({"id": w["branch"], "label": label, "path": w["path"], "branch": w["branch"],
                     "files": files, "active": active, "has_branch": True})
    return sets


def find_conflicts(root: str, head: str, changesets: list[dict], agents: list[dict], t3: list[dict]) -> list[dict]:
    conflicts: list[dict] = []
    merge_pairs: set[tuple[str, str]] = set()
    branches = [c for c in changesets if c["has_branch"]]

    # Rule 1: merge simulation. Certain conflicts, found before anyone merges.
    for c in branches:
        bad = merge_conflicts(root, "HEAD", c["branch"])
        if bad:
            merge_pairs.add(("main", c["id"]))
            conflicts.append(dict(
                fp=fingerprint("merge-head", c["branch"], bad), level="high", kind="合并会冲突",
                title=f'{c["label"]} 并回 {head} 时会冲突', who=[c["label"], head], files=bad,
                suggestion=f'先别合并 {c["branch"]}。在它的 worktree 里基于最新的 {head} 变基，或者由主控手动解决这些文件后再合。'))
    for a, b in combinations(branches, 2):
        bad = merge_conflicts(root, a["branch"], b["branch"])
        if bad:
            merge_pairs.add((a["id"], b["id"]))
            conflicts.append(dict(
                fp=fingerprint("merge-pair", sorted([a["branch"], b["branch"]]), bad), level="high", kind="合并会冲突",
                title=f'{a["label"]} 和 {b["label"]} 改了同一处', who=[a["label"], b["label"]], files=bad,
                suggestion="两个分支只能先合一个。主控决定先合哪个，另一个基于合并后的代码重做冲突部分。"))

    # Rule 2: shared files, including uncommitted edits. The early warning while agents are still working.
    for a, b in combinations(changesets, 2):
        both = sorted(set(a["files"]) & set(b["files"]))
        if not both or (a["id"], b["id"]) in merge_pairs:
            continue
        conflicts.append(dict(
            fp=fingerprint("overlap", sorted([a["id"], b["id"]]), both),
            level="high" if a["active"] and b["active"] else "medium", kind="同一文件多方在改",
            title=f'{a["label"]} 和 {b["label"]} 都在改同样的文件', who=[a["label"], b["label"]], files=both,
            suggestion="主控指定这些文件只由一方负责；另一方暂停对它们的修改，等先完成的一方合并后再继续。"))

    # Rule 3: several live T3 threads writing in the same directory without worktree isolation.
    by_dir: dict[str, list[dict]] = {}
    for t in t3:
        if t["active"]:
            by_dir.setdefault(str(Path(t["cwd"]).resolve()), []).append(t)
    for d, ts in by_dir.items():
        if len(ts) > 1:
            conflicts.append(dict(
                fp=fingerprint("same-dir", d, sorted(t["id"] for t in ts)), level="high", kind="同一目录并行",
                title=f"{len(ts)} 个 T3 会话正同时在同一个目录里工作",
                who=[f'「{t["title"]}」· {t["model_name"]}' for t in ts], files=[d],
                suggestion="同一目录里并行写代码会互相覆盖。让其中一个会话改用 worktree，或者先暂停到另一个完成。"))

    # Rule 4: live write tasks whose task files mention the same paths.
    writers = [a for a in agents if a["state"] == "running" and a.get("mode") == "write" and a.get("task")]
    for a, b in combinations(writers, 2):
        try:
            pa = set(PATH_RE.findall(Path(root, a["task"]).read_text(encoding="utf-8")))
            pb = set(PATH_RE.findall(Path(root, b["task"]).read_text(encoding="utf-8")))
        except OSError:
            continue
        both = sorted(pa & pb)
        if both:
            la, lb = f'{a["model_name"]} · {a["role_label"]}', f'{b["model_name"]} · {b["role_label"]}'
            conflicts.append(dict(
                fp=fingerprint("scope", sorted([a["id"], b["id"]]), both), level="medium", kind="派活范围重叠",
                title=f"{la} 和 {lb} 的派活单提到了相同的文件", who=[la, lb], files=both,
                suggestion="确认两张派活单的边界：在「不要做」里写明对方负责的文件。"))

    # Rule 5: an agent process died without recording an end event.
    for a in agents:
        if a["state"] == "interrupted":
            label = f'{a["model_name"]} · {a["role_label"]}'
            conflicts.append(dict(
                fp=fingerprint("interrupted", a["id"]), level="low", kind="派活中断",
                title=f"{label} 没有正常结束", who=[label], files=[a.get("worktree") or ""],
                suggestion="检查它的 worktree 里有没有半成品；不要就用 git worktree remove 删掉。"))

    conflicts.sort(key=lambda c: LEVEL_ORDER[c["level"]])
    return conflicts


def collect(root: str, t3_db: Path | None = None, alive=pid_alive) -> dict:
    now = time.time()
    names = load_names()
    agents = read_agents(root, names, now, alive=alive)
    head = head_branch(root)
    t3, t3_err = t3_threads(root, names, t3_db)
    changesets = build_changesets(root, head, agents, t3)
    conflicts = find_conflicts(root, head, changesets, agents, t3)
    routed = store.routed_times(root)
    for c in conflicts:
        c["routed_at"] = routed.get(c["fp"])
    return {
        "root": root, "project": Path(root).name, "branch": head, "now": now,
        "orchestrator": {"model": "claude-opus-5-5", "model_name": "Claude Opus 5.5", "role": "主控"},
        "agents": agents[:40], "changesets": changesets, "t3": t3, "t3_error": t3_err, "conflicts": conflicts,
    }
