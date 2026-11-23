import sqlite3
import unittest
from pathlib import Path

from helpers import Repo, make_t3_db

from conflict_guard.models import display, is_cn, load_names, route_of
from conflict_guard.t3 import t3_threads


class T3ReaderTest(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.names = load_names()

    def tearDown(self):
        self.repo.cleanup()

    def test_reads_threads_of_matching_project(self):
        db = make_t3_db(str(Path(self.repo.dir, "t3.sqlite")), self.repo.path, [
            {"id": "t1", "title": "主控", "model": "claude-opus-5-5"},
            {"id": "t2", "title": "后端", "model": "minimax-cn/MiniMax-M3", "status": "completed", "completed_at": "x"},
        ])
        threads, err = t3_threads(self.repo.path, self.names, Path(db))
        self.assertIsNone(err)
        by_id = {t["id"]: t for t in threads}
        self.assertEqual(by_id["t1"]["model_name"], "Claude Opus 5.5")
        self.assertTrue(by_id["t1"]["active"])
        self.assertFalse(by_id["t2"]["active"])
        self.assertTrue(by_id["t2"]["cn"])
        self.assertEqual(by_id["t1"]["steps"][0]["title"], "Ran tests")

    def test_missing_database_is_reported_not_raised(self):
        threads, err = t3_threads(self.repo.path, self.names, Path("/nonexistent/x.sqlite"))
        self.assertEqual(threads, [])
        self.assertIn("没有找到", err)

    def test_unknown_project(self):
        db = make_t3_db(str(Path(self.repo.dir, "t3.sqlite")), "/some/other/project", [{"id": "t1"}])
        threads, err = t3_threads(self.repo.path, self.names, Path(db))
        self.assertEqual(threads, [])
        self.assertIn("还没有添加", err)

    def test_schema_change_degrades_gracefully(self):
        db = str(Path(self.repo.dir, "t3.sqlite"))
        con = sqlite3.connect(db)
        con.execute("create table something_else (x)")
        con.commit()
        con.close()
        threads, err = t3_threads(self.repo.path, self.names, Path(db))
        self.assertEqual(threads, [])
        self.assertIn("读取 T3 数据失败", err)


class ModelsTest(unittest.TestCase):
    def test_routes(self):
        self.assertEqual(route_of("agy:gemini-4-neon-high")[-2:], ["Antigravity 命令行", "gemini-4-neon-high"])
        self.assertEqual(route_of("minimax-cn/MiniMax-M3")[-2:], ["MiniMax (China)", "MiniMax-M3"])
        self.assertEqual(route_of("gpt-6.2-sol")[-2:], ["OpenAI", "gpt-6.2-sol"])
        self.assertEqual(route_of("auto/kimi-k3.1-pro", "review.sh")[1], "review.sh")

    def test_display_and_domestic_flag(self):
        names = load_names()
        self.assertEqual(display("agy:gemini-4-neon-high", names), "Gemini 4 Neon (High)")
        self.assertEqual(display("some/unknown", names), "some/unknown")
        self.assertTrue(is_cn("auto/deepseek-v4.1-flash"))
        self.assertFalse(is_cn("gpt-6.2-astra"))


if __name__ == "__main__":
    unittest.main()
