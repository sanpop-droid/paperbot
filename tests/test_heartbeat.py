"""heartbeat/coverage (postclose-risk/lead, preopen-lead, postclose-fa, preopen-news) — offline ไม่ใช้ key"""
import os, sys, shutil, tempfile, unittest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import common, scanstrat as SC, office_report as OR
from test_shadow import synth_days, CH, cand, FakeBroker, TODAY


class TestScanLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self._old = common.DATA; common.DATA = self.tmp
        common.save_json("population_scan.json", {"champion": {**cand(0, CH), "probation": True}, "candidates": [], "runs": []})
        self.days = synth_days(); common.save_json("universe.json", {"symbols": sorted(self.days), "no_short": []})
        common.save_json("scan_shadow.json", {"shadow": []})
        import dt as D; self.D = D; self.logs = []; D.log = self.logs.append
        cfg = common.config(); cfg["symbols"] = ["AAPL"]; D.config = lambda: cfg
    def tearDown(self):
        common.DATA = self._old; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missed_window_is_recorded_once(self):
        b = FakeBroker()
        self.D.run(b, lambda U, t: self.days, force_minute=CH["M"] + 75)
        self.D.run(b, lambda U, t: self.days, force_minute=CH["M"] + 80)
        st = common.load_json("dt_state.json", {})
        self.assertEqual(st["scan_log"][TODAY]["status"], "missed")
        self.assertEqual(sum("ข้ามสแกน" in l for l in self.logs), 1)
        self.assertEqual(b.submitted, [])

    def test_scanned_has_context(self):
        self.D.run(FakeBroker(), lambda U, t: self.days, force_minute=CH["M"])
        r = common.load_json("dt_state.json", {})["scan_log"][TODAY]
        self.assertEqual(r["status"], "scanned"); self.assertGreater(r["n"], 0); self.assertIn("gap_med_pct", r)


class TestCoverage(unittest.TestCase):
    def test_counts(self):
        log = {"2026-11-09": {"status": "missed"}, "2026-11-10": {"status": "missed"}, "2026-11-11": {"status": "scanned"},
               "2026-11-13": {"status": "scanned"}}
        c = OR.coverage(log, "2026-11-16")   # จ.–ศ. 9–13 + จ. 16 (วันนี้ยังไม่นับ no_run)
        self.assertEqual((c["scanned"], c["missed"], c["no_run"]), (2, 2, 1))   # 12 พ.ย. ไม่มีรัน
        self.assertEqual(c["pct"], 40.0)
        self.assertIsNone(OR.coverage({}, "2026-11-16"))


if __name__ == "__main__":
    unittest.main()
