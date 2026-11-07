"""daystrat.py — กลยุทธ์ Day trade บนแท่ง 5 นาที (ซื้อ-ขายจบในวัน)

ข้อมูล: days = {symbol: {"YYYY-MM-DD": [(m, o, h, l, c, v), ...]}}  m = นาทีนับจาก 9:30 (0, 5, ..., 385)
บอทเช็กทุก 15 นาที → backtest ก็ตัดสินใจเฉพาะ "จุดตัดสินใจ" ทุก 15 นาทีเหมือนกัน (DECIDE_EVERY)
ประเภทกฎ
  orb  = Opening Range Breakout: ราคาปิดทะลุจุดสูงสุดของช่วงแรก (15–60 นาที) → ซื้อ
  vwap = ราคาตัดขึ้นเหนือ VWAP (ราคาเฉลี่ยถ่วงปริมาณของวันนี้) → ซื้อ
  momo = Intraday momentum: ช่วงแรกของวันขึ้นแรงเกิน th → ซื้อตาม (แรงซื้อเช้ามักต่อเนื่อง)
  dip  = Mean reversion: ราคาร่วงต่ำกว่า VWAP เกิน dev × ATR แล้วแท่งล่าสุดเป็นแท่งเขียว → ซื้อรับการเด้ง
ตัวกรองทุกประเภท: gap = (ราคาเปิด ÷ ราคาปิดเมื่อวาน − 1) ต้องอยู่ในช่วงที่ GA เลือก
ออก: bracket stop/target ตั้งที่ Alpaca + ปิดทั้งหมดก่อนตลาดปิด (FLAT_BEFORE นาที)
"""
import math, bisect
import strategy as S

SESSION = 390          # 9:30–16:00 = 390 นาที
DECIDE_EVERY = 15      # บอทรันทุก 15 นาที
FLAT_BEFORE = 35       # ปิดทุกตำแหน่งเมื่อเหลือเวลา ≤ 35 นาที (มีโอกาสรันได้ 2 รอบ)

TYPES = ["orb", "vwap", "momo", "dip"]
RANGES = {
    "or_min": (15, 60, True),      # orb: ความยาว opening range (นาที, ปัดเป็น 5)
    "k_stop": (0.3, 1.5, False),   # orb: stop = k × ความกว้าง OR · vwap: stop = k × ATR5 × 3
    "R": (0.5, 3.0, False),        # target กี่ R
    "last_entry": (60, 300, True), # ไม่เปิด trade ใหม่หลังนาทีที่เท่านี้ของวัน
    "min_gap": (0, 3, False),      # vwap: ต้องเคยอยู่ใต้ VWAP อย่างน้อยกี่จุดตัดสินใจ (0–3)
    "th": (0.002, 0.03, False),    # momo: ช่วง or_min นาทีแรกต้องขึ้นอย่างน้อย th (0.2%–3%)
    "dev": (0.5, 3.0, False),      # dip: ต่ำกว่า VWAP กี่เท่าของ 3×ATR(5 นาที)
    "gap_lo": (-0.05, 0.05, False),  # ตัวกรอง gap: ต้อง ≥ gap_lo (−5% = แทบไม่กรอง)
    "gap_hi": (-0.05, 0.05, False),  # ตัวกรอง gap: ต้อง ≤ gap_hi (+5% = แทบไม่กรอง)
}
DEFAULTS = {"th": 0.005, "dev": 1.0, "gap_lo": -0.05, "gap_hi": 0.05}

def random_genome(rng):
    g = {"type": rng.choice(TYPES)}
    for k, (lo, hi, isint) in RANGES.items():
        g[k] = rng.randint(lo, hi) if isint else round(rng.uniform(lo, hi), 2)
    return fix(g)

def fix(g):
    for k, v in DEFAULTS.items():
        g.setdefault(k, v)
    for k, (lo, hi, isint) in RANGES.items():
        v = min(hi, max(lo, g[k])); g[k] = int(round(v)) if isint else round(v, 2)
    g["or_min"] = max(15, 5 * round(g["or_min"] / 5))
    g["last_entry"] = max(g["or_min"] + 15, g["last_entry"])
    if g["gap_lo"] > g["gap_hi"]:
        g["gap_lo"], g["gap_hi"] = g["gap_hi"], g["gap_lo"]
    return g

def mutate(g, rng, rate=0.3, scale=0.15):
    c = fix(dict(g))
    for k, (lo, hi, isint) in RANGES.items():
        if rng.random() < rate:
            c[k] = c[k] + rng.gauss(0, (hi - lo) * scale)
    return fix(c)

def crossover(a, b, rng):
    a, b = fix(dict(a)), fix(dict(b))
    return fix({k: (a[k] if rng.random() < 0.5 else b[k]) for k in a})

def gap_on(g):
    return g["gap_lo"] > -0.045 or g["gap_hi"] < 0.045

def gid(g):
    g = fix(dict(g))
    core = {"orb": f"or{g['or_min']}", "vwap": f"gap{g['min_gap']:.0f}", "momo": f"or{g['or_min']}-th{g['th']*100:.1f}",
            "dip": f"dev{g['dev']:.1f}"}[g["type"]]
    gf = f"-G{g['gap_lo']*100:+.0f}..{g['gap_hi']*100:+.0f}" if gap_on(g) else ""
    return f"{g['type']}-{core}-k{g['k_stop']:.2f}-R{g['R']:.1f}-L{g['last_entry']}{gf}"

def describe_th(g):
    g = fix(dict(g))
    t = {"orb": f"ซื้อเมื่อราคาปิดทะลุจุดสูงสุดของ {g['or_min']} นาทีแรก · stop {g['k_stop']:.2f} × ความกว้างช่วงนั้น",
         "vwap": f"ซื้อเมื่อราคาตัดขึ้นเหนือ VWAP (หลังอยู่ใต้ ≥ {g['min_gap']:.0f} รอบ) · stop {g['k_stop']:.2f} × 3 ATR(5 นาที)",
         "momo": f"ซื้อเมื่อ {g['or_min']} นาทีแรกขึ้นแล้ว ≥ {g['th']*100:.1f}% (ตามแรงซื้อเช้า) · stop {g['k_stop']:.2f} × 3 ATR(5 นาที)",
         "dip": f"ซื้อเมื่อราคาต่ำกว่า VWAP เกิน {g['dev']:.1f} × 3 ATR แล้วแท่งล่าสุดปิดเขียว (รับการเด้ง) · stop {g['k_stop']:.2f} × 3 ATR(5 นาที)"}[g["type"]]
    if gap_on(g):
        t += f" · เฉพาะวันที่ gap เปิด {g['gap_lo']*100:+.1f}% ถึง {g['gap_hi']*100:+.1f}%"
    return f"{t} · target {g['R']:.1f}R · เปิด trade ได้ถึงนาทีที่ {g['last_entry']} · ปิดทุกตัวก่อนตลาดปิด {FLAT_BEFORE} นาที"

# ---------------- ตัวช่วยต่อวัน ----------------
class Day:
    def __init__(self, bars, prev_close=None):
        self.b = bars  # [(m,o,h,l,c,v)]
        self.prev_close = prev_close
        self.gap = (bars[0][1] / prev_close - 1) if prev_close else 0.0
        self.m = [x[0] for x in bars]
        pv = v = 0.0; self.vwap = []
        for (_, o, h, l, c, vol) in bars:
            tp = (h + l + c) / 3; pv += tp * vol; v += vol
            self.vwap.append(pv / v if v > 0 else c)
        tr = [bars[0][2] - bars[0][3]] + [max(bars[i][2] - bars[i][3], abs(bars[i][2] - bars[i-1][4]), abs(bars[i][3] - bars[i-1][4])) for i in range(1, len(bars))]
        self.atr = [sum(tr[max(0, i - 13):i + 1]) / (i + 1 - max(0, i - 13)) for i in range(len(bars))]

    def idx_done_by(self, minute):
        """index ของแท่งสุดท้ายที่ "ปิดแล้ว" ณ เวลา minute (แท่ง m จบที่ m+5)"""
        return bisect.bisect_right(self.m, minute - 5) - 1

def decide(g, day, minute, prev_minute=None):
    """สัญญาณซื้อ ณ จุดตัดสินใจ minute → (True, ref_price, risk) หรือ (False, None, None)"""
    if minute > g["last_entry"] or minute > SESSION - FLAT_BEFORE:
        return False, None, None
    g = fix(dict(g)) if "gap_lo" not in g else g
    if day.prev_close and not (g["gap_lo"] <= day.gap <= g["gap_hi"]):
        return False, None, None
    i = day.idx_done_by(minute)
    if i < 0: return False, None, None
    c = day.b[i][4]
    if g["type"] == "momo":
        n = g["or_min"] // 5
        if i < n - 1 or minute < g["or_min"]: return False, None, None
        r = day.b[n - 1][4] / day.b[0][1] - 1
        return (True, c, g["k_stop"] * 3 * day.atr[i]) if r >= g["th"] and c > day.vwap[i] else (False, None, None)
    if g["type"] == "dip":
        a = day.atr[i]; b = day.b[i]
        if c < day.vwap[i] - g["dev"] * 3 * a and b[4] > b[1]:
            return True, c, g["k_stop"] * 3 * a
        return False, None, None
    if g["type"] == "orb":
        n = g["or_min"] // 5
        if i < n: return False, None, None
        orh = max(x[2] for x in day.b[:n]); orl = min(x[3] for x in day.b[:n])
        if c > orh and orh > orl:
            return True, c, g["k_stop"] * (orh - orl)
        return False, None, None
    # vwap cross: ตอนนี้อยู่เหนือ และ ณ จุดตัดสินใจก่อนหน้า (ย้อนไป min_gap รอบ) อยู่ใต้
    if c <= day.vwap[i]: return False, None, None
    gap = max(1, int(round(g["min_gap"])))
    for k in range(1, gap + 1):
        j = day.idx_done_by(minute - DECIDE_EVERY * k)
        if j < 0 or day.b[j][4] >= day.vwap[j]:
            return False, None, None
    return True, c, g["k_stop"] * 3 * day.atr[i]

_CACHE = {}

def backtest(g, days, start=None, end=None, slip=0.0005, decide_offset=0):
    """1 trade ต่อหุ้นต่อวันสูงสุด · เข้าที่ราคาเปิดของแท่งถัดไป · stop ก่อนถ้าชนทั้งคู่ · ปิดตามเวลาเมื่อเหลือ ≤ FLAT_BEFORE นาที"""
    trades = []
    for sym, dd in days.items():
        prev = None
        for d in sorted(dd):
            bars = dd[d]
            pc, prev = prev, (bars[-1][4] if bars else prev)
            if (start and d < start) or (end and d > end) or len(bars) < 20:
                continue
            key = (sym, d, len(bars))
            day = _CACHE.get(key)
            if day is None:
                day = _CACHE[key] = Day(bars, pc)
            gg = fix(dict(g))
            for minute in range(DECIDE_EVERY + decide_offset, SESSION, DECIDE_EVERY):
                ok, ref, risk = decide(gg, day, minute)
                if not ok or risk <= 0: continue
                e = day.idx_done_by(minute) + 1
                if e >= len(bars): break
                entry = bars[e][1] * (1 + slip); stop, target = entry - risk, entry + gg["R"] * risk
                flat_m = next((mm for mm in range(minute, SESSION + 1, DECIDE_EVERY) if mm >= SESSION - FLAT_BEFORE), SESSION)
                exit_px, how = None, "time"
                for j in range(e, len(bars)):
                    m, o, h, l, c, v = bars[j]
                    if m >= flat_m: exit_px = o; break
                    if j > e and o <= stop: exit_px, how = o, "stop"; break
                    if l <= stop: exit_px, how = stop, "stop"; break
                    if h >= target: exit_px, how = target, "target"; break
                if exit_px is None: exit_px = bars[-1][4]
                exit_px *= (1 - slip)
                trades.append({"sym": sym, "sig": d, "entry_d": d, "exit_d": d, "entry": entry, "exit": exit_px, "how": how,
                               "R": (exit_px - entry) / risk, "ret": exit_px / entry - 1, "open": False})
                break  # 1 trade/หุ้น/วัน
    return trades

def buy_hold_intraday(days, start=None, end=None):
    """เทียบ: ซื้อตอนเปิด ขายตอนปิดทุกวัน (เฉลี่ยต่อวัน)"""
    r = [bars[-1][4] / bars[0][1] - 1 for dd in days.values() for d, bars in dd.items()
         if bars and (not start or d >= start) and (not end or d <= end)]
    return sum(r) / len(r) if r else 0.0
