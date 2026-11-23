#!/usr/bin/env python3
"""Reproducible experiment: how well can merge conflicts between parallel agents be predicted early?

Setup
  A synthetic code base (several modules, each with several small functions). In every scenario,
  k agents (2..5) branch from the same base commit and edit it in parallel. Edits are drawn from
  three kinds seen in real agent output: change a function body, append a function at the end of
  a file, insert a function in the middle of a file.

Ground truth
  The branches are merged into main one by one with real `git merge`. A branch is "conflicting"
  if its merge stops with conflicts (that merge is then aborted, as a human would before rework).

Early-warning predictors (run before any merge, while agents are still independent)
  file-overlap   warn if the branch touches a file that an earlier-merged branch also touched
  merge-tree     warn if `git merge-tree` reports a conflict with an earlier-merged branch

Also measured
  exactness      at merge time, does `merge-tree HEAD <branch>` agree with the real merge?
  latency        wall time of a full `collect()` (all rules) with 2..16 live worktrees

Usage
  python3 experiments/run_experiment.py --scenarios 300 --seed 42
  Results go to experiments/results/ (summary.md and results.json).
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from conflict_guard.detect import collect  # noqa: E402
from conflict_guard.gitstate import merge_conflicts  # noqa: E402

N_MODULES = 6
N_FUNCS = 8


def git(repo: str, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr}")
    return r


def module_source(m: int) -> list[str]:
    lines = [f'"""Module {m}."""', ""]
    for j in range(N_FUNCS):
        lines += ["", f"def f{m}_{j}(x):", f'    """Function {j} of module {m}."""',
                  f"    y = x + {j}", f"    return y * {m + 1}"]
    return lines


def init_repo(path: str) -> str:
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "exp@example.com")
    git(path, "config", "user.name", "exp")
    git(path, "config", "commit.gpgsign", "false")
    for m in range(N_MODULES):
        Path(path, f"mod{m}.py").write_text("\n".join(module_source(m)) + "\n")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "base")
    return git(path, "rev-parse", "HEAD").stdout.strip()


def apply_edit(lines: list[str], kind: str, m: int, j: int, tag: str) -> list[str]:
    """Edit one module's lines. `tag` makes each agent's text unique, as real agents' code would be."""
    if kind == "modify":
        target = f"    y = x + {j}"
        return [l + f"  # {tag}" if l == target else l for l in lines]
    new_fn = ["", "", f"def {tag}_{m}_{j}(x):", f'    """Added by {tag}."""', f"    return x - {j}"]
    if kind == "append":
        return lines + new_fn
    # insert after function j
    anchor = lines.index(f"    return y * {m + 1}", lines.index(f"def f{m}_{j}(x):"))
    return lines[: anchor + 1] + new_fn + lines[anchor + 1:]


def make_branch(repo: str, base: str, name: str, rng: random.Random, tag: str) -> set[str]:
    git(repo, "checkout", "-q", "-b", name, base)
    touched = set()
    for m in rng.sample(range(N_MODULES), rng.randint(1, 3)):
        path = Path(repo, f"mod{m}.py")
        lines = path.read_text().splitlines()
        for _ in range(rng.randint(1, 2)):
            kind = rng.choices(["modify", "append", "insert"], weights=[0.6, 0.25, 0.15])[0]
            lines = apply_edit(lines, kind, m, rng.randrange(N_FUNCS), tag)
        path.write_text("\n".join(lines) + "\n")
        touched.add(path.name)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"{tag} edits")
    git(repo, "checkout", "-q", "main")
    return touched


def run_scenario(repo: str, base: str, rng: random.Random, sid: int) -> dict:
    k = rng.randint(2, 5)
    names = [f"s{sid}-agent{i}" for i in range(k)]
    files = {n: make_branch(repo, base, n, rng, f"a{sid}x{i}") for i, n in enumerate(names)}

    # Early warnings: pairwise, before anything is merged.
    pair_overlap = {frozenset(p): bool(files[p[0]] & files[p[1]]) for p in combinations(names, 2)}
    pair_mtree = {frozenset(p): bool(merge_conflicts(repo, p[0], p[1])) for p in combinations(names, 2)}

    # Ground truth: merge one by one; at each step also check merge-tree HEAD exactness.
    merged, rows, exact_mismatch = [], [], 0
    for n in names:
        predicted_now = bool(merge_conflicts(repo, "HEAD", n))
        r = git(repo, "merge", "--no-edit", "-q", n, check=False)
        actual = r.returncode != 0
        if actual:
            git(repo, "merge", "--abort", check=False)
        if predicted_now != actual:
            exact_mismatch += 1
        rows.append({
            "branch": n,
            "actual": actual,
            "file_overlap": any(pair_overlap[frozenset((m, n))] for m in merged),
            "merge_tree": any(pair_mtree[frozenset((m, n))] for m in merged),
        })
        if not actual:
            merged.append(n)

    git(repo, "reset", "-q", "--hard", base)
    for n in names:
        git(repo, "branch", "-q", "-D", n)
    return {
        "k": k, "rows": rows, "exact_mismatch": exact_mismatch,
        "pairs_overlap": sum(pair_overlap.values()), "pairs_conflict": sum(pair_mtree.values()),
        "pairs": len(pair_overlap),
    }


def score(rows: list[dict], key: str) -> dict:
    tp = sum(r[key] and r["actual"] for r in rows)
    fp = sum(r[key] and not r["actual"] for r in rows)
    fn = sum(not r[key] and r["actual"] for r in rows)
    tn = sum(not r[key] and not r["actual"] for r in rows)
    prec = tp / (tp + fp) if tp + fp else 1.0
    rec = tp / (tp + fn) if tp + fn else 1.0
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": round(prec, 4), "recall": round(rec, 4),
            "false_alarm_rate": round(fp / (fp + tn), 4) if fp + tn else 0.0,
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0}


def latency(max_agents: int, repeats: int = 5) -> list[dict]:
    """Wall time of one full collect() with n live worktrees, each editing two modules."""
    out = []
    for n in [v for v in (2, 4, 8, 12, 16) if v <= max(2, max_agents)]:
        d = tempfile.mkdtemp(prefix="acg-lat-")
        try:
            repo = str(Path(d).resolve())
            init_repo(repo)
            rng = random.Random(n)
            for i in range(n):
                wt = str(Path(repo, ".agents", "worktrees", f"w{i}"))
                git(repo, "worktree", "add", "-q", "-b", f"lat/w{i}", wt)
                for m in rng.sample(range(N_MODULES), 2):
                    p = Path(wt, f"mod{m}.py")
                    p.write_text("\n".join(apply_edit(p.read_text().splitlines(), "modify", m, rng.randrange(N_FUNCS), f"w{i}")) + "\n")
                git(wt, "add", "-A")
                git(wt, "commit", "-qm", "w")
            times = []
            for _ in range(repeats):
                t0 = time.perf_counter()
                collect(repo, t3_db=Path("/nonexistent/acg.sqlite"), alive=lambda pid: False)
                times.append(time.perf_counter() - t0)
            out.append({"worktrees": n, "median_ms": round(statistics.median(times) * 1000, 1),
                        "max_ms": round(max(times) * 1000, 1)})
        finally:
            shutil.rmtree(d, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", type=int, default=300)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-agents-latency", type=int, default=16)
    ap.add_argument("--out", default=str(HERE / "results"))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    d = tempfile.mkdtemp(prefix="acg-exp-")
    t0 = time.time()
    try:
        repo = str(Path(d).resolve())
        base = init_repo(repo)
        scenarios = []
        for sid in range(args.scenarios):
            scenarios.append(run_scenario(repo, base, rng, sid))
            if (sid + 1) % 50 == 0:
                print(f"  {sid + 1}/{args.scenarios} scenarios", file=sys.stderr)
    finally:
        shutil.rmtree(d, ignore_errors=True)

    rows = [r for s in scenarios for r in s["rows"]]
    results = {
        "config": {"scenarios": args.scenarios, "seed": args.seed, "modules": N_MODULES,
                   "functions_per_module": N_FUNCS, "agents_per_scenario": "2-5",
                   "edit_mix": {"modify": 0.6, "append": 0.25, "insert": 0.15}},
        "branches": len(rows),
        "conflicting_branches": sum(r["actual"] for r in rows),
        "scenarios_with_conflict": sum(any(r["actual"] for r in s["rows"]) for s in scenarios),
        "pairs": sum(s["pairs"] for s in scenarios),
        "pairs_sharing_a_file": sum(s["pairs_overlap"] for s in scenarios),
        "pairs_truly_conflicting": sum(s["pairs_conflict"] for s in scenarios),
        "early_warning": {"file_overlap": score(rows, "file_overlap"), "merge_tree": score(rows, "merge_tree")},
        "merge_time_exactness": {"checks": len(rows), "mismatches": sum(s["exact_mismatch"] for s in scenarios)},
        "latency": latency(args.max_agents_latency),
        "runtime_s": round(time.time() - t0, 1),
        "git": subprocess.run(["git", "--version"], capture_output=True, text=True).stdout.strip(),
        "python": sys.version.split()[0],
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    (out / "summary.md").write_text(render(results))
    print(render(results))


def render(r: dict) -> str:
    fo, mt = r["early_warning"]["file_overlap"], r["early_warning"]["merge_tree"]
    share = r["pairs_sharing_a_file"]
    lines = [
        "# Experiment results",
        "",
        f"{r['config']['scenarios']} scenarios (seed {r['config']['seed']}), {r['branches']} agent branches, "
        f"{r['conflicting_branches']} of them hit a real merge conflict "
        f"({r['scenarios_with_conflict']} scenarios had at least one). {r['git']}, Python {r['python']}.",
        "",
        "## Early warning before any merge",
        "",
        "| Predictor | Precision | Recall | F1 | False-alarm rate | TP | FP | FN | TN |",
        "|---|---|---|---|---|---|---|---|---|",
        f"| file overlap (baseline) | {fo['precision']:.3f} | {fo['recall']:.3f} | {fo['f1']:.3f} | {fo['false_alarm_rate']:.3f} | {fo['tp']} | {fo['fp']} | {fo['fn']} | {fo['tn']} |",
        f"| pairwise merge-tree (this project) | {mt['precision']:.3f} | {mt['recall']:.3f} | {mt['f1']:.3f} | {mt['false_alarm_rate']:.3f} | {mt['tp']} | {mt['fp']} | {mt['fn']} | {mt['tn']} |",
        "",
        f"Of {r['pairs']} branch pairs, {share} touched a common file; only {r['pairs_truly_conflicting']} "
        f"of those pairs actually conflict ({(r['pairs_truly_conflicting'] / share * 100 if share else 0):.1f}%).",
        "",
        "## Exactness at merge time",
        "",
        f"`merge-tree HEAD <branch>` disagreed with the real `git merge` in "
        f"{r['merge_time_exactness']['mismatches']} of {r['merge_time_exactness']['checks']} merges.",
        "",
        "## Latency of one full check",
        "",
        "| Live worktrees | Median (ms) | Max (ms) |",
        "|---|---|---|",
        *[f"| {x['worktrees']} | {x['median_ms']} | {x['max_ms']} |" for x in r["latency"]],
        "",
        f"Total runtime {r['runtime_s']} s.",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
