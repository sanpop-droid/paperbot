"""evolve_scan.py — รันทุกเสาร์ (หรือ Run workflow → evolve)
 1) สร้าง universe: หุ้น US ที่ซื้อขายได้ทั้งหมด (ตัด ETF leverage/inverse/VIX) → คัด 300 ตัวที่มูลค่าซื้อขายต่อวัน (median 20 วัน) สูงสุด ราคา ≥ $5
    ไม่รวมหุ้นของบอท swing (กันตำแหน่งชนกันในบัญชีเดียว)
 2) โหลดแท่ง 5 นาทีย้อนหลังของ 300 ตัว (SIP)
 3) GA 2 เกาะ (วัดความแรงจากราคาเปิด / จากราคาปิดเมื่อวาน) · robust fitness · holdout 30% · stability test
 4) ผู้สมัครเทรดแบบเงา → เลื่อนแชมป์เมื่อชนะ forward test
"""
import random, datetime as dt, statistics, re
import strategy as S, scanstrat as SC
from common import config, keys, load_json, save_json, load_5min_alpaca

LEV = re.compile(r"\b(\d(\.\d)?X|-\dX|ULTRA\w*|INVERSE|LEVERAGED|BULL|BEAR|VIX|VOLATILITY|DAILY TARGET)\b|SHORT (QQQ|S&P|DOW|RUSSELL|\w+ ETF)")

def is_leveraged(name):
    """ETF แบบ leverage / inverse / VIX (เช่น SOXL, TQQQ, SQQQ, UVXY, TSLL) — เหวี่ยงหลายเท่าของตลาดจึงติดอันดับบ่อยเกินจริง"""
    return bool(LEV.search((name or "").upper()))

def build_universe(cfg_scan, swing_syms, log=print):
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetAssetsRequest
    from alpaca.trading.enums import AssetClass, AssetStatus
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import Adjustment, DataFeed
    k, s = keys()
    assets = TradingClient(k, s, paper=True).get_all_assets(GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.US_EQUITY))
    ok_ex = {"NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"}
    base = [a for a in assets if a.tradable and str(getattr(a.exchange, "value", a.exchange)) in ok_ex
            and a.symbol.isalpha() and a.symbol not in swing_syms]
    lev = sorted(a.symbol for a in base if is_leveraged(a.name))
    syms = sorted(a.symbol for a in base if not is_leveraged(a.name))
    log(f"หุ้นที่ซื้อขายได้ {len(syms)} ตัว (ตัด ETF leverage/inverse/VIX ออก {len(lev)} ตัว เช่น {', '.join(lev[:8])}) → วัดสภาพคล่อง")
    cli = StockHistoricalDataClient(k, s)
    end = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20); start = end - dt.timedelta(days=35)
    stats = []
    for i in range(0, len(syms), 400):
        chunk = syms[i:i + 400]
        try:
            res = cli.get_stock_bars(StockBarsRequest(symbol_or_symbols=chunk, timeframe=TimeFrame.Day, start=start, end=end,
                                                      adjustment=Adjustment.ALL, feed=DataFeed.SIP)).data
        except Exception as e:
            log(f"  ข้าม chunk {i}: {e}"); continue
        for sym, bars in res.items():
            if len(bars) < 15: continue
            dv = statistics.median(float(b.close) * float(b.volume) for b in bars[-20:])
            px = float(bars[-1].close)
            if px >= cfg_scan["min_price"]:
                stats.append((dv, sym, px))
    stats.sort(reverse=True)
    top = stats[:cfg_scan["universe_size"]]
    log(f"universe: {len(top)} ตัว · มูลค่าซื้อขายต่อวันต่ำสุดในกลุ่ม ${top[-1][0]/1e6:,.0f}M" if top else "universe ว่าง")
    U = {"date": dt.date.today().isoformat(), "symbols": [t[1] for t in top], "excluded_leveraged": len(lev),
         "dollar_volume_m": {t[1]: round(t[0] / 1e6, 1) for t in top}, "rule": "median 20 วันของ ราคา×ปริมาณ · ราคา ≥ min_price · ไม่รวมหุ้น swing · ไม่รวม ETF leverage/inverse/VIX"}
    save_json("universe.json", U)
    return U

def run(days, today, seed=None, pop_n=20, gens=12, log=print):
    cfg = config()["scan"]; rng = random.Random(seed if seed is not None else int(today.replace("-", "")) + 11)
    panel = SC.build_panel(days, cfg["min_price"])
    dates = sorted(panel)
    if len(dates) < 30:
        log("ข้อมูลน้อยเกินไป"); return None
    split = dates[int(len(dates) * 0.7)]; tr_dates = [d for d in dates if d < split]
    edges = [tr_dates[len(tr_dates) // 3], tr_dates[2 * len(tr_dates) // 3]]
    P = load_json("population_scan.json", {"champion": None, "candidates": [], "runs": [], "n_tested_total": 0})
    gen_log, tested, final = [], 0, []
    for typ in SC.TYPES:
        pop = [SC.random_genome(rng, typ) for _ in range(pop_n)]
        for k, c in enumerate([c for c in P["candidates"] if c["g"]["type"] == typ][:4]): pop[k] = dict(c["g"])
        for gnum in range(gens):
            scored = []
            for g in pop:
                trs = SC.backtest(g, panel, end=split); m = S.metrics(trs); tested += 1
                fit, pos = S.robust_fitness(trs, edges, min_n=30); m["consistency"] = pos
                scored.append((fit, g, m))
            scored.sort(key=lambda x: -x[0])
            best = scored[0]; ho = S.metrics(SC.backtest(best[1], panel, start=split))
            gen_log.append({"island": typ, "gen": gnum + 1, "is_t": round(best[2]["tstat"], 2), "is_avgR": round(best[2]["avgR"], 3),
                            "ho_t": round(ho["tstat"], 2), "ho_avgR": round(ho["avgR"], 3), "id": SC.gid(best[1])})
            log(f"[{typ:9s}] รุ่น {gnum+1:2d}: train t={best[2]['tstat']:5.2f} n={best[2]['n']:4d} | holdout t={ho['tstat']:5.2f} avgR={ho['avgR']:+.3f}")
            elite = [x[1] for x in scored[:4]]
            def pick():
                a, b = rng.sample(scored[:10], 2); return a[1] if a[0] > b[0] else b[1]
            pop = elite + [SC.mutate(SC.crossover(pick(), pick(), rng), rng) for _ in range(pop_n - 6)] + [SC.random_genome(rng, typ) for _ in range(2)]
        seen, k = set(), 0
        for fit, g, mi in scored:
            if SC.gid(g) in seen: continue
            seen.add(SC.gid(g)); mh = S.metrics(SC.backtest(g, panel, start=split))
            mh["stability"] = S.stability(g, lambda x: S.metrics(SC.backtest(x, panel, start=split)), SC.mutate, rng); tested += 6
            final.append((fit, g, mi, mh)); k += 1
            if k == 3: break
    P["n_tested_total"] = P.get("n_tested_total", 0) + tested
    known = {c["id"] for c in P["candidates"]}; added = []
    for fit, g, mi, mh in final:
        if mh["n"] >= 10 and SC.gid(g) not in known:
            P["candidates"].append({"id": SC.gid(g), "g": g, "born": today, "train": mi, "holdout": mh, "desc": SC.describe_th(g),
                                    "passed_holdout": mh["n"] >= 20 and mh["avgR"] > 0 and mh.get("stability", 1) >= 0.5})
            added.append(SC.gid(g)); known.add(SC.gid(g))
    for c in P["candidates"]:
        c["forward"] = S.metrics(SC.backtest(c["g"], panel, start=c["born"]))
    P["candidates"].sort(key=lambda c: (-(c["forward"]["avgR"] if c["forward"]["n"] >= 10 else 0), -c["holdout"]["tstat"]))
    P["candidates"] = P["candidates"][:20]
    champ = P.get("champion"); reason = "คงแชมป์เดิม"
    if champ: champ["forward"] = S.metrics(SC.backtest(champ["g"], panel, start=champ["born"]))
    ready = [c for c in P["candidates"] if c["forward"]["n"] >= cfg["promote_min_forward_trades"] and c["forward"]["avgR"] > 0]
    if ready:
        best = max(ready, key=lambda c: c["forward"]["avgR"])
        if not champ or (best["id"] != champ["id"] and best["forward"]["avgR"] > champ.get("forward", {}).get("avgR", -9)):
            champ = dict(best); champ["since"] = today; champ["probation"] = False
            reason = f"เลื่อนขั้น {best['id']}: forward {best['forward']['n']} trade, avg R {best['forward']['avgR']:+.3f}"
    elif champ and champ.get("probation") and not champ.get("passed_holdout") and any(c.get("passed_holdout") for c in P["candidates"]):
        best = max([c for c in P["candidates"] if c.get("passed_holdout")], key=lambda c: c["holdout"]["tstat"])
        champ = dict(best); champ["since"] = today; champ["probation"] = True
        reason = f"เปลี่ยนแชมป์ทดลองงานเป็น {best['id']} (ผ่าน holdout)"
    elif not champ and P["candidates"]:
        best = max(P["candidates"], key=lambda c: (c.get("passed_holdout", False), c["holdout"]["tstat"]))
        champ = dict(best); champ["since"] = today; champ["probation"] = True
        reason = f"แชมป์ทดลองงาน {best['id']} (ความเสี่ยงครึ่งเดียว)" + ("" if best.get("passed_holdout") else " · ไม่มีกฎผ่าน holdout: เก็บข้อมูลเท่านั้น")
    elif not champ:
        reason = "ยังไม่มีผู้สมัคร"
    P["champion"] = champ
    P["runs"].append({"date": today, "split": split, "universe": sum(1 for _ in days), "days": len(dates), "tested": tested,
                      "tested_total": P["n_tested_total"], "luck_t": round(S.luck_bar(P["n_tested_total"]), 2),
                      "bh_holdout": round(SC.baseline(panel, split), 5), "gens": gen_log, "added": added, "decision": reason})
    P["runs"] = P["runs"][-26:]
    save_json("population_scan.json", P)
    log(f"การตัดสินใจ (scanner): {reason}")
    return P

if __name__ == "__main__":
    cfg = config(); sc = cfg["scan"]
    U = build_universe(sc, set(cfg["symbols"]))
    syms = U["symbols"]; days = {}
    for i in range(0, len(syms), 50):
        part = load_5min_alpaca(syms[i:i + 50], days_back=sc["history_days"], feed="sip")
        days.update(part); print(f"โหลดแท่ง 5 นาที {min(i+50, len(syms))}/{len(syms)}")
    run(days, dt.date.today().isoformat())
