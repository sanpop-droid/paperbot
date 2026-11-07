"""dt.py — บอท Day trade แบบ Scanner บนบัญชี Alpaca **Paper** (ซื้อ-ขายจบในวัน)
GitHub Actions เรียกทุก 15 นาทีระหว่างตลาดเปิด
  1) บันทึก trade ที่ปิดไปแล้ว
  2) เหลือ ≤ 35 นาทีก่อนปิด → ขายทุกตัวของบอทนี้ · ตำแหน่งค้างข้ามวัน → ขายทันที
  3) ถึงนาทีที่ M ของแชมป์ (และวันนี้ยังไม่สแกน) → สแกน universe จัดอันดับ → long ตัวที่ขึ้นแรงสุด และ/หรือ short ตัวที่ลงแรงสุด (bracket DAY)
"""
import math, datetime as dt, traceback
import strategy as S, scanstrat as SC
from common import config, load_json, save_json, load_5min_alpaca, path
from bot import AlpacaBroker

def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M} [scan] {msg}"
    print(line)
    with open(path("log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

def session_minute(now_ny):
    return now_ny.hour * 60 + now_ny.minute - (9 * 60 + 30)

def reconcile(broker, st, trades, pos):
    for sym, info in list(st["open"].items()):
        if sym in pos: continue
        fills = broker.fills(sym, info["submitted"]); d = info.get("dir", 1)
        ins = [f for f in fills if f[0] == ("buy" if d > 0 else "sell")]; outs = [f for f in fills if f[0] == ("sell" if d > 0 else "buy")]
        if ins and outs:
            entry = ins[0][1]; ex = outs[-1]; risk = d * (entry - info["stop"])
            how = {"limit": "target", "stop": "stop"}.get(ex[3], "time")
            trades.append({"sym": sym, "gid": info["gid"], "dir": d, "entry_d": ins[0][4][:10], "exit_d": ex[4][:10], "entry": entry, "exit": ex[1],
                           "qty": ins[0][2], "how": how, "R": d * (ex[1] - entry) / risk if risk > 0 else 0, "pnl": d * (ex[1] - entry) * ins[0][2],
                           "t_in": ins[0][4][11:16], "t_out": ex[4][11:16], "rank": info.get("rank"), "score": info.get("score")})
            log(f"{sym}: ปิดแล้ว ({'long' if d > 0 else 'short'} · {how}) R={trades[-1]['R']:+.2f} P&L ${trades[-1]['pnl']:+,.2f}")
        elif not ins:
            log(f"{sym}: คำสั่งซื้อไม่ได้ fill · ลบออก")
        del st["open"][sym]

def run(broker, loader, force_minute=None):
    cfg_all = config(); cfg = cfg_all["scan"]; swing = set(cfg_all["symbols"])
    UJ = load_json("universe.json", {}); no_short = set(UJ.get("no_short", []))
    U = [s for s in UJ.get("symbols", []) if s not in swing]
    st = load_json("dt_state.json", {"open": {}, "scanned": {}})
    st.setdefault("scanned", {}); st.pop("traded", None)
    trades = load_json("dt_trades.json", [])
    acct = broker.account(); clk = broker.clock(); today = clk["today"]
    mine = set(st["open"]) | set(U)
    pos = {k: v for k, v in broker.positions().items() if k in mine and k not in swing}
    reconcile(broker, st, trades, pos)
    st["scanned"] = {d: v for d, v in st["scanned"].items() if d >= today}
    try:
        if not clk["is_open"]:
            return
        minute = force_minute if force_minute is not None else session_minute(clk["now_ny"])
        stale = [s for s in pos if st["open"].get(s, {}).get("entry_day", "") < today]
        for s in stale:
            broker.close(s); log(f"{s}: ตำแหน่งค้างข้ามวัน → ขายทันที")
        if SC.SESSION - minute <= SC.FLAT_BEFORE:
            for s in pos:
                if s not in stale:
                    broker.close(s); log(f"{s}: ใกล้ตลาดปิด (เหลือ {SC.SESSION - minute} นาที) → ขายตามเวลา")
            return
        P = load_json("population_scan.json", {}); champ = P.get("champion")
        if not champ or not U:
            log("ยังไม่มีแชมป์หรือ universe → รัน evolve"); return
        g = champ["g"]
        if today in st["scanned"] or minute < g["M"] or minute > g["M"] + 60:
            return   # สแกนวันละครั้ง ณ นาที M (ถ้า GitHub ช้าเกิน 60 นาทีให้ข้ามวันนั้น)
        days = loader(U, today)
        infos = []
        for sym in U:
            dd = days.get(sym, {}); bars = dd.get(today, [])
            prev = sorted(d for d in dd if d < today)
            pc = dd[prev[-1]][-1][4] if prev and dd[prev[-1]] else None
            if len(bars) >= 2 and bars[0][1] >= cfg["min_price"]:
                infos.append(SC.Info(sym, bars, pc))
        picks = SC.rank(g, infos, exclude=set(pos) | swing, no_short=no_short)
        st["scanned"][today] = [{"sym": x.sym, "score": round(s, 4), "dir": di} for s, x, di in picks]
        log(f"สแกน {len(infos)} ตัว ณ นาทีที่ {g['M']} → " + (", ".join(f"{'L' if di > 0 else 'S'} {x.sym} {s*100:+.1f}%" for s, x, di in picks) or "ไม่มีตัวผ่านเกณฑ์"))
        cap = acct["equity"] * cfg["capital_share"]
        risk_pct = cfg["risk_per_trade_pct"] / 100 * (0.5 if champ.get("probation") else 1)
        for r, (s, x, di) in enumerate(picks, 1):
            if len(st["open"]) >= cfg["max_open_positions"]:
                break
            risk = g["k_stop"] * 3 * x.atr_at[g["M"]]
            try: px = broker.latest_price(x.sym)
            except Exception: px = x.c_at[g["M"]]
            if risk <= 0: continue
            qty = min(math.floor(cap * risk_pct / risk), math.floor(cap * cfg["max_position_pct"] / 100 / px))
            if qty < 1:
                log(f"{x.sym}: ขนาดไม่ถึง 1 หุ้น · ข้าม"); continue
            stop, target = px - di * risk, px + di * g["R"] * risk
            try:
                oid = broker.submit_bracket(x.sym, qty, stop, target, f"pbs-{x.sym}-{today}", tif="day", short=di < 0)
            except Exception as e:
                log(f"{x.sym}: ส่งคำสั่งไม่สำเร็จ: {e}"); continue
            now = clk["now_ny"]
            st["open"][x.sym] = {"gid": champ["id"], "dir": di, "qty": qty, "ref": px, "stop": stop, "target": target, "entry_day": today, "rank": r,
                                 "score": round(s, 4), "submitted": now.isoformat() if hasattr(now, "isoformat") else str(now), "order": oid}
            log(f"{x.sym}: {'ซื้อ (long)' if di > 0 else 'short'} {qty} หุ้น ~${px:.2f} ({s*100:+.1f}%) · stop ${stop:.2f} · target ${target:.2f}")
    finally:
        save_json("dt_state.json", st); save_json("dt_trades.json", trades)

def today_loader(syms, today):
    """แท่ง 5 นาทีของวันนี้ (IEX real-time) + 5 วันก่อนหน้าเพื่อหาราคาปิดเมื่อวาน"""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    start = (dt.datetime.fromisoformat(today + "T09:30").replace(tzinfo=ny) - dt.timedelta(days=6)).astimezone(dt.timezone.utc)
    out = {}
    for i in range(0, len(syms), 100):
        out.update(load_5min_alpaca(syms[i:i + 100], feed="iex", start=start))
    return out

if __name__ == "__main__":
    try:
        run(AlpacaBroker(), today_loader)
        import dashboard; dashboard.build()
    except SystemExit:
        raise
    except Exception:
        log("ERROR\n" + traceback.format_exc()); raise
