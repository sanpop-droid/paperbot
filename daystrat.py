"""daystrat.py — กลยุทธ์ Day trade บนแท่ง 5 นาที (ซื้อ-ขายจบในวัน)

ข้อมูล: days = {symbol: {"YYYY-MM-DD": [(m, o, h, l, c, v), ...]}}  m = นาทีนับจาก 9:30 (0, 5, ..., 385)
บอทเช็กทุก 15 นาที → backtest ก็ตัดสินใจเฉพาะ "จุดตัดสินใจ" ทุก 15 นาทีเหมือนกัน (DECIDE_EVERY)
ประเภทกฎ
  orb  = Opening Range Breakout: ราคาปิดทะลุจุดสูงสุดของช่วงแรก (15–60 นาที) → ซื้อ
  vwap = ราคาตัดขึ้นเหนือ VWAP (ราคาเฉลี่ยถ่วงปริมาณของวันนี้) → ซื้อ
ออก: bracket stop/target ตั้งที่ Alpaca + ปิดทั้งหมดก่อนตลาดปิด (FLAT_BEFORE นาที)
"""
import math
import strategy as S

SESSION = 390          # 9:30–16:00 = 390 นาที
DECIDE_EVERY = 15      # บอทรันทุก 15 นาที
FLAT_BEFORE = 35       # ปิดทุกตำแหน่งเมื่อเหลือเวลา ≤ 35 นาที (มีโอกาสรันได้ 2 รอบ)

TYPES = ["orb", "vwap"]
RANGES = {
    "or_min": (15, 60, True),      # orb: ความยาว opening range (นาที, ปัดเป็น 5)
    "k_stop": (0.3, 1.5, False),   # orb: stop = k × ความกว้าง OR · vwap: stop = k × ATR5 × 3
    "R": (0.5, 3.0, False),        # target กี่ R
    "last_entry": (60, 300, True), # ไม่เปิด trade ใหม่หลังนาทีที่เท่านี้ของวัน
    "min_gap": (0, 3, False),      # vwap: ต้องเคยอยู่ใต้ VWAP อย่างน้อยกี่จุดตัดสินใจ (0–3)
}

def random_genome(rng):
    g = {"type": rng.choice(TYPES)}
    for k, (lo, hi, isint) in RANGES.items():
        g[k] = rng.randint(lo, hi) if isint else round(rng.uniform(lo, hi), 2)
    return fix(g)

def fix(g):
    for k, (lo, hi, isint) in RANGES.items():
        v = min(hi, max(lo, g[k])); g[k] = int(round(v)) if isint else round(v, 2)
    g["or_min"] = max(15, 5 * round(g["or_min"] / 5))
    g["last_entry"] = max(g["or_min"] + 15, g["last_entry"])
    return g

def mutate(g, rng, rate=0.3):
    c = dict(g)
    for k, (lo, hi, isint) in RANGES.items():
        if rng.random() < rate:
            c[k] = c[k] + rng.gauss(0, (hi - lo) * 0.15)
    return fix(c)

def crossover(a, b, rng):
    return fix({k: (a[k] if rng.random() < 0.5 else b[k]) for k in a})

def gid(g):
    core = f"or{g['or_min']}" if g["type"] == "orb" else f"gap{g['min_gap']:.0f}"
    return f"{g['type']}-{core}-k{g['k_stop']:.2f}-R{g['R']:.1f}-L{g['last_entry']}"

def describe_th(g):
    t = (f"ซื้อเมื่อราคาปิดทะลุจุดสูงสุดของ {g['or_min']} นาทีแรก · stop {g['k_stop']:.2f} × ความกว้างช่วงนั้น"
         if g["type"] == "orb" else
         f"ซื้อเมื่อราคาตัดขึ้นเหนือ VWAP (หลังอยู่ใต้ ≥ {g['min_gap']:.0f} รอบ) · stop {g['k_stop']:.2f} × 3 ATR(5 นาที)")
    return f"{t} · target {g['R']:.1f}R · เปิด trade ได้ถึงนาทีที่ {g['last_entry']} · ปิดทุกตัวก่อนตลาดปิด {FLAT_BEFORE} นาที"

# ---------------- ตัวช่วยต่อวัน ----------------
class Day:
    def __init__(self, bars):
        self.b = bars  # [(m,o,h,l,c,v)]
        self.m = [x[0] for x in bars]
        pv = v = 0.0; self.vwap = []
        for (_, o, h, l, c, vol) in bars:
            tp = (h + l + c) / 3; pv += tp * vol; v += vol
            self.vwap.append(pv / v if v > 0 else c)
        tr = [bars[0][2] - bars[0][3]] + [max(bars[i][2] - bars[i][3], abs(bars[i][2] - bars[i-1][4]), abs(bars[i][3] - bars[i-1][4])) for i in range(1, len(bars))]
        self.atr = [sum(tr[max(0, i - 13):i + 1]) / (i + 1 - max(0, i - 13)) for i in range(len(bars))]

    def idx_done_by(self, minute):
        """index ของแท่งสุดท้ายที่ "ปิดแล้ว" ณ เวลา minute (แท่ง m จบที่ m+5)"""
        k = -1
        for i, m in enumerate(self.m):
            if m + 5 <= minute: k = i
            else: break
        return k

def decide(g, day, minute, prev_minute=None):
    """สัญญาณซื้อ ณ จุดตัดสินใจ minute → (True, ref_price, risk) หรือ (False, None, None)"""
    if minute > g["last_entry"] or minute > SESSION - FLAT_BEFORE:
        return False, None, None
    i = day.idx_done_by(minute)
    if i < 0: return False, None, None
    c = day.b[i][4]
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

def backtest(g, days, start=None, end=None, slip=0.0005, decide_offset=0):
    """1 trade ต่อหุ้นต่อวันสูงสุด · เข้าที่ราคาเปิดของแท่งถัดไป · stop ก่อนถ้าชนทั้งคู่ · ปิดตามเวลาเมื่อเหลือ ≤ FLAT_BEFORE นาที"""
    trades = []
    for sym, dd in days.items():
        for d, bars in dd.items():
            if (start and d < start) or (end and d > end) or len(bars) < 20:
                continue
            day = Day(bars)
            for minute in range(DECIDE_EVERY + decide_offset, SESSION, DECIDE_EVERY):
                ok, ref, risk = decide(g, day, minute)
                if not ok or risk <= 0: continue
                e = day.idx_done_by(minute) + 1
                if e >= len(bars): break
                entry = bars[e][1] * (1 + slip); stop, target = entry - risk, entry + g["R"] * risk
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
