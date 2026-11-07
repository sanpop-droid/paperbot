"""dt.py — บอท Day trade (ซื้อ-ขายจบในวัน) บนบัญชี Alpaca **Paper**
GitHub Actions เรียกทุก 15 นาทีระหว่างตลาดเปิด:  python dt.py run
  1) บันทึก trade ที่ปิดไปแล้ว (โดน stop / ถึง target / ปิดตามเวลา)
  2) ถ้าเหลือเวลาก่อนตลาดปิด ≤ 35 นาที → ปิดทุกตำแหน่งของบอทนี้
  3) ถ้ายังไม่ถึง → ดูแท่ง 5 นาทีของวันนี้ แล้วเปิด trade ตามกฎของแชมป์ (1 trade/หุ้น/วัน)
ใช้หุ้นและเงินคนละส่วนกับบอท swing (bot.py) ดู config.json → "day"
"""
import sys, math, datetime as dt, traceback
import strategy as S, daystrat as D
from common import config, load_json, save_json, load_5min_alpaca, path
from bot import AlpacaBroker

def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M} [day] {msg}"
    print(line)
    with open(path("log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

def session_minute(now_ny):
    return now_ny.hour * 60 + now_ny.minute - (9 * 60 + 30)

def reconcile(broker, st, trades, pos):
    for sym, info in list(st["open"].items()):
        if sym in pos: continue
        fills = broker.fills(sym, info["submitted"])
        buys = [f for f in fills if f[0] == "buy"]; sells = [f for f in fills if f[0] == "sell"]
        if buys and sells:
            entry = buys[0][1]; ex = sells[-1]; risk = entry - info["stop"]
            how = {"limit": "target", "stop": "stop"}.get(ex[3], "time")
            trades.append({"sym": sym, "gid": info["gid"], "entry_d": buys[0][4][:10], "exit_d": ex[4][:10], "entry": entry, "exit": ex[1],
                           "qty": buys[0][2], "how": how, "R": (ex[1] - entry) / risk if risk > 0 else 0, "pnl": (ex[1] - entry) * buys[0][2],
                           "t_in": buys[0][4][11:16], "t_out": ex[4][11:16]})
            log(f"{sym}: ปิดแล้ว ({how}) R={trades[-1]['R']:+.2f} P&L ${trades[-1]['pnl']:+,.2f}")
        elif not buys:
            log(f"{sym}: คำสั่งซื้อไม่ได้ fill · ลบออก")
        del st["open"][sym]

def run(broker, bars_loader, force_minute=None):
    cfg = config()["day"]; syms = cfg["symbols"]
    st = load_json("dt_state.json", {"open": {}, "traded": {}})
    trades = load_json("dt_trades.json", [])
    acct = broker.account(); clk = broker.clock(); today = clk["today"]
    pos = {k: v for k, v in broker.positions().items() if k in syms}
    reconcile(broker, st, trades, pos)
    st["traded"] = {d: v for d, v in st["traded"].items() if d >= today}  # เก็บแค่วันนี้
    done = set(st["traded"].get(today, []))
    try:
        if not clk["is_open"]:
            return  # ตลาดปิด: เงียบไว้ ไม่ให้ log ยาวเกินจำเป็น
        minute = force_minute if force_minute is not None else session_minute(clk["now_ny"])
        # ตำแหน่งค้างจากวันก่อน (ถ้ารอบปิดท้ายวันพลาด) หรือใกล้ปิดตลาด → ปิดทั้งหมด
        stale = [s for s in pos if st["open"].get(s, {}).get("entry_day", today) < today or s not in st["open"]]
        for s in stale:
            broker.close(s); log(f"{s}: ตำแหน่งค้างข้ามวัน → ปิดทันที")
        if D.SESSION - minute <= D.FLAT_BEFORE:
            for s in pos:
                if s not in stale:
                    broker.close(s); log(f"{s}: ใกล้ตลาดปิด (เหลือ {D.SESSION - minute} นาที) → ปิดตามเวลา")
            return
        P = load_json("population_dt.json", {}); champ = P.get("champion")
        if not champ:
            log("ยังไม่มีแชมป์ day trade → รอ evolve_dt.py"); return
        g = champ["g"]
        if minute > g["last_entry"]:
            return
        cap = acct["equity"] * cfg["capital_share"]
        risk_pct = cfg["risk_per_trade_pct"] / 100 * (0.5 if champ.get("probation") else 1)
        days = bars_loader(syms, today)
        n_open = len(pos)
        for sym in syms:
            if sym in pos or sym in done or sym in st["open"] or n_open >= cfg["max_open_positions"]:
                continue
            dd = days.get(sym, {}); bars = dd.get(today, [])
            if len(bars) < 3: continue
            prev = sorted(d for d in dd if d < today)
            pc = dd[prev[-1]][-1][4] if prev and dd[prev[-1]] else None   # ราคาปิดเมื่อวาน (ใช้กับตัวกรอง gap)
            ok, ref, risk = D.decide(g, D.Day(bars, pc), minute)
            if not ok or risk <= 0: continue
            try: px = broker.latest_price(sym)
            except Exception: px = ref
            qty = min(math.floor(cap * risk_pct / risk), math.floor(cap * cfg["max_position_pct"] / 100 / px))
            if qty < 1: continue
            stop, target = px - risk, px + g["R"] * risk
            try:
                oid = broker.submit_bracket(sym, qty, stop, target, f"pbd-{sym}-{today}", tif="day")
            except Exception as e:
                log(f"{sym}: ส่งคำสั่งไม่สำเร็จ: {e}"); continue
            now = clk["now_ny"]
            st["open"][sym] = {"gid": champ["id"], "qty": qty, "ref": px, "stop": stop, "target": target, "entry_day": today,
                               "submitted": now.isoformat() if hasattr(now, "isoformat") else str(now), "order": oid}
            st["traded"].setdefault(today, []).append(sym); n_open += 1
            log(f"{sym}: ซื้อ {qty} หุ้น ~${px:.2f} · stop ${stop:.2f} · target ${target:.2f} · นาทีที่ {minute} · กฎ {champ['id']}")
    finally:
        save_json("dt_state.json", st); save_json("dt_trades.json", trades)

def today_loader(syms, today):
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    start = (dt.datetime.fromisoformat(today + "T09:30").replace(tzinfo=ny) - dt.timedelta(days=6)).astimezone(dt.timezone.utc)  # รวมวันก่อนหน้าเพื่อหาราคาปิดเมื่อวาน
    return load_5min_alpaca(syms, feed="iex", start=start)

if __name__ == "__main__":
    try:
        run(AlpacaBroker(), today_loader)
        import dashboard; dashboard.build()
    except SystemExit:
        raise
    except Exception:
        log("ERROR\n" + traceback.format_exc()); raise
