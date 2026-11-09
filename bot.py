"""bot.py — บอทเทรดในบัญชี Alpaca **Paper** (เงินจำลอง) วันละ 1 ครั้งหลังตลาด US เปิด

  python bot.py check    ตรวจ key / การเชื่อมต่อ / บัญชีเป็น paper จริงไหม
  python bot.py run      รอบประจำวัน (Task Scheduler เรียกให้อัตโนมัติ)
  python bot.py status   ดูพอร์ตและแชมป์ปัจจุบัน

ความปลอดภัย: บอทนี้ล็อกไว้ที่ paper=True เท่านั้น ไม่มีโหมดเงินจริง
"""
import sys, math, datetime as dt, traceback
import strategy as S
import safety
from common import config, keys, base_url, load_json, save_json, load_bars_alpaca, drop_today_partial, path

def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M} {msg}"
    print(line)
    with open(path("log.txt"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ---------------- broker (แยกเป็นคลาสเพื่อทดสอบด้วย FakeBroker ได้) ----------------
class AlpacaBroker:
    def __init__(self):
        from alpaca.trading.client import TradingClient
        from alpaca.data.historical import StockHistoricalDataClient
        k, s = keys()
        self.t = TradingClient(k, s, paper=True, url_override=base_url())  # ล็อก paper
        self.d = StockHistoricalDataClient(k, s)
        u = getattr(self.t, "_base_url", "paper"); u = getattr(u, "value", str(u))
        assert "paper" in u.lower(), "ไม่ใช่ paper endpoint · หยุดเพื่อความปลอดภัย"

    def account(self):
        a = self.t.get_account()
        return {"equity": float(a.equity), "cash": float(a.cash), "number": a.account_number, "status": str(a.status)}

    def clock(self):
        c = self.t.get_clock()
        return {"is_open": c.is_open, "now_ny": c.timestamp, "today": c.timestamp.date().isoformat()}

    def positions(self):
        return {p.symbol: {"qty": float(p.qty), "avg": float(p.avg_entry_price), "price": float(p.current_price),
                           "upl": float(p.unrealized_pl)} for p in self.t.get_all_positions()}

    def open_orders(self, sym=None):
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[sym] if sym else None, nested=True)
        return self.t.get_orders(filter=req)

    def cancel_orders(self, sym):
        for o in self.open_orders(sym):
            try: self.t.cancel_order_by_id(o.id)
            except Exception: pass

    def close(self, sym):
        self.cancel_orders(sym)
        return self.t.close_position(sym)

    def latest_price(self, sym):
        from alpaca.data.requests import StockLatestTradeRequest
        from alpaca.data.enums import DataFeed
        r = self.d.get_stock_latest_trade(StockLatestTradeRequest(symbol_or_symbols=sym, feed=DataFeed.IEX))
        return float(r[sym].price)

    def submit_bracket(self, sym, qty, stop, target, cid, tif="gtc", short=False):
        from alpaca.trading.requests import MarketOrderRequest, TakeProfitRequest, StopLossRequest
        from alpaca.trading.enums import OrderSide, TimeInForce, OrderClass
        o = self.t.submit_order(MarketOrderRequest(symbol=sym, qty=qty, side=OrderSide.SELL if short else OrderSide.BUY,
                                                   time_in_force=TimeInForce.DAY if tif == "day" else TimeInForce.GTC,
                                                   order_class=OrderClass.BRACKET, client_order_id=cid,
                                                   take_profit=TakeProfitRequest(limit_price=round(target, 2)),
                                                   stop_loss=StopLossRequest(stop_price=round(stop, 2))))
        return str(o.id)

    def fills(self, sym, after):
        """คำสั่งที่ fill แล้วของหุ้นนี้หลังเวลา after → [(side, price, qty, type, filled_at)]"""
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        out = []
        after_dt = dt.datetime.fromisoformat(after) - dt.timedelta(minutes=5)
        for o in self.t.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, symbols=[sym], after=after_dt, nested=True, limit=200)):
            for x in [o] + list(o.legs or []):
                if x.filled_at and x.filled_avg_price:
                    out.append((str(x.side.value), float(x.filled_avg_price), float(x.filled_qty), str(x.order_type.value), x.filled_at.isoformat()))
        return sorted(out, key=lambda r: r[4])

# ---------------- รอบประจำวัน ----------------
def run(broker, bars_loader, force=False):
    cfg = config()
    st = load_json("state.json", {"open": {}, "started": None})
    trades = load_json("trades.json", [])
    acct = broker.account(); clk = broker.clock(); today = clk["today"]
    st["started"] = st["started"] or today
    eq = load_json("equity.json", [])
    if not eq or eq[-1]["date"] != today:
        eq.append({"date": today, "equity": acct["equity"], "cash": acct["cash"]})
    else:
        eq[-1].update(equity=acct["equity"], cash=acct["cash"])
    save_json("equity.json", eq)
    log(f"equity ${acct['equity']:,.2f} · cash ${acct['cash']:,.2f} · ตลาด{'เปิด' if clk['is_open'] else 'ปิด'}")

    bars, feed = bars_loader(cfg["symbols"])
    bars = drop_today_partial(bars, clk["is_open"], today)
    save_json("bars.json", {"feed": feed, "updated": today, "bars": bars})
    inds = {s: S.Ind(r) for s, r in bars.items() if r}
    pos = broker.positions()

    # 1) ตรวจ trade ที่ปิดไปแล้ว (โดน stop / ถึง target) และปิดตามเวลา (ถือครบ H วัน)
    for sym, info in list(st["open"].items()):
        if sym not in pos:
            sells = [f for f in broker.fills(sym, info["submitted"]) if f[0] == "sell"]
            buys = [f for f in broker.fills(sym, info["submitted"]) if f[0] == "buy"]
            if not buys:  # ไม่เคย fill (เช่นถูกยกเลิก)
                log(f"{sym}: คำสั่งซื้อไม่ได้ fill · ลบออก"); del st["open"][sym]; continue
            if sells:
                ex = sells[-1]; entry = buys[0][1]; risk = entry - info["stop"]
                how = {"limit": "target", "stop": "stop"}.get(ex[3], "time")
                trades.append({"sym": sym, "gid": info["gid"], "entry_d": buys[0][4][:10], "exit_d": ex[4][:10], "entry": entry,
                               "exit": ex[1], "qty": buys[0][2], "how": how, "R": (ex[1] - entry) / risk if risk > 0 else 0,
                               "pnl": (ex[1] - entry) * buys[0][2]})
                log(f"{sym}: ปิดแล้ว ({how}) R={trades[-1]['R']:+.2f} P&L ${trades[-1]['pnl']:+,.2f}")
            del st["open"][sym]
        else:
            ind = inds.get(sym)
            held = sum(1 for d in ind.d if d >= info["entry_day"]) if ind else 0
            if held >= info["H"] and clk["is_open"]:
                broker.close(sym); log(f"{sym}: ถือครบ {info['H']} วัน → ปิดตามเวลา")
                info["closing"] = True
    save_json("trades.json", trades)

    # 2) เปิด trade ใหม่ตามกฎของแชมป์
    P = load_json("population.json", {})
    champ = P.get("champion")
    if not champ:
        log("ยังไม่มีแชมป์ → รัน evolve.py ก่อน"); save_json("state.json", st); return
    if not clk["is_open"] and not force:
        log("ตลาดปิด: ไม่ส่งคำสั่งใหม่"); save_json("state.json", st); return
    # kill switch / โหมด: ตรวจก่อนเปิดไม้ใหม่ทุกครั้ง (ไม้ที่ถืออยู่ใช้ stop เดิม)
    mode = safety.trading_mode(cfg)
    if safety.check(today, cfg, mode, log, swing_trades=trades):
        log("kill switch ทำงาน: ไม่เปิดไม้ใหม่"); save_json("state.json", st); return
    g = champ["g"]; risk_pct = safety.risk_pct(cfg, cfg, mode) * (0.5 if champ.get("probation") else 1)
    cap = acct["equity"] * cfg.get("capital_share", 1.0)          # เงินส่วนของบอท swing
    n_open = len([s for s in pos if s in cfg["symbols"]])
    for sym, ind in inds.items():
        i = len(ind.c) - 1
        if sym in pos or sym in st["open"] or n_open >= cfg["max_open_positions"]:
            continue
        if not S.signal(g, ind, i):
            continue
        try:
            px = broker.latest_price(sym)
        except Exception:
            px = ind.c[i]
        atr = ind.atr[i]; risk = g["k_stop"] * atr
        qty = math.floor(cap * risk_pct / risk)
        qty = min(qty, math.floor(cap * cfg["max_position_pct"] / 100 / px))
        qty = safety.cap_notional(qty, px, cfg, mode)   # live: จำกัด $ ต่อไม้
        if qty < 1:
            log(f"{sym}: มีสัญญาณแต่ขนาดไม่ถึง 1 หุ้น · ข้าม"); continue
        stop, target = px - risk, px + g["R"] * risk
        cid = f"pb-{sym}-{today}"
        try:
            oid = broker.submit_bracket(sym, qty, stop, target, cid)
        except Exception as e:
            log(f"{sym}: ส่งคำสั่งไม่สำเร็จ: {e}"); continue
        st["open"][sym] = {"gid": champ["id"], "qty": qty, "ref": px, "stop": stop, "target": target, "H": g["H"],
                           "entry_day": today, "submitted": clk["now_ny"].isoformat() if hasattr(clk["now_ny"], "isoformat") else str(clk["now_ny"]), "order": oid}
        n_open += 1
        log(f"{sym}: ซื้อ {qty} หุ้น ~${px:.2f} · stop ${stop:.2f} · target ${target:.2f} · ถือ ≤ {g['H']} วัน · กฎ {champ['id']}")
    save_json("state.json", st)

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    try:
        if cmd == "check":
            b = AlpacaBroker(); a = b.account(); c = b.clock()
            print(f"endpoint: {base_url()}/v2")
            print(f"เชื่อมต่อสำเร็จ · บัญชี {a['number']} (paper) · equity ${a['equity']:,.2f} · ตลาด{'เปิด' if c['is_open'] else 'ปิด'}")
            bars, feed = load_bars_alpaca(config()["symbols"], years=1)
            print(f"โหลดราคาได้ {len(bars)} หุ้น · feed {feed} · ล่าสุด {max(r[0] for v in bars.values() for r in v)}")
        elif cmd == "run":
            b = AlpacaBroker()
            run(b, lambda syms: load_bars_alpaca(syms, years=2), force="--force" in sys.argv)
            import dashboard; dashboard.build()
        elif cmd == "status":
            b = AlpacaBroker(); print(b.account()); print(b.positions())
            P = load_json("population.json", {}); c = P.get("champion")
            print("แชมป์:", c["id"] if c else "-", "·", c.get("desc", "") if c else "")
    except SystemExit:
        raise
    except Exception:
        log("ERROR\n" + traceback.format_exc()); raise

if __name__ == "__main__":
    main()
