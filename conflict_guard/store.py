"""Which conflicts have already been routed to the orchestrator, per delivery channel."""
from __future__ import annotations

import json
import time
from pathlib import Path


def store_path(root: str, channel: str) -> Path:
    return Path(root) / ".agents" / "state" / f"notified-{channel}.json"


def load(root: str, channel: str) -> dict[str, float]:
    try:
        return json.loads(store_path(root, channel).read_text())
    except Exception:
        return {}


def take_new(root: str, fingerprints: list[str], channel: str, now: float | None = None) -> list[str]:
    """Return fingerprints not yet delivered on `channel`, and remember the current set.

    Fingerprints that are no longer present are forgotten, so a conflict that is resolved
    and later comes back is delivered again.
    """
    now = time.time() if now is None else now
    seen = load(root, channel)
    new = [f for f in fingerprints if f not in seen]
    keep = {f: seen.get(f, now) for f in fingerprints}
    p = store_path(root, channel)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(keep))
    return new


def routed_times(root: str) -> dict[str, float]:
    """Earliest delivery time of each fingerprint across all channels."""
    out: dict[str, float] = {}
    d = Path(root) / ".agents" / "state"
    if not d.exists():
        return out
    for f in d.glob("notified-*.json"):
        try:
            for k, v in json.loads(f.read_text()).items():
                out[k] = min(v, out.get(k, v))
        except Exception:
            continue
    return out
