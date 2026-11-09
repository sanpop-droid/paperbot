"""safety.py — โหมดการเทรด (paper/live) + kill switch (ใช้ร่วมกันทั้ง bot.py และ dt.py)

โหมด
  - config.json "mode": "paper" (ค่าเริ่ม) หรือ "live"
  - จะนับเป็น live ได้ก็ต่อเมื่อ config = "live" **และ** env LIVE_CONFIRM=yes (POP ตั้งเอง) ไม่งั้นบังคับ paper
  - หมายเหตุ: เวอร์ชันนี้ยังล็อก paper endpoint เหมือนเดิม (common.base_url + paper=True ไม่ถูกแตะ)
    โหมด live มีผลแค่ "ขนาดไม้" (live_risk_pct / max_notional_per_trade) เพื่อซ้อมบน paper ก่อน

Kill switch (หยุดเปิดไม้ใหม่ · ไม้ที่ถืออยู่ใช้ stop เดิม)
  - ขาดทุนในวัน ≥ kill_daily_loss_r (ค่าเริ่ม 2R) — รวม trade ที่ปิดวันนี้ของทั้งสองบอท
  - drawdown ของ R สะสมจากจุดสูงสุด ≥ max_dd_r (ค่าเริ่ม 10R)
  - ล้าง drawdown: ตั้ง config "killswitch_reset_date": "YYYY-MM-DD" → นับเฉพาะ trade ที่ปิดหลังวันนั้น
  - บันทึกเหตุผลใน data/log.txt และ data/killswitch.json
"""
import os, math, datetime as dt
from common import load_json, save_json, path

def trading_mode(cfg):
    """คืน "live" เฉพาะเมื่อ config เป็น live และ LIVE_CONFIRM=yes เท่านั้น"""
    want = str(cfg.get("mode", "paper")).lower()
    if want == "live" and os.environ.get("LIVE_CONFIRM", "").strip().lower() == "yes":
        return "live"
    return "paper"

def risk_pct(section, cfg, mode):
    """สัดส่วนความเสี่ยงต่อไม้ (0.005 = 0.5%) · live ใช้ live_risk_pct (ค่าเริ่ม 0.25%)"""
    if mode == "live":
        return cfg.get("live_risk_pct", 0.25) / 100
    return section["risk_per_trade_pct"] / 100

def cap_notional(qty, px, cfg, mode):
    """โหมด live: จำกัดมูลค่าต่อไม้ไม่เกิน max_notional_per_trade (ค่าเริ่ม $500)"""
    if mode != "live" or px <= 0:
        return qty
    return min(qty, math.floor(cfg.get("max_notional_per_trade", 500) / px))

def evaluate(trades, today, cfg):
    """คำนวณสถานะ kill switch จากรายการ trade ที่ปิดแล้ว (ฟังก์ชันบริสุทธิ์ · ทดสอบได้ offline)"""
    day_lim = cfg.get("kill_daily_loss_r", 2.0); dd_lim = cfg.get("max_dd_r", 10.0)
    reset = cfg.get("killswitch_reset_date") or ""
    closed = [t for t in trades if t.get("exit_d") and "R" in t]
    day_r = sum(t["R"] for t in closed if t["exit_d"] == today)
    # R สะสมเรียงตามเวลาปิด → drawdown จากจุดสูงสุด
    cum = peak = 0.0
    for t in sorted((t for t in closed if t["exit_d"] > reset), key=lambda t: (t["exit_d"], t.get("t_out", ""))):
        cum += t["R"]; peak = max(peak, cum)
    dd = peak - cum
    reasons = []
    if -day_r >= day_lim: reasons.append(f"ขาดทุนวันนี้ {-day_r:.2f}R ≥ {day_lim:g}R")
    if dd >= dd_lim: reasons.append(f"drawdown {dd:.2f}R ≥ {dd_lim:g}R")
    return {"active": bool(reasons), "reason": " · ".join(reasons), "date": today,
            "day_loss_r": round(max(0.0, -day_r), 3), "dd_r": round(dd, 3),
            "limits": {"daily_loss_r": day_lim, "max_dd_r": dd_lim}}

def check(today, cfg, mode, log, swing_trades=None, scan_trades=None):
    """ประเมิน kill switch ของทั้งพอร์ต แล้วบันทึก data/killswitch.json · คืน True ถ้าต้องหยุดเปิดไม้ใหม่"""
    sw = swing_trades if swing_trades is not None else load_json("trades.json", [])
    sc = scan_trades if scan_trades is not None else load_json("dt_trades.json", [])
    st = evaluate(list(sw) + list(sc), today, cfg)
    prev = load_json("killswitch.json", {})
    st["mode"] = mode; st["checked"] = dt.datetime.now().isoformat(timespec="minutes")
    if st["active"]:
        # คงเวลาที่เริ่มหยุดไว้ · log เฉพาะตอนเริ่มหยุด/เหตุผลเปลี่ยน (กัน log ซ้ำทุก 15 นาที)
        same = prev.get("active") and prev.get("reason") == st["reason"] and prev.get("date") == today
        st["since"] = prev.get("since") if same else st["checked"]
        if not same:
            log(f"KILL SWITCH: หยุดเปิดไม้ใหม่ ({st['reason']}) · ไม้ที่ถืออยู่ใช้ stop เดิม")
    elif prev.get("active"):
        log("kill switch ปลดแล้ว (ไม่เข้าเงื่อนไขอีก)")
    save_json("killswitch.json", st)
    return st["active"]
