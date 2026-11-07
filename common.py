"""โหลดค่าตั้งค่า, API key และข้อมูลราคา (ใช้ร่วมกันทุกสคริปต์)"""
import json, os, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

def path(*p):
    return os.path.join(DATA, *p)

def load_json(name, default):
    try:
        with open(path(name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default

def save_json(name, obj):
    tmp = path(name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path(name))

def config():
    with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
        return json.load(f)

def env():
    e = {}
    p = os.path.join(HERE, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); e[k.strip()] = v.strip().strip('"').strip("'")
    return e

def base_url():
    """endpoint ของ trading API · ต้องเป็น paper เท่านั้น (alpaca-py เติม /v2 เอง จึงตัดออก)"""
    u = env().get("APCA_API_BASE_URL") or os.environ.get("APCA_API_BASE_URL") or "https://paper-api.alpaca.markets"
    u = u.rstrip("/")
    if u.endswith("/v2"): u = u[:-3]
    if "paper" not in u.lower():
        raise SystemExit("APCA_API_BASE_URL ไม่ใช่ paper endpoint · บอทหยุดเพื่อความปลอดภัย")
    return u

def keys():
    """อ่าน key จากไฟล์ .env ในโฟลเดอร์นี้ (ไม่ส่งไปที่ไหนนอกจาก Alpaca)"""
    env_ = env()
    k = env_.get("APCA_API_KEY_ID") or os.environ.get("APCA_API_KEY_ID")
    s = env_.get("APCA_API_SECRET_KEY") or os.environ.get("APCA_API_SECRET_KEY")
    if not k or not s or "ใส่" in k:
        raise SystemExit("ไม่พบ API key: เปิดไฟล์ .env แล้วใส่ APCA_API_KEY_ID และ APCA_API_SECRET_KEY ของบัญชี Paper")
    return k, s

def load_bars_alpaca(symbols, years=3):
    """แท่งรายวันแบบ adjusted จาก Alpaca (SIP ย้อนหลัง >15 นาที ใช้ได้ฟรี ถ้าไม่ได้จะลอง IEX)"""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.data.enums import Adjustment, DataFeed
    k, s = keys()
    cli = StockHistoricalDataClient(k, s)
    end = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=20)
    start = end - dt.timedelta(days=int(365.25 * years))
    last_err = None
    for feed in (DataFeed.SIP, DataFeed.IEX):
        try:
            req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame.Day, start=start, end=end,
                                   adjustment=Adjustment.ALL, feed=feed)
            res = cli.get_stock_bars(req).data
            out = {}
            for sym in symbols:
                rows = []
                for b in res.get(sym, []):
                    d = b.timestamp.astimezone(dt.timezone.utc).date().isoformat()  # แท่งวันเริ่ม 00:00 NY = 04/05:00 UTC วันเดียวกัน
                    rows.append((d, float(b.open), float(b.high), float(b.low), float(b.close)))
                out[sym] = rows
            if all(len(v) > 200 for v in out.values()):
                return out, feed.value
        except Exception as e:  # noqa
            last_err = e
    raise SystemExit(f"โหลดราคาจาก Alpaca ไม่สำเร็จ: {last_err}")

def drop_today_partial(bars, market_open_today, today):
    """ถ้าตลาดเปิดอยู่ แท่งของวันนี้ยังไม่จบ ห้ามใช้สร้างสัญญาณ"""
    if not market_open_today:
        return bars
    return {s: [r for r in rows if r[0] < today] for s, rows in bars.items()}

def load_bars_csv(folder, symbols):
    """สำหรับทดสอบ offline: CSV date,open,high,low,close"""
    import csv
    out = {}
    for s in symbols:
        rows = []
        for r in csv.DictReader(open(os.path.join(folder, f"{s}.csv"))):
            rows.append((r["date"], float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])))
        out[s] = rows
    return out

# ---------------- Day trade: แท่ง 5 นาที ----------------
def to_days(rows):
    """rows = [(datetime_utc, o,h,l,c,v)] → {date: [(m,o,h,l,c,v)]} เฉพาะช่วงตลาดปกติ 9:30–16:00 NY"""
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York"); out = {}
    for ts, o, h, l, c, v in rows:
        t = ts.astimezone(ny); m = (t.hour * 60 + t.minute) - (9 * 60 + 30)
        if 0 <= m < 390:
            out.setdefault(t.date().isoformat(), []).append((m, o, h, l, c, v))
    return out

def load_5min_alpaca(symbols, days_back=180, feed="sip", start=None):
    """แท่ง 5 นาที · feed sip = ย้อนหลัง (ต้องเก่ากว่า 15 นาที) · iex = real-time ของวันนี้"""
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    from alpaca.data.enums import Adjustment, DataFeed
    k, s = keys(); cli = StockHistoricalDataClient(k, s)
    now = dt.datetime.now(dt.timezone.utc)
    end = now - dt.timedelta(minutes=16) if feed == "sip" else now
    st = start or (now - dt.timedelta(days=days_back))
    req = StockBarsRequest(symbol_or_symbols=symbols, timeframe=TimeFrame(5, TimeFrameUnit.Minute), start=st, end=end,
                           adjustment=Adjustment.ALL, feed=DataFeed.SIP if feed == "sip" else DataFeed.IEX)
    res = cli.get_stock_bars(req).data
    return {sym: to_days([(b.timestamp, float(b.open), float(b.high), float(b.low), float(b.close), float(b.volume or 0))
                          for b in res.get(sym, [])]) for sym in symbols}
