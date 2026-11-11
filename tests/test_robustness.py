"""ทดสอบ offline (ไม่ต่อเน็ต ไม่ใช้ key ไม่ส่งคำสั่ง): robustness.py"""
import os, sys, shutil, tempfile, unittest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import common, scanstrat as SC, robustness as RB
from test_shadow import synth_days, G2, CH, cand, DATES


class TestRobust(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self._old = common.DATA; common.DATA = self.tmp
        common.save_json("population_scan.json", {"champion": cand(0, CH), "candidates": [], "runs": [{"split": DATES[1]}]})
        common.save_json("scan_shadow.json", {"shadow": [cand(1, G2)]})
        common.save_json("universe.json", {"symbols": [], "no_short": []})
        self.days = {s: {d: SC.compact(b) for d, b in dd.items()} for s, dd in synth_days(n_sym=40).items()}
    def tearDown(self):
        common.DATA = self._old; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_slippage_monotonic_and_report(self):
        out = RB.run(self.days, DATES[-1], log=lambda *a: None)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "robustness.json")))
        self.assertEqual([r["role"] for r in out["rules"]], ["champion", "shadow"])
        for r in out["rules"]:
            av = [x["avgR"] for x in r["rows"]]
            self.assertTrue(all(a >= b - 1e-12 for a, b in zip(av, av[1:])), av)   # slip สูงขึ้น → avgR ไม่เพิ่ม
            self.assertGreater(r["rows"][0]["n"], 0)

    def test_daily_t(self):
        tr = [{"sig": "d1", "R": 1.0}, {"sig": "d1", "R": 1.0}, {"sig": "d2", "R": -1.0}, {"sig": "d3", "R": 0.5}]
        d = RB.daily_t(tr)
        self.assertEqual(d["days"], 3); self.assertAlmostEqual(d["avgR_day"], 0.5)
        self.assertAlmostEqual(d["t_day"], 0.5 / 1.5 * 3 ** 0.5)

    def test_breakeven_brackets_zero(self):
        P = common.load_json("population_scan.json", {}); g = P["champion"]["g"]
        panel = SC.build_panel(self.days, 5.0)
        be = RB.breakeven(g, panel, DATES[1], set())
        if be is not None and be < 0.02:
            import strategy as S
            f = lambda s: S.metrics(SC.backtest(g, panel, start=DATES[1], slip=s))["avgR"]
            self.assertGreater(f(be * 0.9), -1e-9); self.assertLess(f(be * 1.1), 1e-9)


if __name__ == "__main__":
    unittest.main()
