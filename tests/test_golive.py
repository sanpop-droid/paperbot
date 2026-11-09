"""ทดสอบ offline (ไม่ต่อเน็ต ไม่ใช้ key): โหมด live/paper + kill switch
รัน:  python -m unittest discover -s tests -v"""
import os, sys, json, shutil, tempfile, unittest, datetime as dt, types
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import common, safety

class TmpData(unittest.TestCase):
    """ย้าย data/ ไปโฟลเดอร์ชั่วคราว กันเขียนทับไฟล์จริง"""
    def setUp(self):
        self.tmp = tempfile.mkdtemp(); self._old = common.DATA; common.DATA = self.tmp
        self._env = os.environ.pop("LIVE_CONFIRM", None); self.logs = []
    def tearDown(self):
        common.DATA = self._old; shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("LIVE_CONFIRM", None)
        if self._env is not None: os.environ["LIVE_CONFIRM"] = self._env
    def log(self, m): self.logs.append(m)

class TestMode(TmpData):
    def test_no_confirm_forces_paper(self):
        self.assertEqual(safety.trading_mode({"mode": "live"}), "paper")
    def test_confirm_but_config_paper(self):
        os.environ["LIVE_CONFIRM"] = "yes"
        self.assertEqual(safety.trading_mode({"mode": "paper"}), "paper")
        self.assertEqual(safety.trading_mode({}), "paper")
    def test_live_needs_both(self):
        os.environ["LIVE_CONFIRM"] = "yes"
        self.assertEqual(safety.trading_mode({"mode": "live"}), "live")
    def test_live_sizing(self):
        cfg = {"risk_per_trade_pct": 0.5, "live_risk_pct": 0.25, "max_notional_per_trade": 500}
        self.assertAlmostEqual(safety.risk_pct(cfg, cfg, "paper"), 0.005)
        self.assertAlmostEqual(safety.risk_pct(cfg, cfg, "live"), 0.0025)
        self.assertEqual(safety.cap_notional(100, 20.0, cfg, "live"), 25)
        self.assertEqual(safety.cap_notional(100, 20.0, cfg, "paper"), 100)
    def test_paper_lock_untouched(self):
        os.environ["LIVE_CONFIRM"] = "yes"; old = os.environ.get("APCA_API_BASE_URL")
        os.environ["APCA_API_BASE_URL"] = "https://api.alpaca.markets"
        try:
            with self.assertRaises(SystemExit): common.base_url()
        finally:
            if old is None: os.environ.pop("APCA_API_BASE_URL", None)
            else: os.environ["APCA_API_BASE_URL"] = old

class TestKillSwitch(TmpData):
    def test_daily_loss_2R(self):
        tr = [{"exit_d": "2026-11-09", "R": -1.0}, {"exit_d": "2026-11-09", "R": -1.0}]
        s = safety.evaluate(tr, "2026-11-09", {})
        self.assertTrue(s["active"]); self.assertIn("ขาดทุนวันนี้", s["reason"])
    def test_small_loss_ok(self):
        s = safety.evaluate([{"exit_d": "2026-11-09", "R": -1.5}], "2026-11-09", {})
        self.assertFalse(s["active"])
    def test_yesterday_loss_not_counted(self):
        s = safety.evaluate([{"exit_d": "2026-11-08", "R": -3.0}], "2026-11-09", {})
        self.assertFalse(s["active"])
    def test_drawdown(self):
        tr = [{"exit_d": "2026-10-01", "R": 5.0}] + [{"exit_d": f"2026-10-{d:02d}", "R": -1.0} for d in range(2, 12)]
        s = safety.evaluate(tr, "2026-11-09", {})
        self.assertTrue(s["active"]); self.assertAlmostEqual(s["dd_r"], 10.0)
        s2 = safety.evaluate(tr, "2026-11-09", {"killswitch_reset_date": "2026-10-11"})
        self.assertFalse(s2["active"])
    def test_check_writes_file_and_log(self):
        tr = [{"exit_d": "2026-11-09", "R": -2.1}]
        self.assertTrue(safety.check("2026-11-09", {}, "paper", self.log, swing_trades=tr, scan_trades=[]))
        ks = json.load(open(os.path.join(self.tmp, "killswitch.json"), encoding="utf-8"))
        self.assertTrue(ks["active"]); self.assertEqual(ks["mode"], "paper")
        self.assertTrue(any("KILL SWITCH" in m for m in self.logs))
        n = len(self.logs); safety.check("2026-11-09", {}, "paper", self.log, swing_trades=tr, scan_trades=[])
        self.assertEqual(len(self.logs), n)   # ไม่ log ซ้ำ

# ---------------- จำลองบอท swing: ขาดทุน 2R แล้วต้องไม่เปิดไม้ใหม่ ----------------
class FakeBroker:
    def __init__(self): self.submitted = []
    def account(self): return {"equity": 100000.0, "cash": 100000.0, "number": "PA-TEST", "status": "ACTIVE"}
    def clock(self): return {"is_open": True, "now_ny": dt.datetime(2026, 11, 9, 10, 0), "today": "2026-11-09"}
    def positions(self): return {}
    def fills(self, sym, after): return []
    def latest_price(self, sym): return 100.0
    def close(self, sym): pass
    def submit_bracket(self, sym, qty, stop, target, cid, tif="gtc", short=False):
        self.submitted.append((sym, qty)); return "oid"

def fake_bars(syms):
    rows = []; d0 = dt.date(2025, 1, 1)
    for k in range(300):
        p = 100 + k * 0.1
        rows.append(((d0 + dt.timedelta(days=k)).isoformat(), p, p + 1, p - 1, p + 0.5))
    return {s: rows for s in syms}, "test"

class TestBotGate(TmpData):
    def _prep(self, trades):
        import bot
        self.bot = bot
        common.save_json("population.json", {"champion": {"id": "T", "g": {"k_stop": 2.0, "R": 2.0, "H": 5}}})
        common.save_json("trades.json", trades)
        self._sig = bot.S.signal; bot.S.signal = lambda g, ind, i: True   # บังคับให้มีสัญญาณทุกตัว
        self._cfg = bot.config; base = common.config(); base["mode"] = "paper"
        bot.config = lambda: base
    def tearDown(self):
        if hasattr(self, "bot"): self.bot.S.signal = self._sig; self.bot.config = self._cfg
        super().tearDown()
    def test_opens_when_ok(self):
        self._prep([]); b = FakeBroker(); self.bot.run(b, fake_bars)
        self.assertTrue(b.submitted)
    def test_blocked_after_2R_loss(self):
        self._prep([{"sym": "X", "exit_d": "2026-11-09", "R": -1.0}, {"sym": "Y", "exit_d": "2026-11-09", "R": -1.0}])
        b = FakeBroker(); self.bot.run(b, fake_bars)
        self.assertEqual(b.submitted, [])
        self.assertTrue(json.load(open(os.path.join(self.tmp, "killswitch.json"), encoding="utf-8"))["active"])

if __name__ == "__main__":
    unittest.main()
