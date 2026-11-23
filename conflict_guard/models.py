"""Model names, roles and request routes, for display."""
from __future__ import annotations

import json
import os
from pathlib import Path

ROLE_LABELS = {
    "plan": "独立出方案",
    "ux": "审交互",
    "copy-cn": "审中文文案",
    "backend-hard": "写难的后端",
    "backend-easy": "写成块的后端",
    "chores": "杂活",
    "review-pre": "预审",
    "review-final": "终审",
}

DISPLAY = {
    "claude-opus-5-5": "Claude Opus 5.5",
    "agy:gemini-4-neon-high": "Gemini 4 Neon (High)",
    "gemini-4-neon-high": "Gemini 4 Neon (High)",
    "auto/kimi-k3.1-pro": "Kimi K3.1 Pro",
    "gpt-6.2-astra": "GPT-6.2-Astra",
    "gpt-6.2-sol": "GPT-6.2-Sol",
    "minimax-cn/MiniMax-M3": "MiniMax-M3",
    "minimax-cn/MiniMax-M3.1-Flash": "MiniMax-M3.1-Flash",
    "auto/deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
}

ROUTE_PREFIX = {
    "auto": "magpie 自动路由组",
    "group": "magpie 分流组",
    "minimax-cn": "MiniMax (China)",
}

CN_HINTS = ("kimi", "minimax", "deepseek", "glm", "qwen", "step", "mimo")


def catalog_path() -> Path:
    return Path(os.environ.get("ACG_MODEL_CATALOG", Path.home() / ".codex" / "magpie-desktop-models.json"))


def load_names() -> dict[str, str]:
    """Built-in names, extended with display names from the local Codex model catalog if present."""
    names = dict(DISPLAY)
    try:
        data = json.loads(catalog_path().read_text())
        items = data.get("models", data) if isinstance(data, dict) else data
        for m in items:
            if isinstance(m, dict):
                slug = m.get("slug") or m.get("id")
                label = (m.get("display_name") or "").split(" · ")[0]
                if slug and label:
                    names.setdefault(slug, label)
    except Exception:
        pass
    return names


def display(model: str | None, names: dict[str, str]) -> str:
    if not model:
        return "未知模型"
    return names.get(model) or names.get(model.removeprefix("agy:")) or model


def is_cn(model: str | None) -> bool:
    m = (model or "").lower()
    return any(h in m for h in CN_HINTS)


def route_of(model: str, via: str | None = None) -> list[str]:
    """The hops a request takes from the orchestrator to the model."""
    if model.startswith("agy:"):
        return ["Claude 主控", via or "ask.sh", "Antigravity 命令行", model[4:]]
    hops = ["Claude 主控", via or "ask.sh", "Codex 命令行", "magpie 本地网关"]
    if "/" in model:
        prefix, rest = model.split("/", 1)
        return hops + [ROUTE_PREFIX.get(prefix, prefix), rest]
    return hops + ["OpenAI", model]
