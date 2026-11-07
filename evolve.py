"""evolve.py — ให้กฎเทรด "วิวัฒนาการ" ด้วย Genetic Algorithm แล้วคัดตัวที่ผ่านการทดสอบนอกตัวอย่าง
รันสัปดาห์ละครั้ง (Task Scheduler) หรือดับเบิลคลิก evolve.bat

ขั้นตอน
 1. แบ่งข้อมูล 3 ปี: 70% แรก = train (ให้ GA หา) · 30% หลัง = holdout (GA ไม่เคยเห็น)
 2. GA แบบ 3 เกาะ (breakout / pullback / trend) เกาะละ 16 ชุด → คะแนนบน train → คัดตัวเก่ง → ผสม/กลายพันธุ์ × 12 รุ่น
 3. 3 อันดับแรกของแต่ละเกาะเป็น "ผู้สมัคร" พร้อมผล holdout (ผ่าน = avg R > 0 และ trade ≥ 10)
 4. ผู้สมัครทุกตัวถูกจดวันเกิด (born) แล้วเทรดแบบเงา — ผลหลังวันเกิดคือ forward test ของจริง
 5. เปลี่ยนแชมป์ (ตัวที่เทรดจริงใน Alpaca paper) เฉพาะเมื่อผู้ท้าชิงชนะใน forward test
"""
import random, datetime as dt, sys
import strategy as S
from common import config, load_json, save_json, load_bars_alpaca, load_bars_csv

def run(bars, today, seed=None, pop_n=16, gens=12, log=print):
    cfg = config(); rng = random.Random(seed if seed is not None else int(today.replace("-", "")))
    inds = {s: S.Ind(r) for s, r in bars.items() if len(r) > 250}
    dates = sorted({d for ind in inds.values() for d in ind.d})
    split = dates[int(len(dates) * 0.7)]
    P = load_json("population.json", {"champion": None, "candidates": [], "runs": [], "n_tested_total": 0})

    # ---- GA บนช่วง train แบบ "เกาะ" (island model): แต่ละประเภทกฎวิวัฒนาการแยกกัน เพื่อไม่ให้ทุกตัวหน้าตาเหมือนกัน ----
    gen_log, tested, final = [], 0, []
    for typ in S.TYPES:
        def rnd():
            g = S.random_genome(rng); g["type"] = typ; return g
        pop = [rnd() for _ in range(pop_n)]
        olds = [dict(c["g"]) for c in P["candidates"] if c["g"]["type"] == typ][:4]  # ความรู้สะสมจากรอบก่อน
        for k, g in enumerate(olds): pop[k] = g
        for gnum in range(gens):
            scored = []
            for g in pop:
                m = S.metrics(S.backtest(g, inds, end=split)); tested += 1
                scored.append((S.fitness(m), g, m))
            scored.sort(key=lambda x: -x[0])
            best = scored[0]; ho = S.metrics(S.backtest(best[1], inds, start=split))
            gen_log.append({"island": typ, "gen": gnum + 1, "is_t": round(best[2]["tstat"], 2), "is_avgR": round(best[2]["avgR"], 3),
                            "ho_t": round(ho["tstat"], 2), "ho_avgR": round(ho["avgR"], 3), "id": S.gid(best[1])})
            log(f"[{typ:8s}] รุ่น {gnum+1:2d}: train t={best[2]['tstat']:5.2f} avgR={best[2]['avgR']:+.3f} | holdout t={ho['tstat']:5.2f} avgR={ho['avgR']:+.3f}")
            elite = [x[1] for x in scored[:4]]
            def pick():
                a, b = rng.sample(scored[:max(4, pop_n // 2)], 2)
                return a[1] if a[0] > b[0] else b[1]
            kids = []
            for _ in range(pop_n - len(elite) - 2):
                c = S.mutate(S.crossover(pick(), pick(), rng), rng); c["type"] = typ; kids.append(c)
            pop = elite + kids + [rnd() for _ in range(2)]
        # ---- 3 อันดับแรกของเกาะนี้ (ไม่ซ้ำกัน) ----
        seen, k = set(), 0
        for fit, g, mi in scored:
            if S.gid(g) in seen: continue
            seen.add(S.gid(g)); mh = S.metrics(S.backtest(g, inds, start=split))
            final.append((fit, g, mi, mh)); k += 1
            if k == 3: break
    P["n_tested_total"] = P.get("n_tested_total", 0) + tested
    luck = S.luck_bar(P["n_tested_total"])
    bh = S.buy_hold(inds, split)
    known = {c["id"] for c in P["candidates"]}
    added = []
    for fit, g, mi, mh in final:
        if mh["n"] >= 5 and S.gid(g) not in known:  # ทุกตัวได้ลงสนาม forward test แบบเงา; holdout ใช้จัดอันดับ
            c = {"id": S.gid(g), "g": g, "born": today, "train": mi, "holdout": mh, "desc": S.describe_th(g),
                 "passed_holdout": mh["n"] >= 10 and mh["avgR"] > 0}
            P["candidates"].append(c); added.append(c["id"]); known.add(c["id"])
    # ---- forward test ของทุกผู้สมัคร (สัญญาณหลังวันเกิดเท่านั้น) ----
    for c in P["candidates"]:
        c["forward"] = S.metrics(S.backtest(c["g"], inds, start=c["born"]))
    # เก็บไว้ไม่เกิน 30 ตัว: ตัดตัวที่ forward แย่สุดเมื่อมีข้อมูลพอ
    P["candidates"].sort(key=lambda c: (-(c["forward"]["avgR"] if c["forward"]["n"] >= 5 else 0), -c["holdout"]["tstat"]))
    P["candidates"] = P["candidates"][:30]

    # ---- เลือกแชมป์ ----
    champ = P.get("champion"); reason = "คงแชมป์เดิม"
    if champ:
        champ["forward"] = S.metrics(S.backtest(champ["g"], inds, start=champ["born"]))
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
        reason = (f"ยังไม่มีข้อมูล forward: ตั้ง {best['id']} เป็นแชมป์ทดลองงาน (ความเสี่ยงครึ่งเดียว)"
                  + ("" if best.get("passed_holdout") else " · คำเตือน: ไม่มีกฎไหนผ่าน holdout ผลนี้เพื่อเก็บข้อมูลเท่านั้น"))
    elif not champ:
        reason = "ยังไม่มีผู้สมัคร · บอทจะยังไม่เทรด"
    P["champion"] = champ
    P["runs"].append({"date": today, "split": split, "tested": tested, "tested_total": P["n_tested_total"], "luck_t": round(luck, 2),
                      "bh_holdout": round(bh, 4), "gens": gen_log, "added": added, "decision": reason})
    P["runs"] = P["runs"][-26:]
    save_json("population.json", P)
    log(f"\nทดลองกฎไปแล้วรวม {P['n_tested_total']} ครั้ง → t-stat ที่โชคช่วยก็ทำได้ ≈ {luck:.2f}")
    log(f"ซื้อแล้วถือ (holdout) เฉลี่ย {bh*100:+.1f}% · ผู้สมัครใหม่: {added or 'ไม่มี'}")
    log("การตัดสินใจ: " + reason)
    return P

if __name__ == "__main__":
    cfg = config()
    if len(sys.argv) > 2 and sys.argv[1] == "--csv":
        bars = load_bars_csv(sys.argv[2], cfg["symbols"]); today = max(r[0] for v in bars.values() for r in v)
    else:
        bars, feed = load_bars_alpaca(cfg["symbols"], years=3); today = dt.date.today().isoformat()
        print(f"โหลดราคา {len(bars)} หุ้น (feed {feed})")
    run(bars, today)
    try:
        import dashboard; dashboard.build()
    except Exception as e:
        print("สร้าง dashboard ไม่สำเร็จ:", e)
