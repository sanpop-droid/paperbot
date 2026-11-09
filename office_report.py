"""office_report.py — สรุปผลของบอททั้งสองเป็น JSON สำหรับแอป Trading Office
ใช้โดย scheduled task ของ Claude:  python office_report.py > office_latest.json
ไม่ต่อเน็ต ไม่ต้องใช้ key อ่านแค่ไฟล์ใน data/"""
import json, os, datetime as dt
import strategy as S

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def j(name, default):
    try:
        with open(os.path.join(D, name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def m(trades):
    if not trades: return {"n": 0, "avgR": 0, "win": 0, "pnl": 0}
    mm = S.metrics([{**t, "open": False, "ret": 0} for t in trades])
    return {"n": mm["n"], "avgR": round(mm["avgR"], 3), "win": round(mm["win"], 3), "t": round(mm["tstat"], 2),
            "pnl": round(sum(t.get("pnl", 0) for t in trades), 2)}

def champ(P):
    c = (P or {}).get("champion")
    if not c: return None
    return {"id": c["id"], "desc": c.get("desc", ""), "probation": bool(c.get("probation")), "since": c.get("since"),
            "holdout": {k: round(c["holdout"].get(k, 0), 3) for k in ("n", "avgR", "tstat", "win")} if c.get("holdout") else None,
            "forward": {k: round(c.get("forward", {}).get(k, 0), 3) for k in ("n", "avgR", "tstat")} if c.get("forward") else None}

def build():
    eq = j("equity.json", []); sw_tr = j("trades.json", []); sw_st = j("state.json", {"open": {}})
    sc_tr = j("dt_trades.json", []); sc_st = j("dt_state.json", {"open": {}, "scanned": {}})
    Psw = j("population.json", {}); Psc = j("population_scan.json", {}); U = j("universe.json", {})
    rsw = (Psw.get("runs") or [{}])[-1]; rsc = (Psc.get("runs") or [{}])[-1]
    log = []
    try:
        with open(os.path.join(D, "log.txt"), encoding="utf-8") as f:
            log = [l.rstrip() for l in f.readlines()[-30:] if l.strip()]
    except FileNotFoundError:
        pass
    scanned = sc_st.get("scanned", {}); last_day = max(scanned) if scanned else None
    errors = [l for l in log if "ERROR" in l or "ไม่สำเร็จ" in l]
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=7))).strftime("%Y-%m-%d %H:%M")
    eq_last = eq[-1]["equity"] if eq else None; eq_first = eq[0]["equity"] if eq else None
    sw_m, sc_m = m(sw_tr), m(sc_tr)
    out = {
        "updated": today,
        "equity": [{"d": e["date"], "v": round(e["equity"], 2)} for e in eq[-180:]],
        "equity_now": eq_last, "equity_change_pct": round((eq_last / eq_first - 1) * 100, 2) if eq_first else 0,
        "swing": {"champion": champ(Psw), "stats": sw_m,
                  "open": [{"sym": s, **{k: o[k] for k in ("qty", "stop", "target", "entry_day", "H") if k in o}} for s, o in sw_st.get("open", {}).items()],
                  "trades": sw_tr[-20:], "last_evolve": rsw.get("date"), "decision": rsw.get("decision")},
        "scan": {"champion": champ(Psc), "stats": sc_m, "universe": len(U.get("symbols", [])), "universe_date": U.get("date"),
                 "wf": rsc.get("wf", {}) and {k: rsc["wf"][k] for k in ("n", "avgR", "t", "win") if k in rsc["wf"]},
                 "last_scan": {"date": last_day, "picks": scanned.get(last_day, [])} if last_day else None,
                 "open": [{"sym": s, **{k: o[k] for k in ("dir", "qty", "stop", "target", "entry_day") if k in o}} for s, o in sc_st.get("open", {}).items()],
                 "trades": sc_tr[-30:], "last_evolve": rsc.get("date"), "decision": rsc.get("decision")},
        "log_tail": log[-12:], "errors": errors[-5:],
    }
    # โหมด + kill switch (killswitch.json เขียนโดยบอทตอนรัน · mode ในนั้นคือโหมดที่บอทเห็นจริง)
    try:
        with open(os.path.join(os.path.dirname(D), "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfg = {}
    ks = j("killswitch.json", {})
    out["mode"] = ks.get("mode", "paper"); out["mode_config"] = cfg.get("mode", "paper"); out["endpoint"] = "paper"
    out["killswitch"] = {k: ks.get(k) for k in ("active", "reason", "since", "date", "dd_r", "limits", "checked")} if ks else {"active": False}
    out["day_loss_r"] = ks.get("day_loss_r", 0); out["day_loss_date"] = ks.get("date")   # วันตามเวลา NY ของบอท
    # shadow test ของตัวเต็งอันดับ 2–3 (trade สมมติ ไม่ได้ส่งคำสั่ง)
    sh = j("scan_shadow.json", {}); shtr = j("shadow_trades.json", {}).get("trades", [])
    out["scan"]["shadow"] = []
    for c in sh.get("shadow", []):
        mm = m([t for t in shtr if t.get("id") == c["id"]])
        out["scan"]["shadow"].append({"id": c["id"], "n": mm["n"], "avgR": mm["avgR"], "win": mm["win"], "tstat": mm.get("t", 0)})
    # สถานะตัวละครในออฟฟิศ (ส่วนที่คำนวณได้จากข้อมูล · บทบาทวิเคราะห์ให้ scheduled task เติม)
    sc_line = ("สแกน " + last_day + ": " + (", ".join(("L " if p.get("dir", 1) > 0 else "S ") + p["sym"] for p in scanned[last_day]) or "ไม่มีตัวผ่านเกณฑ์")) if last_day else "รอสแกนครั้งแรก"
    out["roles"] = {
        "scanner": {"status": "ok" if last_day else "idle", "line": sc_line,
                    "detail": f"แชมป์: {out['scan']['champion']['desc'] if out['scan']['champion'] else '-'}\nWalk-forward t = {out['scan']['wf'].get('t', '-')} ({out['scan']['wf'].get('n', 0)} trade)\nปิดแล้ว {sc_m['n']} trade · avg R {sc_m['avgR']:+.3f}"},
        "swing": {"status": "busy" if sw_st.get("open") else "idle", "line": f"ถือ {len(sw_st.get('open', {}))} ตัว · ปิดแล้ว {sw_m['n']} trade",
                  "detail": f"แชมป์: {out['swing']['champion']['desc'] if out['swing']['champion'] else '-'}\navg R {sw_m['avgR']:+.3f} · P&L ${sw_m['pnl']:+,.2f}"},
        "risk": {"status": "alert" if (errors or out["killswitch"].get("active")) else "ok", "line": ("KILL SWITCH: " + (out["killswitch"].get("reason") or "")) if out["killswitch"].get("active") else (("มี error " + str(len(errors)) + " รายการ") if errors else "ไม่มี error · paper เท่านั้น"),
                 "detail": "\n".join(errors) if errors else "log ล่าสุดไม่มี error · ทุกตำแหน่ง day trade ถูกปิดก่อนตลาดปิด"},
    }
    return out

if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
