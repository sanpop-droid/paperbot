"""robustness.py — รายงานความทนของแชมป์ scanner (งานรายงานเท่านั้น ไม่ส่งคำสั่ง ไม่เปลี่ยนแชมป์)
dt-rnd-robust-1 (ponytail-2, ponytail-5):
 1) holdout ของแชมป์ (+ ตัวเต็ง shadow) ที่ slippage 5/10/15/20/30 bps ต่อข้าง + จุดคุ้มทุน (break-even)
 2) t-stat แบบรวมรายวัน (ไม้หลายตัวในวันเดียวกันไม่อิสระต่อกัน) เทียบ t ต่อ trade
ใช้: Run workflow → job=robust · ผล data/robustness.json
"""
import math, datetime as dt
import strategy as S, scanstrat as SC
from common import config, load_json, save_json, load_5min_alpaca

SLIPS = [0.0005, 0.001, 0.0015, 0.002, 0.003]


def daily_t(trades):
    """sum R ต่อวัน → t ของค่าเฉลี่ยรายวัน (sd ตัวอย่าง ไม่มี floor)"""
    by = {}
    for t in trades:
        if not t.get("open"):
            by[t["sig"]] = by.get(t["sig"], 0.0) + t["R"]
    x = list(by.values()); n = len(x)
    if n < 2:
        return {"days": n, "avgR_day": (x[0] if x else 0.0), "t_day": 0.0}
    m = sum(x) / n; sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return {"days": n, "avgR_day": m, "t_day": (m / sd * math.sqrt(n)) if sd > 0 else 0.0}


def plain_t(trades):
    R = [t["R"] for t in trades if not t.get("open")]; n = len(R)
    if n < 2: return 0.0
    m = sum(R) / n; sd = math.sqrt(sum((v - m) ** 2 for v in R) / (n - 1))
    return m / sd * math.sqrt(n) if sd > 0 else 0.0


def breakeven(g, panel, split, no_short, lo=0.0, hi=0.02, it=18):
    """slippage ต่อข้างที่ทำให้ avgR = 0 (bisection) · None ถ้า avgR ≤ 0 ตั้งแต่ไม่มี slippage หรือ > hi"""
    f = lambda s: S.metrics(SC.backtest(g, panel, start=split, slip=s, no_short=no_short))["avgR"]
    if f(lo) <= 0: return None
    if f(hi) > 0: return hi
    for _ in range(it):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if f(mid) > 0 else (lo, mid)
    return round((lo + hi) / 2, 5)


def analyse(g, panel, split, no_short=()):
    rows = []
    for s in SLIPS:
        tr = SC.backtest(g, panel, start=split, slip=s, no_short=no_short); m = S.metrics(tr); d = daily_t(tr)
        rows.append({"slip_bps": round(s * 1e4, 1), "n": m["n"], "avgR": round(m["avgR"], 4), "t_report": round(m["tstat"], 2),
                     "t_plain": round(plain_t(tr), 2), "days": d["days"], "t_day": round(d["t_day"], 2)})
    be = breakeven(g, panel, split, no_short)
    return {"rows": rows, "breakeven_bps": None if be is None else round(be * 1e4, 1)}


def run(days, today, log=print):
    cfg = config()["scan"]
    P = load_json("population_scan.json", {}); U = load_json("universe.json", {}); no_short = set(U.get("no_short", []))
    champ = P.get("champion")
    if not champ:
        log("ไม่มีแชมป์"); return None
    panel = SC.build_panel(days, cfg["min_price"])
    split = (P.get("runs") or [{}])[-1].get("split") or sorted(panel)[int(len(panel) * 0.7)]
    who = [("champion", champ)] + [("shadow", c) for c in load_json("scan_shadow.json", {}).get("shadow", [])]
    out = {"date": today, "split": split, "days_in_panel": len(panel), "note": "holdout เดิม (ตั้งแต่ split) · t_report = สูตรเดิม (sd ขั้นต่ำ 0.5) · t_plain = sd จริง · t_day = รวมรายวัน", "rules": []}
    for role, c in who:
        a = analyse(c["g"], panel, split, no_short); a.update({"id": c["id"], "role": role}); out["rules"].append(a)
        r10 = next(r for r in a["rows"] if r["slip_bps"] == 10.0)
        log(f"[{role}] {c['id']}: break-even {a['breakeven_bps']} bps/ข้าง · 10 bps avgR {r10['avgR']:+.4f} t_day {r10['t_day']}")
        for r in a["rows"]:
            log(f"   slip {r['slip_bps']:>4} bps: n {r['n']:4d} avgR {r['avgR']:+.4f} t {r['t_report']:5.2f} (plain {r['t_plain']:5.2f}) · {r['days']} วัน t_day {r['t_day']:5.2f}")
    ch = out["rules"][0]; r10 = next(r for r in ch["rows"] if r["slip_bps"] == 10.0)
    out["verdict"] = ("เปราะบาง: avgR ≤ 0 ที่ 10 bps" if r10["avgR"] <= 0 else
                      "ยังไม่มีหลักฐานพอ: t รายวัน < 2" if ch["rows"][0]["t_day"] < 2 else "ผ่าน: t รายวัน ≥ 2 และบวกที่ 10 bps")
    save_json("robustness.json", out)
    log("สรุป: " + out["verdict"])
    return out


if __name__ == "__main__":
    cfg = config(); sc = cfg["scan"]
    U = load_json("universe.json", {}); syms = U.get("symbols", []); days = {}
    for i in range(0, len(syms), 20):
        part = load_5min_alpaca(syms[i:i + 20], days_back=sc["history_days"], feed="sip")
        for sym, dd in part.items():
            days[sym] = {d: SC.compact(b) for d, b in dd.items()}
        del part
        print(f"โหลดแท่ง 5 นาที {min(i + 20, len(syms))}/{len(syms)}", flush=True)
    run(days, dt.date.today().isoformat())
