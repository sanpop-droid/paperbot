"""research.py — งานวิจัยจากข้อเสนอ Scout 11 พ.ย. (รายงานเท่านั้น: ไม่ส่งคำสั่ง ไม่เปลี่ยนแชมป์ ไม่แก้ config)
กฎล็อกก่อนรัน (12 พ.ย. 2026 · POP อนุมัติแผนในแชท) — ห้ามปรับหลังเห็นผล ผลเขียน data/research.json

A) scout-2 Scanner โหมด reversal (fade): ซื้อ K ตัวที่ "ลงแรงสุด" / short K ตัวที่ "ขึ้นแรงสุด" จากราคาปิดเมื่อวาน ณ นาที M
   grid 108 ชุด: mode {rev-long, rev-short, rev-both} × M {30,60,90} × th {2,4,6}% × k_stop {0.6,1.2} × R {1.0,2.0} · K = 3 · ไม่มีตัวกรอง gap
   เลือกตัวดีสุดด้วย t รายวันใน train (ก่อน split เดียวกับ evolve_scan, ต้อง ≥ 30 วันที่มีไม้) → รายงาน holdout ที่ slippage 5/10/20 bps
   เทียบแชมป์ momentum บน holdout เดียวกัน · ผ่านเมื่อ holdout t รายวัน ≥ 2 และ avgR > 0 ที่ 10 bps
B) scout-3 ความลำเอียงจากการเลือกกฎ:
   - PBO (CSCV, S = 16 ช่วงเวลา) ของ grid ข้อ A และของผู้สมัคร scanner ใน population_scan.json (+ แชมป์)
   - Deflated Sharpe ของแชมป์ scanner บน holdout (R รายวัน) · N = n_tested_total · ความแปรปรวนของ Sharpe จากผู้สมัครใน train
C) scout-4 Swing volatility targeting: แชมป์ swing บน symbols ใน config (ข้อมูลรายวัน 3 ปี)
   scale = clip(median vol / vol 20 วันของ SPY ณ วันสัญญาณ, 0.5, 1.0) · vol เป้า = median ของทั้งช่วง (ไม่จูน)
   เทียบ total R, max DD (R), Sharpe ต่อไม้ แบบมี/ไม่มี scale · ไม้น้อย = สรุปไม่ได้ (บอกตรงๆ)
ใช้: Run workflow → job=research
"""
import math, itertools, datetime as dt, random
from statistics import NormalDist
import strategy as S, scanstrat as SC
from robustness import daily_t
from common import config, load_json, save_json, load_5min_alpaca, load_bars_alpaca

N01 = NormalDist()
GRID = [dict(mode=mo, M=M, th=th, k_stop=k, R=R, K=3)
        for mo in ("rev-long", "rev-short", "rev-both") for M in (30, 60, 90) for th in (0.02, 0.04, 0.06)
        for k in (0.6, 1.2) for R in (1.0, 2.0)]


# ---------------------------------------------------------------- A) reversal
def rank_rev(g, infos, no_short=()):
    """reversal: long ตัวที่ลง ≥ th (แรงสุดก่อน) · short ตัวที่ขึ้น ≥ th · วัดจากราคาปิดเมื่อวานถึงนาที M"""
    M = g["M"]; sc = []
    for x in infos:
        if M in x.c_at and x.pc:
            sc.append((x.c_at[M] / x.pc - 1, x))
    out = []
    if g["mode"] in ("rev-long", "rev-both"):
        L = sorted([(s, x) for s, x in sc if s <= -g["th"]], key=lambda t: t[0])
        out += [(s, x, 1) for s, x in L[:g["K"]]]
    if g["mode"] in ("rev-short", "rev-both"):
        Sh = sorted([(s, x) for s, x in sc if s >= g["th"] and x.sym not in no_short], key=lambda t: -t[0])
        out += [(s, x, -1) for s, x in Sh[:g["K"]]]
    return out


def backtest_rev(g, panel, start=None, end=None, slip=0.0005, no_short=()):
    """กลไกเข้า/ออกเหมือน scanstrat.backtest ทุกอย่าง ต่างแค่การเลือกตัว (rank_rev)"""
    trades = []; M = g["M"]
    flat_m = next(mm for mm in range(M, SC.SESSION + 1, SC.STEP) if mm >= SC.SESSION - SC.FLAT_BEFORE)
    for d in sorted(panel):
        if (start and d < start) or (end and d > end): continue
        for s, x, di in rank_rev(g, panel[d], no_short):
            e = x.i_at[M] + 1
            if e >= len(x.m): continue
            risk = g["k_stop"] * 3 * x.atr_at[M]
            if risk <= 0: continue
            entry, ex, how = SC.simulate(x, e, di, risk, g["R"], flat_m, slip)
            ex *= (1 - slip * di)
            trades.append({"sym": x.sym, "sig": d, "dir": di, "how": how, "R": di * (ex - entry) / risk,
                           "ret": di * (ex / entry - 1), "open": False})
    return trades


def gid_rev(g):
    return f"{g['mode']}-M{g['M']}-K{g['K']}-th{g['th']*100:.0f}-k{g['k_stop']}-R{g['R']}"


def part_a(panel, split, champ, no_short):
    rows = []
    for g in GRID:
        tr = backtest_rev(g, panel, end=split, no_short=no_short); d = daily_t([t for t in tr if t["sig"] < split])
        rows.append((g, S.metrics(tr), d))
    ok = [r for r in rows if r[2]["days"] >= 30]
    best = max(ok, key=lambda r: r[2]["t_day"]) if ok else None
    out = {"grid_n": len(GRID), "eligible": len(ok), "train_top5": [
        {"id": gid_rev(g), "n": m["n"], "avgR": round(m["avgR"], 4), "t_day": round(d["t_day"], 2)}
        for g, m, d in sorted(ok, key=lambda r: -r[2]["t_day"])[:5]]}
    if best:
        g = best[0]; hold = []
        for s in (0.0005, 0.001, 0.002):
            tr = backtest_rev(g, panel, start=split, slip=s, no_short=no_short); m = S.metrics(tr); d = daily_t(tr)
            hold.append({"slip_bps": round(s * 1e4), "n": m["n"], "avgR": round(m["avgR"], 4), "t_day": round(d["t_day"], 2)})
        out["best"] = {"id": gid_rev(g), "train_t_day": round(best[2]["t_day"], 2), "holdout": hold}
        h10 = hold[1]; out["pass"] = h10["avgR"] > 0 and hold[0]["t_day"] >= 2
    ch = []
    for s in (0.0005, 0.001, 0.002):
        tr = SC.backtest(champ["g"], panel, start=split, slip=s, no_short=no_short); m = S.metrics(tr); d = daily_t(tr)
        ch.append({"slip_bps": round(s * 1e4), "n": m["n"], "avgR": round(m["avgR"], 4), "t_day": round(d["t_day"], 2)})
    out["champion_holdout"] = {"id": champ["id"], "rows": ch}
    return out, rows


# ---------------------------------------------------------------- B) PBO + DSR
def daily_series(trades, dates):
    by = {}
    for t in trades:
        if not t.get("open"): by[t["sig"]] = by.get(t["sig"], 0.0) + t["R"]
    return [by.get(d, 0.0) for d in dates]


def sharpe(x):
    n = len(x)
    if n < 2: return 0.0
    m = sum(x) / n; sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    return m / sd if sd > 0 else 0.0


def pbo_cscv(series, S_=16, max_combos=4000, seed=7):
    """series: list ของ R รายวัน (ยาวเท่ากัน) ต่อกฎ 1 ตัว → PBO = สัดส่วนครั้งที่กฎดีสุดใน IS ตกครึ่งล่างใน OOS"""
    N = len(series); T = len(series[0]) if N else 0
    if N < 2 or T < S_ * 5: return None
    b = T // S_; blocks = [list(range(i * b, (i + 1) * b)) for i in range(S_)]
    combos = list(itertools.combinations(range(S_), S_ // 2))
    if len(combos) > max_combos: combos = random.Random(seed).sample(combos, max_combos)
    lam = []
    for c in combos:
        cs = set(c); IS = [i for k in c for i in blocks[k]]; OS = [i for k in range(S_) if k not in cs for i in blocks[k]]
        sr_is = [sharpe([s[i] for i in IS]) for s in series]; sr_os = [sharpe([s[i] for i in OS]) for s in series]
        n_star = max(range(N), key=lambda j: sr_is[j])
        rank = sum(1 for v in sr_os if v < sr_os[n_star]) + 0.5 * (sum(1 for v in sr_os if v == sr_os[n_star]) - 1)
        w = (rank + 1) / (N + 1); lam.append(math.log(w / (1 - w)))
    return {"pbo": round(sum(1 for l in lam if l <= 0) / len(lam), 3), "combos": len(lam), "n_rules": N, "days": T}


def dsr(x, n_trials, var_sr):
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014) ของ R รายวัน x"""
    n = len(x)
    if n < 10 or n_trials < 2: return None
    m = sum(x) / n; sd = math.sqrt(sum((v - m) ** 2 for v in x) / (n - 1))
    if sd == 0: return None
    sr = m / sd
    g3 = sum(((v - m) / sd) ** 3 for v in x) / n; g4 = sum(((v - m) / sd) ** 4 for v in x) / n
    em = 0.5772156649
    sr0 = math.sqrt(max(var_sr, 1e-12)) * ((1 - em) * N01.inv_cdf(1 - 1 / n_trials) + em * N01.inv_cdf(1 - 1 / (n_trials * math.e)))
    den = math.sqrt(max(1e-12, 1 - g3 * sr + (g4 - 1) / 4 * sr ** 2))
    return {"sr_daily": round(sr, 4), "sr0": round(sr0, 4), "dsr": round(N01.cdf((sr - sr0) * math.sqrt(n - 1) / den), 3),
            "n_days": n, "n_trials": n_trials}


def part_b(panel, split, P, rev_rows, no_short):
    dates = sorted(panel); out = {}
    rev = [daily_series(backtest_rev(g, panel, no_short=no_short), dates) for g, _, _ in rev_rows]
    out["pbo_reversal_grid"] = pbo_cscv(rev)
    cands = [P["champion"]] + [c for c in P.get("candidates", []) if c.get("id") != P["champion"]["id"]]
    cs = [daily_series(SC.backtest(c["g"], panel, no_short=no_short), dates) for c in cands]
    out["pbo_scan_candidates"] = pbo_cscv(cs)
    tr_dates = [i for i, d in enumerate(dates) if d < split]
    var_sr = 0.0
    if len(cs) > 2:
        srs = [sharpe([s[i] for i in tr_dates]) for s in cs]; mu = sum(srs) / len(srs)
        var_sr = sum((v - mu) ** 2 for v in srs) / (len(srs) - 1)
    ho = [i for i, d in enumerate(dates) if d >= split]
    out["dsr_champion_holdout"] = dsr([cs[0][i] for i in ho], int(P.get("n_tested_total", 0)), var_sr)
    return out


# ---------------------------------------------------------------- C) vol targeting (swing)
def part_c():
    cfg = config(); syms = list(cfg["symbols"]); Q = load_json("population.json", {}); ch = Q.get("champion")
    if not ch: return {"note": "ไม่มีแชมป์ swing"}
    bars, feed = load_bars_alpaca(syms + ["SPY"], years=3)
    spy = bars.pop("SPY"); inds = {s: S.Ind(r) for s, r in bars.items() if len(r) > 250}
    trs = [t for t in S.backtest(ch["g"], inds) if not t["open"]]
    c = [r[4] for r in spy]; d = [r[0] for r in spy]; vol = {}
    for i in range(21, len(c)):
        rets = [c[k] / c[k - 1] - 1 for k in range(i - 19, i + 1)]; m = sum(rets) / 20
        vol[d[i]] = math.sqrt(sum((r - m) ** 2 for r in rets) / 19) * math.sqrt(252)
    vs = sorted(vol.values()); target = vs[len(vs) // 2] if vs else None
    def stats(R):
        cum = peak = dd = 0.0
        for r in R: cum += r; peak = max(peak, cum); dd = max(dd, peak - cum)
        return {"n": len(R), "totR": round(sum(R), 2), "maxDD_R": round(dd, 2), "sharpe_trade": round(sharpe(R), 3)}
    trs.sort(key=lambda t: t["entry_d"])
    base = [t["R"] for t in trs]
    scl = [t["R"] * min(1.0, max(0.5, target / vol[t["sig"]])) if target and vol.get(t["sig"]) else t["R"] for t in trs]
    b, s = stats(base), stats(scl)
    return {"champion": ch["id"], "feed": feed, "vol_target": round(target, 4) if target else None, "base": b, "scaled": s,
            "dd_cut_pct": round(100 * (1 - s["maxDD_R"] / b["maxDD_R"]), 1) if b["maxDD_R"] else None,
            "totR_cut_pct": round(100 * (1 - s["totR"] / b["totR"]), 1) if b["totR"] else None,
            "pass": bool(b["maxDD_R"] and b["totR"] > 0 and s["maxDD_R"] <= 0.85 * b["maxDD_R"] and s["totR"] >= 0.9 * b["totR"] and s["sharpe_trade"] >= b["sharpe_trade"]),
            "note": "ไม้น้อย (< 30) = สรุปไม่ได้" if len(trs) < 30 else ""}


def run(days, today, log=print):
    cfg = config()["scan"]; P = load_json("population_scan.json", {}); U = load_json("universe.json", {})
    no_short = set(U.get("no_short", [])); champ = P.get("champion")
    if not champ:
        log("ไม่มีแชมป์ scanner"); return None
    panel = SC.build_panel(days, cfg["min_price"])
    split = (P.get("runs") or [{}])[-1].get("split") or sorted(panel)[int(len(panel) * 0.7)]
    out = {"date": today, "split": split, "days_in_panel": len(panel), "preregistered": "ดู docstring research.py (commit ก่อนรัน)"}
    a, rows = part_a(panel, split, champ, no_short); out["reversal"] = a
    log(f"[A] reversal best {a.get('best', {}).get('id')} · holdout {a.get('best', {}).get('holdout')} · pass {a.get('pass')}")
    out["selection_bias"] = part_b(panel, split, P, rows, no_short); log(f"[B] {out['selection_bias']}")
    try:
        out["vol_targeting"] = part_c(); log(f"[C] {out['vol_targeting']}")
    except (SystemExit, Exception) as e:   # โหลดราคา swing ไม่ได้ ไม่ให้ส่วน A/B หาย
        out["vol_targeting"] = {"error": str(e)[:200]}; log(f"[C] error {e}")
    save_json("research.json", out)
    return out


if __name__ == "__main__":
    sc = config()["scan"]; U = load_json("universe.json", {}); syms = U.get("symbols", []); days = {}
    for i in range(0, len(syms), 20):
        part = load_5min_alpaca(syms[i:i + 20], days_back=sc["history_days"], feed="sip")
        for sym, dd in part.items():
            days[sym] = {d: SC.compact(b) for d, b in dd.items()}
        del part
        print(f"โหลดแท่ง 5 นาที {min(i + 20, len(syms))}/{len(syms)}", flush=True)
    run(days, dt.date.today().isoformat())
