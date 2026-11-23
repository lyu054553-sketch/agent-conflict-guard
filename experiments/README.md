# Experiment: predicting merge conflicts between parallel agents

## Question

When several agents edit a repository in parallel, can we warn about merge conflicts *before*
anyone merges, and how much better is merge simulation than the common "same file" heuristic?

## Method

- **Code base.** 6 modules with 8 small functions each.
- **Scenarios.** 300 scenarios, seed 42. In each, 2–5 agents branch from the same commit. Each
  agent edits 1–3 modules, 1–2 edits per module, drawn from: change a function body (60%),
  append a function at the end of the file (25%), insert a function after a random function (15%).
  Every agent's text is unique, as real agent output would be.
- **Ground truth.** Branches are merged into `main` in order with real `git merge`. A branch whose
  merge stops with conflicts is labelled conflicting, and that merge is aborted.
- **Predictors**, evaluated per branch against the branches actually merged before it:
  - *file overlap* (baseline): the branch shares a file with an earlier-merged branch;
  - *pairwise merge-tree* (this project): `git merge-tree --write-tree` reports a conflict
    between the branch and an earlier-merged branch.
- **Exactness.** Before every real merge, `merge-tree HEAD <branch>` is recorded and compared
  with the merge outcome.
- **Latency.** Wall time of one full `collect()` (all five rules, no T3 database) with 2, 4, 8,
  12 and 16 live worktrees, median of 5 runs.

## Reproduce

```bash
python3 experiments/run_experiment.py --scenarios 300 --seed 42
```

Output: `experiments/results/summary.md` and `experiments/results/results.json`.

## Threats to validity

- The edits are synthetic. Real agents make larger, more varied changes (renames, reformatting,
  moved code), which changes both the base rate of conflicts and the gap between the predictors.
- Pairwise simulation is exact for pairs; conflicts that only arise from three or more branches
  combined are possible in principle and are not specifically generated here.
- Latency was measured on one machine; absolute numbers depend on disk and repository size.

A natural next step is the same evaluation on real agent runs: dispatch the same task set to
several models in parallel (the kit's `ask.sh --write`), then compare predictions with real merges.
