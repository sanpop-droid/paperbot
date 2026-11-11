"""ทดสอบ offline (ไม่ต่อเน็ต ไม่ใช้ key ไม่ส่งคำสั่ง): research.py"""
import os, sys, shutil, tempfile, unittest, random
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import common, scanstrat as SC, research as RS
from test_shadow import synth_days, G2, CH, cand, DATES


class TestReversal(unittest.TestCase):
    def setUp(self):
        self.days = {s: {d: SC.compact(b) for d, b in dd.items()} for s, dd in synth_days(n_sym=40).items()}
        self.panel = SC.build_panel(self.days, 5.0)

    def test_rank_rev_picks_losers_for_long(self):
        g = dict(mode="rev-both", M=30, th=0.0, k_stop=1.0, R=1.0, K=3)
        for d, infos in self.panel.items():
            out = RS.rank_rev(g, infos)
            L = [s for s, x, di in out if di == 1]; Sh = [s for s, x, di in out if di == -1]
            self.assertTrue(all(v <= 0 for v in L)); self.assertTrue(all(v >= 0 for v in Sh))
            self.assertEqual(L, sorted(L)); self.assertEqual(Sh, sorted(Sh, reverse=True))

    def test_backtest_rev_r_sign(self):
        g = dict(mode="rev-both", M=30, th=0.0, k_stop=1.0, R=1.0, K=3)
        tr = RS.backtest_rev(g, self.panel, slip=0.0)
        self.assertGreater(len(tr), 0)
        for t in tr:
            self.assertTrue(-5 < t["R"] < 5)
            if t["how"] == "target": self.assertAlmostEqual(t["R"], 1.0, places=6)
            if t["how"] == "stop" and abs(t["R"] + 1) > 1e-9: self.assertLess(t["R"], -1)   # gap ทะลุ stop เสียเกิน 1R

    def test_grid_size(self):
        self.assertEqual(len(RS.GRID), 108)


class TestStats(unittest.TestCase):
    def test_pbo_noise_vs_edge(self):
        rng = random.Random(1); T = 400
        noise = [[rng.gauss(0, 1) for _ in range(T)] for _ in range(20)]
        p = RS.pbo_cscv(noise, max_combos=600)["pbo"]; self.assertTrue(0.2 < p < 0.8, p)
        edge = [[rng.gauss(0.6, 1) for _ in range(T)]] + [[rng.gauss(0, 1) for _ in range(T)] for _ in range(19)]
        self.assertLess(RS.pbo_cscv(edge, max_combos=600)["pbo"], 0.1)

    def test_dsr(self):
        rng = random.Random(2)
        good = [rng.gauss(0.3, 1) for _ in range(500)]
        self.assertGreater(RS.dsr(good, 2, 0.01)["dsr"], 0.95)
        noise = [rng.gauss(0.0, 1) for _ in range(150)]
        self.assertLess(RS.dsr(noise, 4716, 0.01)["dsr"], 0.5)
        self.assertIsNone(RS.dsr([1.0] * 5, 10, 0.1))


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self._old = common.DATA; common.DATA = self.tmp
        common.save_json("population_scan.json", {"champion": cand(0, CH), "candidates": [cand(1, G2)], "runs": [{"split": DATES[3]}], "n_tested_total": 100})
        common.save_json("universe.json", {"symbols": [], "no_short": []})
        self.days = {s: {d: SC.compact(b) for d, b in dd.items()} for s, dd in synth_days(n_sym=40).items()}
        self._pc = RS.part_c; RS.part_c = lambda: {"note": "stub (offline)"}
    def tearDown(self):
        RS.part_c = self._pc; common.DATA = self._old; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_writes_report(self):
        out = RS.run(self.days, DATES[-1], log=lambda *a: None)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "research.json")))
        self.assertEqual(out["reversal"]["grid_n"], 108)
        self.assertIn("champion_holdout", out["reversal"]); self.assertIn("selection_bias", out)


if __name__ == "__main__":
    unittest.main()
