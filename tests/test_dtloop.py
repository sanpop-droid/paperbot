"""ทดสอบ offline: dtloop ด้วย clock ปลอม (ไม่ต่อ Alpaca ไม่ส่งคำสั่ง ไม่ commit)"""
import os, sys, unittest, datetime as dt
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from test_golive import TmpData
import dtloop

NOW = lambda: dt.datetime.now(dt.timezone.utc)

class TestDecide(unittest.TestCase):
    def test_states(self):
        n = NOW()
        self.assertEqual(dtloop.decide({"is_open": True}, n, 0), "run")
        self.assertEqual(dtloop.decide({"is_open": False, "next_open": n + dt.timedelta(minutes=90)}, n, 0), "wait")
        self.assertEqual(dtloop.decide({"is_open": False, "next_open": n + dt.timedelta(hours=17)}, n, 0), "stop")
        self.assertEqual(dtloop.decide({"is_open": True}, n, dtloop.BUDGET), "next")
        self.assertEqual(dtloop.decide({"is_open": False, "next_open": n}, n, dtloop.BUDGET), "stop")

class TestLoop(TmpData):
    def simulate(self, states):
        """states = ลำดับ clock ทีละรอบ ('wait'/'open'/'closed'); เวลาเดินทีละ STEP เมื่อ sleep"""
        t = [0.0]; seq = iter(states); calls = []
        def clock():
            s = next(seq)
            if s == "open": return {"is_open": True, "today": "2026-11-10"}
            hrs = 1 if s == "wait" else 17
            return {"is_open": False, "today": "2026-11-10", "next_open": NOW() + dt.timedelta(hours=hrs)}
        def sleep(sec): t[0] += sec
        with mock.patch.object(dtloop, "clock", clock), mock.patch.object(dtloop, "sh", lambda *c: calls.append(c)), \
             mock.patch.object(dtloop, "commit", lambda: calls.append("commit")), \
             mock.patch.object(dtloop, "dispatch", lambda: calls.append("dispatch")), \
             mock.patch.object(dtloop.time, "sleep", sleep), mock.patch.object(dtloop.time, "monotonic", lambda: t[0]):
            dtloop.main()
        return calls

    def test_wait_open_then_close(self):
        c = self.simulate(["wait", "wait", "open", "open", "open", "closed"])
        self.assertEqual(c.count(("bot.py", "run")), 1)       # swing ครั้งเดียว
        self.assertEqual(c.count(("dt.py",)), 4)               # 3 รอบเปิด + 1 รอบหลังปิด
        self.assertNotIn("dispatch", c)
        self.assertEqual(c[-1], "commit")

    def test_closed_day_exits_immediately(self):
        c = self.simulate(["closed"])
        self.assertEqual(c, ["commit"])                         # ตัวเริ่มที่ตามมาทีหลัง: ไม่รันอะไร

    def test_budget_redispatch_and_no_double_swing(self):
        n = dtloop.BUDGET // dtloop.STEP + 1
        c = self.simulate(["open"] * (n + 1))
        self.assertEqual(c[-1], "dispatch")
        self.assertEqual(c.count(("bot.py", "run")), 1)
        self.assertGreaterEqual(c.count("commit"), 2)           # commit ระหว่างทาง (~30 นาที) + ตอนจบ
        c2 = self.simulate(["open", "closed"])                  # รอบที่ถูกสั่งต่อ: ไม่รัน swing ซ้ำวันเดิม
        self.assertNotIn(("bot.py", "run"), c2)

    def test_clock_error_retries(self):
        seq = iter([RuntimeError("net"), {"is_open": False, "today": "x", "next_open": NOW() + dt.timedelta(hours=17)}])
        def clock():
            v = next(seq)
            if isinstance(v, Exception): raise v
            return v
        with mock.patch.object(dtloop, "clock", clock), mock.patch.object(dtloop, "commit", lambda: None), \
             mock.patch.object(dtloop.time, "sleep", lambda s: None), mock.patch.object(dtloop, "log", self.log):
            dtloop.main()
        self.assertTrue(any("ERROR clock" in m for m in self.logs))

if __name__ == "__main__":
    unittest.main()
