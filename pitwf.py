"""pitwf.py — ponytail-3: walk-forward แบบ universe point-in-time (รายงานเท่านั้น: ไม่ส่งคำสั่ง ไม่เปลี่ยนแชมป์ ไม่แก้ universe.json)
กฎล็อกก่อนรัน (12 พ.ย. 2026 · POP อนุมัติแผนในแชท):
- pool = หุ้น active ที่ผ่านกฎเดิมของ build_universe แต่เอา 400 ตัว (ยังมี survivorship: หุ้นที่ถูกถอดไม่อยู่ใน pool — ข้อจำกัด)
- universe ของวัน d = 200 ตัวที่ median มูลค่าซื้อขาย (Σ close×volume ของแท่ง 5 นาที) ของ 20 วันทำการ "ก่อน" d สูงสุด · ราคาปิดวันก่อน ≥ min_price
- เทียบ 2 แบบด้วย seed เดียวกันและ evolve_scan.walk_forward ตัวเดิม (6 fold × 63 วัน):
    current = 200 ตัวของ universe.json วันนี้ (แบบที่ใช้อยู่ · มี look-ahead) · pit = universe รายวันข้างบน
- no_short ใช้ของวันนี้ทั้งสองแบบ (ข้อจำกัดเดียวกัน)
- ผ่านเมื่อ pit t ≥ 2 · ถ้า t ลดลงมาก แปลว่า edge เดิมเกินจริง
ใช้: Run workflow → job=pitwf · ผล data/pitwf.json
"""
import random, statistics, datetime as dt
import scanstrat as SC, evolve_scan as ES
from common import config, load_json, save_json, load_5min_alpaca

POOL_N, TOP_N, LOOKBACK = 400, 200, 20


def pit_universe(dv, closes, dates, top=TOP_N, lookback=LOOKBACK, min_price=5.0):
    """dv/closes = {sym: {date: value}} → {date: set(sym)} ใช้เฉพาะข้อมูลก่อนวันนั้น (ไม่มี look-ahead)"""
    out = {}
    for i, d in enumerate(dates):
        prev = dates[max(0, i - lookback):i]
        if len(prev) < 5:
            out[d] = set(); continue
        sc = []
        for s, m in dv.items():
            vals = [m[p] for p in prev if p in m]
            last = next((closes[s][p] for p in reversed(prev) if p in closes.get(s, {})), None)
            if len(vals) >= 5 and last is not None and last >= min_price:
                sc.append((statistics.median(vals), s))
        sc.sort(reverse=True)
        out[d] = {s for _, s in sc[:top]}
    return out


def restrict(panel, allow):
    """panel เฉพาะหุ้นที่อยู่ใน universe ของวันนั้น"""
    return {d: [x for x in xs if x.sym in allow.get(d, ())] for d, xs in panel.items() if allow.get(d)}


def run(days, dv, closes, cur_syms, today, seed=None, log=print, folds=6):
    cfg = config()["scan"]; U = load_json("universe.json", {}); no_short = set(U.get("no_short", []))
    panel = SC.build_panel(days, cfg["min_price"]); dates = sorted(panel)
    if len(dates) < 150:
        log("ข้อมูลน้อยเกินไป"); return None
    seed = seed if seed is not None else int(today.replace("-", "")) + 31
    cur = set(cur_syms)
    p_cur = restrict(panel, {d: cur for d in dates})
    p_pit = restrict(panel, pit_universe(dv, closes, dates, min_price=cfg["min_price"]))
    overlap = []
    for d in dates[::21]:
        a = {x.sym for x in p_pit.get(d, [])}
        if a: overlap.append(len(a & cur) / len(a))
    wf_cur, n1 = ES.walk_forward(p_cur, random.Random(seed), folds=folds, no_short=no_short, log=lambda m: log("[current] " + m))
    wf_pit, n2 = ES.walk_forward(p_pit, random.Random(seed), folds=folds, no_short=no_short, log=lambda m: log("[pit] " + m))
    out = {"date": today, "pool": len(days), "top": TOP_N, "lookback_days": LOOKBACK, "seed": seed,
           "overlap_pit_vs_current": round(sum(overlap) / len(overlap), 3) if overlap else None,
           "current": wf_cur, "pit": wf_pit, "tested": n1 + n2,
           "verdict": ("ผ่าน: WF แบบไม่ look-ahead t ≥ 2" if wf_pit["t"] >= 2 else
                       "ไม่ผ่าน: WF แบบไม่ look-ahead t < 2 → edge เดิมน่าจะเกินจริง"),
           "limits": "pool ยังเป็นหุ้น active วันนี้ (ไม่มีหุ้นที่ถูกถอด) · no_short ของวันนี้"}
    save_json("pitwf.json", out)
    log(f"current WF t {wf_cur['t']} avgR {wf_cur['avgR']} n {wf_cur['n']} · pit WF t {wf_pit['t']} avgR {wf_pit['avgR']} n {wf_pit['n']} · {out['verdict']}")
    return out


if __name__ == "__main__":
    cfg = config(); sc = dict(cfg["scan"]); sc["universe_size"] = POOL_N
    ES.save_json = lambda *a, **k: None   # ห้ามเขียนทับ universe.json ของบอทจริง
    pool = ES.build_universe(sc, set(cfg["symbols"]))["symbols"]
    cur_syms = load_json("universe.json", {}).get("symbols", [])
    days, dv, closes = {}, {}, {}
    for i in range(0, len(pool), 20):
        part = load_5min_alpaca(pool[i:i + 20], days_back=sc["history_days"], feed="sip")
        for sym, dd in part.items():
            dv[sym] = {d: sum(b[4] * b[5] for b in bars) for d, bars in dd.items() if bars}
            closes[sym] = {d: bars[-1][4] for d, bars in dd.items() if bars}
            days[sym] = {d: SC.compact(b) for d, b in dd.items()}
        del part
        print(f"โหลดแท่ง 5 นาที {min(i + 20, len(pool))}/{len(pool)}", flush=True)
    run(days, dv, closes, cur_syms, dt.date.today().isoformat())
