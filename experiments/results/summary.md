# Experiment results

300 scenarios (seed 42), 1037 agent branches, 190 of them hit a real merge conflict (148 scenarios had at least one). git version 2.50.1 (Apple Git-155), Python 3.15.2.

## Early warning before any merge

| Predictor | Precision | Recall | F1 | False-alarm rate | TP | FP | FN | TN |
|---|---|---|---|---|---|---|---|---|
| file overlap (baseline) | 0.359 | 1.000 | 0.528 | 0.400 | 190 | 339 | 0 | 508 |
| pairwise merge-tree (this project) | 1.000 | 1.000 | 1.000 | 0.000 | 190 | 0 | 0 | 847 |

Of 1463 branch pairs, 837 touched a common file; only 233 of those pairs actually conflict (27.8%).

## Exactness at merge time

`merge-tree HEAD <branch>` disagreed with the real `git merge` in 0 of 1037 merges.

## Latency of one full check

| Live worktrees | Median (ms) | Max (ms) |
|---|---|---|
| 2 | 139.1 | 155.8 |
| 4 | 272.6 | 299.0 |
| 8 | 674.3 | 695.6 |
| 12 | 1301.1 | 1369.1 |
| 16 | 1944.2 | 2046.8 |

Total runtime 146.3 s.
