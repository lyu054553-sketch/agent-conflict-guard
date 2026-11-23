"""Dispatch events written by the kit scripts (ask.sh / review.sh) to .agents/events.jsonl."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .models import ROLE_LABELS, display, is_cn, route_of


def events_path(root: str) -> Path:
    return Path(root) / ".agents" / "events.jsonl"


def append_event(root: str, record: dict) -> None:
    rec = dict(record)
    rec.setdefault("ts", time.time())
    p = events_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:  # O_APPEND: small lines from parallel writers stay intact
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def read_agents(root: str, names: dict[str, str], now: float | None = None, alive=pid_alive) -> list[dict]:
    """Fold start/end events into one record per dispatched agent, newest first."""
    now = time.time() if now is None else now
    p = events_path(root)
    if not p.exists():
        return []
    agents: dict[str, dict] = {}
    for line in p.read_text(encoding="utf-8").splitlines()[-2000:]:
        try:
            e = json.loads(line)
        except Exception:
            continue
        aid = e.get("id")
        if not aid:
            continue
        a = agents.setdefault(aid, {"id": aid})
        if e.get("event") == "start":
            a.update({k: v for k, v in e.items() if k not in ("event", "ts")})
            a["started"] = e.get("ts", now)
        elif e.get("event") == "end":
            a["ended"] = e.get("ts", now)
            a["result"] = e.get("status")
            if e.get("out"):
                a["out"] = e["out"]

    out = []
    for a in agents.values():
        if "started" not in a:
            continue
        model = a.get("model", "")
        if "ended" in a:
            state = "done" if a.get("result") == "ok" else "failed"
        elif alive(a.get("pid", 0)):
            state = "running"
        else:
            state = "interrupted"
        a.update(
            state=state,
            model_name=display(model, names),
            role_label=ROLE_LABELS.get(a.get("role", ""), a.get("role", "")),
            route=route_of(model, a.get("via")),
            cn=is_cn(model),
            elapsed=(a.get("ended") or now) - a["started"],
        )
        out.append(a)
    out.sort(key=lambda a: a["started"], reverse=True)
    return out
