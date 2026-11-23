import unittest
from pathlib import Path

from helpers import BASE_CALC, Repo

from conflict_guard import gitstate


class GitStateTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.repo.write("calc.py", BASE_CALC)
        self.repo.write("util.py", "X = 1\n")
        self.repo.commit("init")

    def tearDown(self):
        self.repo.cleanup()

    def test_status_files_lists_modified_and_untracked_but_not_agents_dir(self):
        self.repo.write("calc.py", BASE_CALC + "\n# edit\n")
        self.repo.write("new_module.py", "Y = 2\n")
        self.repo.write(".agents/out/log.md", "ignored\n")
        self.assertEqual(sorted(gitstate.status_files(self.repo.path)), ["calc.py", "new_module.py"])

    def test_branch_files_lists_committed_changes_since_fork(self):
        wt = self.repo.worktree("agent/a")
        self.repo.write("util.py", "X = 2\n", cwd=wt)
        self.repo.commit(cwd=wt)
        self.assertEqual(gitstate.branch_files(self.repo.path, "agent/a"), ["util.py"])

    def test_merge_conflicts_reports_same_line_edits(self):
        a, b = self.repo.worktree("agent/a"), self.repo.worktree("agent/b")
        self.repo.write("calc.py", BASE_CALC.replace("a + b", "a + b + 0"), cwd=a)
        self.repo.commit(cwd=a)
        self.repo.write("calc.py", BASE_CALC.replace("a + b", "b + a"), cwd=b)
        self.repo.commit(cwd=b)
        self.assertEqual(gitstate.merge_conflicts(self.repo.path, "agent/a", "agent/b"), ["calc.py"])

    def test_merge_conflicts_is_empty_for_edits_in_different_regions(self):
        a, b = self.repo.worktree("agent/a"), self.repo.worktree("agent/b")
        self.repo.write("calc.py", BASE_CALC.replace("a + b", "a + b + 0"), cwd=a)
        self.repo.commit(cwd=a)
        self.repo.write("calc.py", BASE_CALC.replace("return -a", "return 0 - a"), cwd=b)
        self.repo.commit(cwd=b)
        self.assertEqual(gitstate.merge_conflicts(self.repo.path, "agent/a", "agent/b"), [])

    def test_merge_simulation_does_not_touch_any_checkout(self):
        a = self.repo.worktree("agent/a")
        self.repo.write("calc.py", "changed\n", cwd=a)
        self.repo.commit(cwd=a)
        head_before = self.repo.git("rev-parse", "HEAD")
        gitstate.merge_conflicts(self.repo.path, "HEAD", "agent/a")
        self.assertEqual(self.repo.git("rev-parse", "HEAD"), head_before)
        self.assertEqual(gitstate.status_files(self.repo.path), [])

    def test_list_worktrees_excludes_main_checkout(self):
        wt = self.repo.worktree("agent/a")
        found = gitstate.list_worktrees(self.repo.path)
        self.assertEqual([(Path(w["path"]).resolve(), w["branch"]) for w in found], [(Path(wt).resolve(), "agent/a")])

    def test_main_root_from_inside_a_worktree(self):
        wt = self.repo.worktree("agent/a")
        self.assertEqual(Path(gitstate.main_root(wt)).resolve(), Path(self.repo.path).resolve())

    def test_main_root_outside_git_is_none(self):
        self.assertIsNone(gitstate.main_root("/"))


if __name__ == "__main__":
    unittest.main()
