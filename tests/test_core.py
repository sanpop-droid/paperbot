"""ponytail-6: test หัวใจของ scanner (rank / simulate) และ dt.reconcile — offline ไม่ใช้ key ไม่ส่งคำสั่ง"""
import os, sys, unittest
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import scanstrat as SC
import dt as DT


def info(sym, pc, open_, at30):
    """แท่ง 5 นาที 0..85 · ราคาเดินจาก open_ ไป at30 ตอนนาที 30 แล้วนิ่ง"""
    bars = []
    for m in range(0, 90, 5):
        c = open_ + (at30 - open_) * min(1, (m + 5) / 30)
        bars.append((m, c, c * 1.001, c * 0.999, c, 1000))
    bars[0] = (0, open_, open_ * 1.001, open_ * 0.999, bars[0][4], 1000)
    return SC.Info(sym, bars, pc)


G = {"M": 30, "K": 2, "pc": 1, "side": 2, "th": 0.03, "gap_lo": -0.1, "gap_hi": 0.1, "k_stop": 1.0, "R": 1.0}


class TestRank(unittest.TestCase):
    def setUp(self):
        self.xs = [info("UP5", 100, 101, 105), info("UP4", 100, 100, 104), info("UP2", 100, 100, 102), info("UP9", 100, 100, 109),
                   info("DN6", 100, 99, 94), info("DN4", 100, 100, 96), info("DN1", 100, 100, 99)]

    def test_threshold_k_and_order(self):
        out = SC.rank(SC.fix(dict(G)), self.xs)
        L = [x.sym for s, x, d in out if d == 1]; S = [x.sym for s, x, d in out if d == -1]
        self.assertEqual(L, ["UP9", "UP5"])            # K=2 แรงสุดก่อน · UP2 ไม่ถึง th
        self.assertEqual(S, ["DN6", "DN4"])            # DN1 ไม่ถึง th

    def test_no_short_and_gap_filter(self):
        out = SC.rank(SC.fix(dict(G)), self.xs, no_short={"DN6"})
        self.assertNotIn("DN6", [x.sym for s, x, d in out if d == -1])
        g = SC.fix(dict(G, gap_lo=0.0, gap_hi=0.005))   # long รับ gap 0..+0.5% · short รับ −0.5..0%
        out = SC.rank(g, self.xs)
        self.assertNotIn("UP5", [x.sym for s, x, d in out if d == 1])   # gap +1% ถูกตัด
        self.assertNotIn("DN6", [x.sym for s, x, d in out if d == -1])  # gap −1% ถูกตัด


class TestSimulate(unittest.TestCase):
    def mk(self, rows):
        bars = [(m, o, h, l, c, 1) for m, o, h, l, c in rows]
        return SC.Info("X", bars, 100)

    def test_stop_before_target_same_bar(self):
        x = self.mk([(0, 100, 100, 100, 100), (5, 100, 103, 97, 100)])
        e, ex, how = SC.simulate(x, 1, 1, 2.0, 1.0, 355, 0.0)
        self.assertEqual((how, ex), ("stop", 98.0))

    def test_gap_through_stop(self):
        x = self.mk([(0, 100, 100, 100, 100), (5, 100, 101, 99.5, 100), (10, 95, 96, 94, 95)])
        e, ex, how = SC.simulate(x, 1, 1, 2.0, 1.0, 355, 0.0)
        self.assertEqual((how, ex), ("stop", 95))

    def test_time_exit_and_short(self):
        x = self.mk([(0, 100, 100, 100, 100), (5, 100, 100.5, 99.5, 100), (355, 99, 99, 99, 99)])
        e, ex, how = SC.simulate(x, 1, -1, 2.0, 1.0, 355, 0.0)
        self.assertEqual((how, ex), ("time", 99))
        x = self.mk([(0, 100, 100, 100, 100), (5, 100, 100.5, 97.5, 98)])
        self.assertEqual(SC.simulate(x, 1, -1, 2.0, 1.0, 355, 0.0)[2], "target")


class FakeBroker:
    def __init__(self, fills): self._f = fills
    def fills(self, sym, since): return self._f.get(sym, [])


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self._log = DT.log; DT.log = lambda *a, **k: None
    def tearDown(self):
        DT.log = self._log

    def test_closed_long_target_short_stop_and_unfilled(self):
        st = {"open": {
            "AAA": {"submitted": "t", "dir": 1, "stop": 98.0, "gid": "g"},
            "BBB": {"submitted": "t", "dir": -1, "stop": 52.0, "gid": "g"},
            "CCC": {"submitted": "t", "dir": 1, "stop": 9.0, "gid": "g"},
            "DDD": {"submitted": "t", "dir": 1, "stop": 9.0, "gid": "g"}}}
        f = {"AAA": [("buy", 100.0, 10, "market", "2026-11-11T14:30:00"), ("sell", 102.0, 10, "limit", "2026-11-11T15:00:00")],
             "BBB": [("sell", 50.0, 5, "market", "2026-11-11T14:30:00"), ("buy", 52.0, 5, "stop", "2026-11-11T14:40:00")]}
        trades = []
        DT.reconcile(FakeBroker(f), st, trades, pos={"DDD": {}})
        by = {t["sym"]: t for t in trades}
        self.assertAlmostEqual(by["AAA"]["R"], 1.0); self.assertEqual(by["AAA"]["how"], "target")
        self.assertAlmostEqual(by["BBB"]["R"], -1.0); self.assertEqual(by["BBB"]["how"], "stop")
        self.assertNotIn("CCC", by); self.assertNotIn("CCC", st["open"])   # ไม่ fill → ลบ ไม่นับเป็น trade
        self.assertIn("DDD", st["open"])                                     # ยังถืออยู่ → ไม่แตะ


if __name__ == "__main__":
    unittest.main()
