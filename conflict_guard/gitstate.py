"""Read-only views of git state: what each workspace is changing, and whether merges would conflict."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

IGNORED_PREFIXES = (".agents/",)


def run(cmd: list[str], cwd: str | None = None, timeout: int = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except Exception:
        return 1, ""


def git(args: list[str], cwd: str) -> tuple[int, str]:
    return run(["git", *args], cwd=cwd)


def main_root(start: str | None = None) -> str | None:
    """Root of the main repository, even when called from inside a linked worktree."""
    code, out = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], start or os.getcwd())
    if code != 0 or not out.strip():
        return None
    return str(Path(out.strip()).parent)


def head_branch(root: str) -> str:
    _, out = git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    return out.strip()


def _keep(path: str) -> bool:
    return bool(path) and not path.startswith(IGNORED_PREFIXES)


def status_files(path: str) -> list[str]:
    """Uncommitted changes (including untracked files) in one working tree."""
    code, out = git(["status", "--porcelain", "-z", "--untracked-files=all"], path)
    if code != 0:
        return []
    files: list[str] = []
    toks = out.split("\0")
    i = 0
    while i < len(toks):
        tok = toks[i]
        if len(tok) > 3:
            xy, p = tok[:2], tok[3:]
            if _keep(p):
                files.append(p)
            if xy[0] in "RC":  # renames and copies carry the original path as an extra token
                i += 1
        i += 1
    return files


def branch_files(root: str, branch: str, base_ref: str = "HEAD") -> list[str]:
    """Files committed on `branch` since it forked from `base_ref`."""
    code, base = git(["merge-base", base_ref, branch], root)
    if code != 0:
        return []
    code, out = git(["diff", "--name-only", base.strip(), branch], root)
    return [f for f in out.splitlines() if _keep(f)]


def merge_conflicts(root: str, a: str, b: str) -> list[str]:
    """Simulate merging `a` and `b` without touching any working tree; return the conflicted files.

    Uses `git merge-tree --write-tree` (git >= 2.38), which writes objects only and never
    changes the index, HEAD or any checkout.
    """
    code, out = git(["merge-tree", "--write-tree", "--name-only", "--no-messages", a, b], root)
    if code == 1:
        return sorted({line for line in out.splitlines()[1:] if line.strip()})
    return []


def list_worktrees(root: str) -> list[dict]:
    """Linked worktrees with a branch checked out (the main checkout is excluded)."""
    _, out = git(["worktree", "list", "--porcelain"], root)
    result, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur.get("path") and cur.get("branch") and Path(cur["path"]).resolve() != Path(root).resolve():
                result.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[len("worktree "):]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].removeprefix("refs/heads/")
    return result
