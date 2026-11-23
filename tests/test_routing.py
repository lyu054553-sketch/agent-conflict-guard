import io
import json
import unittest

from helpers import BASE_CALC, Repo

from conflict_guard import routing, store


class FakeStdin(io.StringIO):
    def isatty(self):
        return False


def run_hook(cwd, event="PostToolUse"):
    out = io.StringIO()
    routing.hook(stdin=FakeStdin(json.dumps({"hook_event_name": event, "cwd": cwd})), stdout=out)
    text = out.getvalue().strip()
    return json.loads(text) if text else None


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write("calc.py", BASE_CALC)
        self.repo.commit("init")

    def tearDown(self):
        self.repo.cleanup()

    def make_conflict(self):
        for name, new in (("agent/a", "a + b + 0"), ("agent/b", "b + a")):
            wt = self.repo.worktree(name)
            self.repo.write("calc.py", BASE_CALC.replace("a + b", new), cwd=wt)
            self.repo.commit(cwd=wt)

    def test_store_forgets_resolved_conflicts_so_they_alert_again(self):
        root = self.repo.path
        self.assertEqual(store.take_new(root, ["x", "y"], "hook"), ["x", "y"])
        self.assertEqual(store.take_new(root, ["x", "y"], "hook"), [])
        self.assertEqual(store.take_new(root, ["y"], "hook"), [])
        self.assertEqual(store.take_new(root, ["x", "y"], "hook"), ["x"])

    def test_channels_are_independent(self):
        root = self.repo.path
        store.take_new(root, ["x"], "hook")
        self.assertEqual(store.take_new(root, ["x"], "t3"), ["x"])

    def test_hook_injects_alert_once(self):
        self.make_conflict()
        first = run_hook(self.repo.path, "UserPromptSubmit")
        self.assertIsNotNone(first)
        out = first["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "UserPromptSubmit")
        self.assertTrue(out["additionalContext"].startswith("【冲突监控】发现 1 个新的冲突风险"))
        self.assertIn("calc.py", out["additionalContext"])
        self.assertIsNone(run_hook(self.repo.path))

    def test_hook_is_silent_without_conflicts(self):
        self.assertIsNone(run_hook(self.repo.path))

    def test_hook_never_raises(self):
        out = io.StringIO()
        routing.hook(stdin=FakeStdin("not json"), stdout=out)
        routing.hook(stdin=FakeStdin(json.dumps({"cwd": "/"})), stdout=out)
        self.assertEqual(out.getvalue(), "")

    def test_dashboard_marks_routed_conflicts(self):
        from conflict_guard.detect import collect
        self.make_conflict()
        self.assertIsNone(collect(self.repo.path)["conflicts"][0]["routed_at"])
        run_hook(self.repo.path)
        self.assertIsNotNone(collect(self.repo.path)["conflicts"][0]["routed_at"])

    def test_watch_sends_new_conflicts_to_t3_thread(self):
        self.make_conflict()
        sent = []
        sender = lambda tid, text: sent.append((tid, text)) or True  # noqa: E731
        routing.watch(self.repo.path, "thread-1", once=True, sender=sender)
        routing.watch(self.repo.path, "thread-1", once=True, sender=sender)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], "thread-1")

    def test_watch_retries_after_failed_delivery(self):
        self.make_conflict()
        calls = []

        def flaky(tid, text):
            calls.append(text)
            return len(calls) > 1

        routing.watch(self.repo.path, "thread-1", once=True, sender=flaky)
        routing.watch(self.repo.path, "thread-1", once=True, sender=flaky)
        routing.watch(self.repo.path, "thread-1", once=True, sender=flaky)
        self.assertEqual(len(calls), 2)

    def test_send_to_t3_uses_thread_send_with_stdin(self):
        seen = {}

        class Result:
            returncode = 0

        def runner(cmd, **kw):
            seen["cmd"], seen["input"] = cmd, kw.get("input")
            return Result()

        self.assertTrue(routing.send_to_t3("abc", "hello", binary="/bin/t3", runner=runner))
        self.assertEqual(seen["cmd"], ["/bin/t3", "thread", "send", "abc", "-"])
        self.assertEqual(seen["input"], "hello")


if __name__ == "__main__":
    unittest.main()
