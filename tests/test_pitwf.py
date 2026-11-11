"""ทดสอบ offline (ไม่ต่อเน็ต ไม่ใช้ key ไม่ส่งคำสั่ง): pitwf.py"""
import os, sys, shutil, tempfile, unittest, random, datetime as dt
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import common, scanstrat as SC, pitwf as PW


def dates(n):
    d, out = dt.date(2025, 1, 6), []
    while len(out) < n:
        if d.weekday() < 5: out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


class TestPitUniverse(unittest.TestCase):
    def test_no_lookahead(self):
        D = dates(40)
        dv = {"A": {d: 100.0 for d in D}, "B": {d: (1.0 if d < D[30] else 1e9) for d in D}, "C": {d: 50.0 for d in D}}
        closes = {s: {d: 10.0 for d in D} for s in dv}
        U = PW.pit_universe(dv, closes, D, top=2, lookback=5)
        self.assertEqual(U[D[30]], {"A", "C"})          # วันที่ B เริ่มดัง ยังไม่ควรรู้
        self.assertIn("B", U[D[33]])                     # หลังมีข้อมูลก่อนหน้าแล้วจึงเข้า
        self.assertEqual(U[D[2]], set())                 # ข้อมูลก่อนหน้าน้อยกว่า 5 วัน = ว่าง

    def test_min_price(self):
        D = dates(12)
        dv = {"A": {d: 100.0 for d in D}, "P": {d: 1e9 for d in D}}
        closes = {"A": {d: 10.0 for d in D}, "P": {d: 1.0 for d in D}}
        self.assertNotIn("P", PW.pit_universe(dv, closes, D, top=2, lookback=5)[D[-1]])


class TestRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self._old = common.DATA; common.DATA = self.tmp
        common.save_json("universe.json", {"symbols": [], "no_short": []})
        rng = random.Random(3); D = dates(260); self.days, self.dv, self.closes = {}, {}, {}
        for k in range(16):
            s = f"S{k}"; px = 20.0 + k; dd = {}
            for d in D:
                bars = []; o = px * (1 + rng.gauss(0, 0.02))
                for m in range(0, 390, 5):
                    c = o * (1 + rng.gauss(0, 0.003)); bars.append((m, o, max(o, c) * 1.001, min(o, c) * 0.999, c, 1000 + k * 100)); o = c
                dd[d] = bars; px = o
            self.dv[s] = {d: sum(b[4] * b[5] for b in bb) for d, bb in dd.items()}
            self.closes[s] = {d: bb[-1][4] for d, bb in dd.items()}
            self.days[s] = {d: SC.compact(b) for d, b in dd.items()}
    def tearDown(self):
        common.DATA = self._old; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_run_writes_report(self):
        out = PW.run(self.days, self.dv, self.closes, [f"S{k}" for k in range(8)], "2026-11-12", seed=1, log=lambda *a: None, folds=2)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "pitwf.json")))
        for k in ("current", "pit", "verdict", "overlap_pit_vs_current"): self.assertIn(k, out)
        self.assertGreaterEqual(out["pit"]["n"], 0)


if __name__ == "__main__":
    unittest.main()
