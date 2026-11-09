"""shadow.py — Shadow test: เทรดสมมติของตัวเต็งอันดับ 2–3 ของ scanner (ไม่ส่งคำสั่งจริง ไม่เปลี่ยนแชมป์)

- data/scan_shadow.json   รายชื่อตัวเต็ง (evolve_scan.py เขียนทุกครั้งที่ evolve · ถ้ายังไม่มี dt.py จะสร้างจาก population_scan.json)
- data/shadow_trades.json {"evaluated": {id: วันล่าสุดที่คิดแล้ว}, "champion": id แชมป์ที่จำลองด้วย, "trades": [...]}
วิธีคิด: ทุกครั้งที่ dt.py ดึงแท่ง 5 นาทีมาสแกน (วันนี้ + ~5 วันก่อน) จะเอา "วันก่อนหน้าที่จบแล้ว" มาจำลองด้วย
scanstrat.backtest ตัวเดียวกับแชมป์ (เข้าแท่งถัดจากนาที M · stop / target · ปิดก่อนตลาดปิด · slippage เท่ากัน)
→ ผลของวันนี้จะถูกบันทึกในการสแกนของวันทำการถัดไป (ต้องรอให้วันจบก่อนถึงรู้ผล)
"""
import scanstrat as SC
from common import load_json, save_json

N_SHADOW = 2   # อันดับ 2–3 = 2 ตัวถัดจากแชมป์

def select(P, n=N_SHADOW):
    """เลือกผู้สมัครที่ผ่าน holdout (ไม่ใช่แชมป์) เรียงตาม holdout t-stat"""
    champ_id = ((P or {}).get("champion") or {}).get("id")
    ok = [c for c in (P or {}).get("candidates", []) if c.get("passed_holdout") and c["id"] != champ_id]
    ok.sort(key=lambda c: -c.get("holdout", {}).get("tstat", 0))
    return [{"id": c["id"], "g": c["g"], "desc": c.get("desc", ""),
             "holdout": {k: round(c["holdout"].get(k, 0), 3) for k in ("n", "avgR", "tstat", "win")}} for c in ok[:n]]

def save_from_population(P, today):
    """เรียกจาก evolve_scan.run หลังเลือกแชมป์"""
    sh = {"date": today, "champion": ((P or {}).get("champion") or {}).get("id"), "shadow": select(P)}
    save_json("scan_shadow.json", sh)
    return sh

def load(today):
    sh = load_json("scan_shadow.json", None)
    if sh is None:   # ยังไม่เคย evolve หลังมีฟีเจอร์นี้ → สร้างจากผู้สมัครปัจจุบัน
        sh = save_from_population(load_json("population_scan.json", {}), today)
    return sh

def update(days, today, min_price, no_short=(), exclude=(), log=print, champ=None):
    """จำลอง trade ของตัวเต็ง (+ แชมป์ ไว้เทียบบนแท่งชุดเดียวกัน) บนวันที่จบแล้ว (ก่อน today) ที่ยังไม่เคยคิด · คืนจำนวน trade ใหม่"""
    sh = load(today)
    if not sh.get("shadow"):
        return 0
    days = {s: dd for s, dd in days.items() if s not in exclude}
    panel = SC.build_panel(days, min_price)
    past = sorted(d for d in panel if d < today)[1:]   # วันแรกไม่มีราคาปิดเมื่อวาน → ข้าม (กันผลเพี้ยนจาก gap)
    if not past:
        return 0
    st = load_json("shadow_trades.json", {"evaluated": {}, "trades": []})
    cands = list(sh["shadow"])
    if champ:   # แชมป์ live มี delay/slippage จริง → จำลองแชมป์แบบเดียวกันด้วยเพื่อเทียบยุติธรรม
        st["champion"] = champ["id"]
        cands.append({"id": champ["id"], "g": champ["g"]})
    added = 0
    for c in cands:
        last = st["evaluated"].get(c["id"]) or sh.get("date") or ""   # นับเฉพาะวันหลังจากได้เป็นตัวเต็ง
        todo = [d for d in past if d > last]
        if not todo:
            continue
        for t in SC.backtest(c["g"], panel, start=todo[0], end=todo[-1], no_short=no_short):
            st["trades"].append({"id": c["id"], "sym": t["sym"], "dir": t["dir"], "d": t["entry_d"], "entry": round(t["entry"], 4),
                                 "exit": round(t["exit"], 4), "how": t["how"], "R": round(t["R"], 4)})
            added += 1
        st["evaluated"][c["id"]] = todo[-1]
    st["trades"] = st["trades"][-2000:]
    save_json("shadow_trades.json", st)
    if added:
        log(f"shadow: บันทึก trade สมมติ {added} รายการ ({', '.join(c['id'] for c in cands)})")
    return added
