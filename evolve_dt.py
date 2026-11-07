"""evolve_dt.py — GA สำหรับกฎ Day trade (แท่ง 5 นาที ย้อนหลัง ~6 เดือน)
4 เกาะ (orb / vwap / momo / dip) × 16 × 10 รุ่น · ทุกกฎมียีนตัวกรอง gap
คะแนน = robust fitness (train แบ่ง 3 ช่วง ต้องกำไรสม่ำเสมอ) · holdout 30% + stability test · ผู้สมัครเทรดแบบเงา · เลื่อนแชมป์จาก forward test"""
import random, datetime as dt, sys
import strategy as S, daystrat as D
from common import config, load_json, save_json, load_5min_alpaca

def run(days, today, seed=None, pop_n=16, gens=10, log=print):
    cfg = config()["day"]; rng = random.Random(seed if seed is not None else int(today.replace("-", "")) + 7)
    dates = sorted({d for dd in days.values() for d in dd})
    if len(dates) < 30:
        log("ข้อมูล 5 นาทีน้อยเกินไป"); return None
    split = dates[int(len(dates) * 0.7)]
    P = load_json("population_dt.json", {"champion": None, "candidates": [], "runs": [], "n_tested_total": 0})
    gen_log, tested, final = [], 0, []
    tr_dates = [d for d in dates if d < split]
    edges = [tr_dates[len(tr_dates) // 3], tr_dates[2 * len(tr_dates) // 3]]
    for typ in D.TYPES:
        def rnd():
            g = D.random_genome(rng); g["type"] = typ; return g
        pop = [rnd() for _ in range(pop_n)]
        for k, c in enumerate([c for c in P["candidates"] if c["g"]["type"] == typ][:4]): pop[k] = dict(c["g"])
        for gnum in range(gens):
            scored = []
            for g in pop:
                trs = D.backtest(g, days, end=split); m = S.metrics(trs); tested += 1
                fit, pos = S.robust_fitness(trs, edges, min_n=30); m["consistency"] = pos
                scored.append((fit, g, m))
            scored.sort(key=lambda x: -x[0])
            best = scored[0]; ho = S.metrics(D.backtest(best[1], days, start=split))
            gen_log.append({"island": typ, "gen": gnum + 1, "is_t": round(best[2]["tstat"], 2), "is_avgR": round(best[2]["avgR"], 3),
                            "ho_t": round(ho["tstat"], 2), "ho_avgR": round(ho["avgR"], 3), "id": D.gid(best[1])})
            log(f"[{typ:4s}] รุ่น {gnum+1:2d}: train t={best[2]['tstat']:5.2f} n={best[2]['n']:3d} | holdout t={ho['tstat']:5.2f} avgR={ho['avgR']:+.3f}")
            elite = [x[1] for x in scored[:4]]
            def pick():
                a, b = rng.sample(scored[:8], 2); return a[1] if a[0] > b[0] else b[1]
            kids = []
            for _ in range(pop_n - 6):
                c = D.mutate(D.crossover(pick(), pick(), rng), rng); c["type"] = typ; kids.append(c)
            pop = elite + kids + [rnd(), rnd()]
        seen, k = set(), 0
        for fit, g, mi in scored:
            if D.gid(g) in seen: continue
            seen.add(D.gid(g)); mh = S.metrics(D.backtest(g, days, start=split))
            mh["stability"] = S.stability(g, lambda x: S.metrics(D.backtest(x, days, start=split)), D.mutate, rng); tested += 6
            final.append((fit, g, mi, mh)); k += 1
            if k == 3: break
    P["n_tested_total"] = P.get("n_tested_total", 0) + tested
    known = {c["id"] for c in P["candidates"]}; added = []
    for fit, g, mi, mh in final:
        if mh["n"] >= 10 and D.gid(g) not in known:
            P["candidates"].append({"id": D.gid(g), "g": g, "born": today, "train": mi, "holdout": mh, "desc": D.describe_th(g),
                                    "passed_holdout": mh["n"] >= 20 and mh["avgR"] > 0 and mh.get("stability", 1) >= 0.5}); added.append(D.gid(g)); known.add(D.gid(g))
    for c in P["candidates"]:
        c["forward"] = S.metrics(D.backtest(c["g"], days, start=c["born"]))
    P["candidates"].sort(key=lambda c: (-(c["forward"]["avgR"] if c["forward"]["n"] >= 10 else 0), -c["holdout"]["tstat"]))
    P["candidates"] = P["candidates"][:20]
    champ = P.get("champion"); reason = "คงแชมป์เดิม"
    if champ: champ["forward"] = S.metrics(D.backtest(champ["g"], days, start=champ["born"]))
    ready = [c for c in P["candidates"] if c["forward"]["n"] >= cfg["promote_min_forward_trades"] and c["forward"]["avgR"] > 0]
    if ready:
        best = max(ready, key=lambda c: c["forward"]["avgR"])
        if not champ or (best["id"] != champ["id"] and best["forward"]["avgR"] > champ.get("forward", {}).get("avgR", -9)):
            champ = dict(best); champ["since"] = today; champ["probation"] = False
            reason = f"เลื่อนขั้น {best['id']}: forward {best['forward']['n']} trade, avg R {best['forward']['avgR']:+.3f}"
    elif champ and champ.get("probation") and not champ.get("passed_holdout") and any(c.get("passed_holdout") for c in P["candidates"]):
        # แชมป์ทดลองงานที่ไม่ผ่าน holdout ถูกแทนด้วยผู้สมัครที่ผ่าน (ยังทดลองงานจนกว่าจะชนะ forward test)
        best = max([c for c in P["candidates"] if c.get("passed_holdout")], key=lambda c: c["holdout"]["tstat"])
        champ = dict(best); champ["since"] = today; champ["probation"] = True
        reason = f"เปลี่ยนแชมป์ทดลองงานเป็น {best['id']} (ผ่าน holdout: avg R {best['holdout']['avgR']:+.3f} จาก {best['holdout']['n']} trade)"
    elif not champ and P["candidates"]:
        best = max(P["candidates"], key=lambda c: (c.get("passed_holdout", False), c["holdout"]["tstat"]))
        champ = dict(best); champ["since"] = today; champ["probation"] = True
        reason = f"แชมป์ทดลองงาน {best['id']} (ความเสี่ยงครึ่งเดียว)" + ("" if best.get("passed_holdout") else " · ไม่มีกฎผ่าน holdout: เก็บข้อมูลเท่านั้น")
    elif not champ:
        reason = "ยังไม่มีผู้สมัคร · บอท day trade ยังไม่เทรด"
    P["champion"] = champ
    P["runs"].append({"date": today, "split": split, "tested": tested, "tested_total": P["n_tested_total"],
                      "luck_t": round(S.luck_bar(P["n_tested_total"]), 2), "bh_holdout": round(D.buy_hold_intraday(days, split), 5),
                      "gens": gen_log, "added": added, "decision": reason})
    P["runs"] = P["runs"][-26:]
    save_json("population_dt.json", P)
    log(f"การตัดสินใจ (day): {reason}")
    return P

if __name__ == "__main__":
    cfg = config()["day"]
    days = load_5min_alpaca(cfg["symbols"], days_back=cfg.get("history_days", 180), feed="sip")
    print("โหลดแท่ง 5 นาที:", {s: len(v) for s, v in days.items()}, "วัน")
    run(days, dt.date.today().isoformat())
