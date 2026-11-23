# Design

## Problem

Coding agents are now cheap enough to run several at once: one model writes the API, another
the migration, a third the tests. Each agent sees only its own task. Nothing stops two of them
from editing the same function, and the collision is usually discovered at merge time, after
both have spent their budget. The orchestrating model (the one talking to the user) has no
shared view of who is changing what.

This project gives the orchestrator that view, and pushes risks to it before they become
merge failures.

## Constraints

- **No changes to the host tools.** T3 Code, Claude Code and Codex are used as they are. T3 Code
  does not accept feature contributions, so the monitor runs beside it and reads its state
  read-only.
- **No side effects.** Detection must never touch a working tree, the index or HEAD, since agents
  are working in those trees at the same moment.
- **Never block the orchestrator.** The hook runs after every shell command the orchestrator
  executes. Any failure must degrade to "no alert", never to an error in the agent loop.
- **Standard library only**, so it installs into any project by copying a folder.

## Architecture

```
 dispatch scripts ──► .agents/events.jsonl ─┐
 (ask.sh, review.sh)                        │
                                            ├──► detect.collect() ──► conflicts ──► routing ──► orchestrator
 git: main checkout + linked worktrees ─────┤        (5 rules)           │            ├─ Claude Code hook (additionalContext)
                                            │                            │            └─ t3 thread send (any provider)
 T3 Code state DB (read-only, optional) ────┘                            └──► web dashboard / CLI
```

| Module | Responsibility |
|---|---|
| `gitstate.py` | Changed files per working tree, files per branch, merge simulation, worktree listing |
| `events.py` | Append and fold dispatch events into one record per agent; detect dead agents by PID |
| `t3.py` | Read T3 Code threads, models, run status and recent steps from its SQLite store |
| `detect.py` | Build *change sets* (one per working tree) and apply the conflict rules |
| `store.py` | Remember which conflicts each delivery channel has already sent |
| `routing.py` | Format alerts and deliver them through the hook or a T3 thread |
| `server.py`, `web/` | Local dashboard polling `/api/state` every two seconds |

## Change sets

Every place where code is being changed is a change set: the main checkout (the orchestrator
and any T3 thread working there) and each linked worktree (one per dispatched agent or isolated
T3 thread). A change set's files are the union of its committed changes since the fork point and
its uncommitted edits. Including uncommitted edits is what makes the warning arrive while agents
are still typing, not only after they commit.

## Rules

| # | Rule | Signal | Level |
|---|---|---|---|
| 1 | Merge simulation | `git merge-tree --write-tree` reports conflicts between a branch and HEAD, or between two branches | high (certain) |
| 2 | Shared files | two change sets touch the same path | high if both are live, else medium |
| 3 | Same directory | two live T3 threads share a working directory without worktree isolation | high |
| 4 | Task scope | two live write tasks mention the same paths in their task files | medium |
| 5 | Interrupted | an agent's process is gone but no end event was written | low |

Rule 2 is suppressed for a pair already reported by rule 1, so one collision produces one alert.

The two-tier design follows from the experiment (see `experiments/results/summary.md`): sharing
a file is a weak predictor of a real conflict, while merge simulation is exact. Rule 1 says
"this will fail", rule 2 says "watch this", and the orchestrator can treat them differently.

## Routing to the orchestrator

Only high and medium risks are routed. Each conflict has a fingerprint (rule, parties, files).
A channel stores the fingerprints it has delivered; a fingerprint that disappears is forgotten,
so a conflict that is resolved and later reappears is delivered again.

- **Claude Code hook.** `PostToolUse` (matcher `Bash`) and `UserPromptSubmit` call
  `monitor.py hook`, which returns the alert as `additionalContext`. The orchestrator reads it on
  its next step. The project's `CLAUDE.md` tells it how to respond.
- **T3 thread.** `acg watch --t3-thread <id>` polls and sends alerts with `t3 thread send`.
  T3 Code queues the message as the thread's next turn, so this works whichever provider is
  orchestrating. A failed delivery is un-remembered and retried on the next poll.

## Known limitations

- Pairwise merge simulation can in principle miss a conflict that only appears when three or
  more branches are combined. It did not occur in the experiment; the merge-time check
  (rule 1 against HEAD) still catches it before the merge.
- Rule 1 needs commits. Before an agent commits, only rule 2 (shared files) applies.
- The orchestrator's own file edits are checked on its next shell command or user message,
  not immediately after an edit.
- The T3 Code reader depends on an internal schema of a nightly build. It is isolated and
  degrades to an explanatory message when the schema changes.
- Running state of T3 threads is inferred from run status; it has been tested against a
  fixture database, not yet against a live running T3 turn.
- Rule 1 and rule 2 compare every pair, so cost grows quadratically with the number of live
  worktrees (see the latency table in the results).
