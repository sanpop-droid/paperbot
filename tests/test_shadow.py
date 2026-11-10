"""ทดสอบ offline แบบ dry (ไม่ต่อเน็ต ไม่ใช้ key ไม่ส่งคำสั่ง): shadow test ตัวเต็งอันดับ 2–3
ใช้แท่ง 5 นาทีจำลอง 6 วัน (5 วันย้อนหลัง + วันนี้) · รัน:  python -m unittest discover -s tests -v"""
import os, sys, json, shutil, tempfile, random, unittest, datetime as dt
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import common, scanstrat as SC, shadow

DATES = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09"]
TODAY = DATES[-1]

def synth_days(n_sym=30, seed=7):
    """random walk แท่ง 5 นาที 78 แท่ง/วัน · บางตัว gap/วิ่งแรงเพื่อให้มีสัญญาณ"""
    rng = random.Random(seed); out = {}
    for k in range(n_sym):
        sym = f"S{k:02d}"; px = rng.uniform(20, 200); dd = {}
        for d in DATES:
            px *= 1 + rng.gauss(0, 0.03); drift = rng.gauss(0, 0.002); bars = []
            for i in range(78):
                o = px; c = o * (1 + drift + rng.gauss(0, 0.004))
                h = max(o, c) * (1 + abs(rng.gauss(0, 0.002))); l = min(o, c) * (1 - abs(rng.gauss(0, 0.002)))
                bars.append((i * 5, o, h, l, c, 1000.0)); px = c
            dd[d] = bars
        out[sym] = dd
    return out

G2 = {"M": 30, "K": 3, "pc": 1, "side": 2, "th": 0.005, "gap_lo": -0.1, "gap_hi": 0.1, "k_stop": 1.0, "R": 1.5}
G3 = {"M": 60, "K": 2, "pc": 0, "side": 0, "th": 0.002, "gap_lo": -0.1, "gap_hi": 0.1, "k_stop": 0.8, "R": 2.0}
CH = {"M": 30, "K": 1, "pc": 1, "side": 0, "th": 0.001, "gap_lo": -0.1, "gap_hi": 0.1, "k_stop": 1.0, "R": 1.0}

def cand(i, g, passed=True, t=1.0):
    g = SC.fix(dict(g))
    return {"id": SC.gid(g), "g": g, "passed_holdout": passed, "holdout": {"n": 50, "avgR": 0.1, "tstat": t, "win": 0.5}}

class FakeBroker:
    def __init__(self): self.submitted = []
    def account(self): return {"equity": 100000.0, "cash": 100000.0, "number": "PA-TEST", "status": "ACTIVE"}
    def clock(self): return {"is_open": True, "now_ny": dt.datetime(2026, 11, 9, 10, 0), "today": TODAY}
    def positions(self): return {}
    def fills(self, sym, after): return []
    def latest_price(self, sym): raise RuntimeError("offline")
    def close(self, sym): pass
    def submit_bracket(self, sym, qty, stop, target, cid, tif="gtc", short=False):
        self.submitted.append(sym); return "oid"

class TestShadow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self._old = common.DATA; common.DATA = self.tmp
        champ = cand(0, CH, t=2.0)
        self.P = {"champion": {**champ, "probation": True}, "candidates": [champ, cand(1, G2, t=1.5), cand(2, G3, t=1.2),
                  cand(3, G3 | {"R": 3.0}, passed=False, t=3.0), cand(4, G2 | {"K": 1}, t=0.5)], "runs": []}
        common.save_json("population_scan.json", self.P)
        self.days = synth_days()
        common.save_json("universe.json", {"symbols": sorted(self.days), "no_short": []})
    def tearDown(self):
        common.DATA = self._old; shutil.rmtree(self.tmp, ignore_errors=True)

    def test_select_rank_2_3(self):
        ids = [c["id"] for c in shadow.select(self.P)]
        self.assertEqual(ids, [SC.gid(G2), SC.gid(G3)])   # ไม่เอาแชมป์ · ไม่เอาตัวที่ไม่ผ่าน holdout · เรียงตาม t

    def _run_dt(self, with_shadow=True):
        import dt as D
        logs = []; D.log = logs.append
        if with_shadow:
            common.save_json("scan_shadow.json", {"date": "2026-11-01", "shadow": shadow.select(self.P)})
        else:
            common.save_json("scan_shadow.json", {"date": "2026-11-01", "shadow": []})
        cfg = common.config(); cfg["symbols"] = ["AAPL"]; D.config = lambda: cfg
        b = FakeBroker(); D.run(b, lambda U, today: self.days, force_minute=30)
        return b, logs

    def test_dt_dry_5_days(self):
        b0, _ = self._run_dt(with_shadow=False)
        common.save_json("dt_state.json", {"open": {}, "scanned": {}})
        b1, logs = self._run_dt(with_shadow=True)
        self.assertEqual(b0.submitted, b1.submitted)   # shadow ไม่เพิ่ม/เปลี่ยนคำสั่งจริง
        st = common.load_json("shadow_trades.json", {})
        self.assertTrue(st["trades"], "ควรมี trade สมมติจากข้อมูล 5 วัน")
        # วันที่คิด = วันที่จบแล้วเท่านั้น (ไม่รวมวันนี้ และข้ามวันแรกที่ไม่มีราคาปิดเมื่อวาน)
        self.assertTrue(all(DATES[1] <= t["d"] < TODAY for t in st["trades"]))
        # ผลต้องตรงกับ backtest ของแชมป์แบบเดียวกัน
        panel = SC.build_panel(self.days, 5)
        exp = SC.backtest(G2, panel, start=DATES[1], end=DATES[-2])
        got = [t for t in st["trades"] if t["id"] == SC.gid(G2)]
        self.assertEqual(len(got), len(exp))
        self.assertAlmostEqual(sum(t["R"] for t in got), sum(t["R"] for t in exp), places=2)
        # แชมป์ถูกจำลองบนแท่งชุดเดียวกัน (เทียบยุติธรรมกับตัวเต็ง)
        ch = self.P["champion"]; self.assertEqual(st["champion"], ch["id"])
        exp_ch = SC.backtest(ch["g"], panel, start=DATES[1], end=DATES[-2])
        got_ch = [t for t in st["trades"] if t["id"] == ch["id"]]
        self.assertEqual(len(got_ch), len(exp_ch))
        self.assertAlmostEqual(sum(t["R"] for t in got_ch), sum(t["R"] for t in exp_ch), places=2)
        # รันซ้ำวันเดิม → ไม่บันทึกซ้ำ
        n = len(st["trades"]); shadow.update(self.days, TODAY, 5, log=lambda m: None)
        self.assertEqual(len(common.load_json("shadow_trades.json", {})["trades"]), n)
        print(f"\n  dry run: {len(got)} + {n - len(got) - len(got_ch)} + แชมป์ {len(got_ch)} trade สมมติ · คำสั่งจริง {len(b1.submitted)} (เท่ากับไม่มี shadow)")

    def test_bootstrap_from_population(self):
        shadow.update(self.days, TODAY, 5, log=lambda m: None)
        sh = common.load_json("scan_shadow.json", {})
        self.assertEqual([c["id"] for c in sh["shadow"]], [SC.gid(G2), SC.gid(G3)])

    def test_office_report_shadow(self):
        common.save_json("scan_shadow.json", {"date": "2026-11-01", "shadow": shadow.select(self.P)})
        shadow.update(self.days, TODAY, 5, log=lambda m: None, champ=self.P["champion"])
        import office_report as O
        old = O.D; O.D = self.tmp
        try:
            sh = O.build()["scan"]["shadow"]
        finally:
            O.D = old
        self.assertEqual([x["id"] for x in sh], [SC.gid(G2), SC.gid(G3), self.P["champion"]["id"]])
        self.assertEqual(set(sh[0]), {"id", "n", "avgR", "win", "tstat"})
        self.assertTrue(sh[-1]["champion"] and sh[-1]["simulated"])

if __name__ == "__main__":
    unittest.main()
