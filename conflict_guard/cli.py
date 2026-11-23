"""Command line: acg serve | check | hook | watch | log."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .detect import collect
from .events import append_event
from .gitstate import main_root


def _root() -> str:
    root = main_root()
    if not root:
        sys.exit("不在 git 仓库里。请在项目目录里运行。")
    return root


def cmd_serve(args):
    from .server import serve
    serve(_root(), args.port)


def cmd_check(args):
    state = collect(_root())
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return
    print(f"项目 {state['project']}（{state['branch']}） 主控：{state['orchestrator']['model_name']}")
    running = [a for a in state["agents"] if a["state"] == "running"]
    print(f"\n正在干活：{len(running)} 个")
    for a in running:
        print(f"  · {a['model_name']} · {a['role_label']}  {int(a['elapsed'])}s  路由：{' → '.join(a['route'])}")
        if a.get("files"):
            print(f"    在改：{', '.join(a['files'][:8])}")
    active = [t for t in state["t3"] if t["active"]]
    note = f"（{state['t3_error']}）" if state["t3_error"] else ""
    print(f"\nT3 会话：{len(state['t3'])} 个，其中 {len(active)} 个在运行{note}")
    for t in active:
        print(f"  · 「{t['title']}」 {t['model_name']}  {t['status']}  {t['cwd']}")
    print(f"\n冲突风险：{len(state['conflicts'])} 个")
    for c in state["conflicts"]:
        print(f"  [{c['level']}] {c['kind']}：{c['title']}")
        print(f"      文件：{', '.join(c['files'][:8])}")
        print(f"      建议：{c['suggestion']}")
    if not state["conflicts"]:
        print("  没有发现冲突。")
    if args.strict and any(c["level"] == "high" for c in state["conflicts"]):
        sys.exit(1)


def cmd_hook(args):
    from .routing import hook
    hook()


def cmd_watch(args):
    from .routing import watch
    watch(_root(), args.t3_thread, args.interval, once=args.once)


def cmd_log(args):
    root = args.root or main_root()
    if not root:
        return
    rec = {k: v for k, v in vars(args).items() if k not in ("func", "root", "cmd", "kind") and v is not None}
    rec["event"] = args.kind
    append_event(root, rec)


def main(argv=None):
    p = argparse.ArgumentParser(prog="acg", description="并行 AI agent 的冲突检测与实时监控")
    p.add_argument("--version", action="version", version=f"agent-conflict-guard {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="打开实时监控页面")
    s.add_argument("--port", type=int, default=4317)
    s.set_defaults(func=cmd_serve)

    c = sub.add_parser("check", help="在终端打印当前状态和冲突")
    c.add_argument("--json", action="store_true", help="输出完整 JSON")
    c.add_argument("--strict", action="store_true", help="有高风险冲突时以退出码 1 结束（适合放进 CI 或合并前检查）")
    c.set_defaults(func=cmd_check)

    h = sub.add_parser("hook", help="Claude Code 钩子：有新冲突时注入主控上下文")
    h.set_defaults(func=cmd_hook)

    w = sub.add_parser("watch", help="持续检查，把新冲突发进 T3 Code 的主控会话")
    w.add_argument("--t3-thread", required=True, help="主控所在的 T3 会话 id")
    w.add_argument("--interval", type=float, default=5.0)
    w.add_argument("--once", action="store_true", help="只检查一次")
    w.set_defaults(func=cmd_watch)

    lg = sub.add_parser("log", help="（派活脚本内部用）记录一条事件")
    lg.add_argument("kind", choices=["start", "end"])
    for f in ("id", "role", "model", "mode", "task", "title", "branch", "worktree", "via", "status", "out", "root"):
        lg.add_argument(f"--{f}")
    lg.add_argument("--pid", type=int)
    lg.set_defaults(func=cmd_log)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
