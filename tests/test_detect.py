import time
import unittest
from pathlib import Path

from helpers import BASE_CALC, Repo, make_t3_db

from conflict_guard.detect import collect

ALIVE = lambda pid: True  # noqa: E731
DEAD = lambda pid: False  # noqa: E731


def kinds(state):
    return sorted((c["level"], c["kind"]) for c in state["conflicts"])


class DetectTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write("calc.py", BASE_CALC)
        self.repo.write("util.py", "X = 1\n")
        self.repo.commit("init")

    def tearDown(self):
        self.repo.cleanup()

    def branch(self, name, path, text, commit=True):
        wt = self.repo.worktree(name)
        self.repo.write(path, text, cwd=wt)
        if commit:
            self.repo.commit(cwd=wt)
        return wt

    def start(self, aid, wt, branch, task=None, mode="write"):
        self.repo.event(event="start", id=aid, role="backend-easy", model="minimax-cn/MiniMax-M3",
                        mode=mode, worktree=wt, branch=branch, task=task, pid=1, ts=time.time())

    def test_disjoint_files_report_nothing(self):
        self.branch("agent/a", "calc.py", BASE_CALC + "\n\ndef sub(a, b):\n    return a - b\n")
        self.branch("agent/b", "util.py", "X = 2\n")
        self.assertEqual(collect(self.repo.path, alive=DEAD)["conflicts"], [])

    def test_certain_merge_conflict_is_high_and_replaces_overlap_warning(self):
        self.branch("agent/a", "calc.py", BASE_CALC.replace("a + b", "a + b + 0"))
        self.branch("agent/b", "calc.py", BASE_CALC.replace("a + b", "b + a"))
        state = collect(self.repo.path, alive=DEAD)
        self.assertEqual(kinds(state), [("high", "合并会冲突")])
        self.assertEqual(state["conflicts"][0]["files"], ["calc.py"])

    def test_same_file_clean_merge_is_overlap_only(self):
        self.branch("agent/a", "calc.py", BASE_CALC.replace("a + b", "a + b + 0"))
        self.branch("agent/b", "calc.py", BASE_CALC.replace("return -a", "return 0 - a"))
        self.assertEqual(kinds(collect(self.repo.path, alive=DEAD)), [("medium", "同一文件多方在改")])

    def test_overlap_between_two_live_agents_is_high(self):
        wa = self.branch("agent/a", "calc.py", BASE_CALC + "# a\n", commit=False)
        wb = self.branch("agent/b", "calc.py", BASE_CALC + "# b\n", commit=False)
        self.start("a", wa, "agent/a")
        self.start("b", wb, "agent/b")
        state = collect(self.repo.path, alive=ALIVE)
        self.assertIn(("high", "同一文件多方在改"), kinds(state))
        running = {a["id"]: a for a in state["agents"]}
        self.assertEqual(running["a"]["files"], ["calc.py"])
        self.assertEqual(running["a"]["state"], "running")

    def test_uncommitted_main_edit_overlapping_a_branch(self):
        self.branch("agent/a", "calc.py", BASE_CALC.replace("return -a", "return 0 - a"))
        self.repo.write("calc.py", BASE_CALC + "\n# orchestrator edit\n")
        state = collect(self.repo.path, alive=DEAD)
        overlap = [c for c in state["conflicts"] if c["kind"] == "同一文件多方在改"]
        self.assertEqual(len(overlap), 1)
        self.assertIn("主工作区", overlap[0]["who"])

    def test_branch_conflicting_with_head_after_main_moves(self):
        self.branch("agent/a", "calc.py", BASE_CALC.replace("a + b", "a + b + 0"))
        self.repo.write("calc.py", BASE_CALC.replace("a + b", "b + a"))
        self.repo.commit("main moved")
        state = collect(self.repo.path, alive=DEAD)
        self.assertEqual(state["conflicts"][0]["kind"], "合并会冲突")
        self.assertIn("main", state["conflicts"][0]["who"])

    def test_overlapping_task_scopes_of_live_writers(self):
        for name in ("a", "b"):
            self.repo.write(f".agents/tasks/{name}.md", f"# task {name}\nOnly change src/api/orders.py\n")
        wa, wb = self.repo.worktree("agent/a"), self.repo.worktree("agent/b")
        self.start("a", wa, "agent/a", task=".agents/tasks/a.md")
        self.start("b", wb, "agent/b", task=".agents/tasks/b.md")
        state = collect(self.repo.path, alive=ALIVE)
        scope = [c for c in state["conflicts"] if c["kind"] == "派活范围重叠"]
        self.assertEqual(len(scope), 1)
        self.assertEqual(scope[0]["files"], ["src/api/orders.py"])

    def test_agent_that_died_without_end_event_is_low(self):
        wa = self.repo.worktree("agent/a")
        self.start("a", wa, "agent/a")
        state = collect(self.repo.path, alive=DEAD)
        self.assertEqual(kinds(state), [("low", "派活中断")])
        self.assertEqual(state["agents"][0]["state"], "interrupted")

    def test_finished_agent_is_not_running(self):
        wa = self.repo.worktree("agent/a")
        self.start("a", wa, "agent/a")
        self.repo.event(event="end", id="a", status="ok", ts=time.time())
        state = collect(self.repo.path, alive=DEAD)
        self.assertEqual(state["agents"][0]["state"], "done")
        self.assertEqual(state["conflicts"], [])

    def test_two_live_t3_threads_in_same_directory(self):
        db = make_t3_db(str(Path(self.repo.dir, "t3.sqlite")), self.repo.path, [
            {"id": "t1", "title": "写接口", "model": "gpt-6.2-astra"},
            {"id": "t2", "title": "改页面", "model": "auto/kimi-k3.1-pro"},
        ])
        state = collect(self.repo.path, t3_db=Path(db), alive=DEAD)
        self.assertEqual(kinds(state), [("high", "同一目录并行")])

    def test_t3_threads_in_separate_worktrees_do_not_clash(self):
        wt = self.repo.worktree("t3/feature")
        db = make_t3_db(str(Path(self.repo.dir, "t3.sqlite")), self.repo.path, [
            {"id": "t1", "title": "写接口"},
            {"id": "t2", "title": "改页面", "worktree": wt, "cwd": wt},
        ])
        state = collect(self.repo.path, t3_db=Path(db), alive=DEAD)
        self.assertEqual(state["conflicts"], [])
        labels = [c["label"] for c in state["changesets"]]
        self.assertTrue(any("T3 会话「改页面」" in l for l in labels))

    def test_fingerprints_are_stable_across_runs(self):
        self.branch("agent/a", "calc.py", BASE_CALC.replace("a + b", "a + b + 0"))
        self.branch("agent/b", "calc.py", BASE_CALC.replace("a + b", "b + a"))
        first = [c["fp"] for c in collect(self.repo.path, alive=DEAD)["conflicts"]]
        second = [c["fp"] for c in collect(self.repo.path, alive=DEAD)["conflicts"]]
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
