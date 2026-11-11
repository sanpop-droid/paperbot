"""ponytail-4: บันทึกคุณภาพการเข้าไม้ (offline ไม่ใช้ key)"""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dt as DT


class TestExec(unittest.TestCase):
    def test_short_worse_fill_positive(self):
        q = DT.exec_quality({"M": 30, "m_scan": 37, "c_model": 100.0, "risk": 2.0}, 99.8, -1)
        self.assertEqual(q["late_min"], 7); self.assertAlmostEqual(q["slip_bps"], 20.0); self.assertAlmostEqual(q["slip_R"], 0.1)

    def test_long_better_fill_negative(self):
        q = DT.exec_quality({"M": 30, "m_scan": 30, "c_model": 50.0, "risk": 1.0}, 49.95, 1)
        self.assertEqual(q["late_min"], 0); self.assertLess(q["slip_bps"], 0)

    def test_old_positions_without_fields(self):
        self.assertEqual(DT.exec_quality({"stop": 1}, 10.0, 1), {})


if __name__ == "__main__":
    unittest.main()
