"""scanstrat.py — Scanner: ดูหุ้นทั้ง universe แล้วเทรดตัวที่ "เช้านี้แรงที่สุด" ทั้งฝั่งขึ้น (long) และฝั่งลง (short)
ซื้อ/ขาย ณ นาทีที่ M หลังตลาดเปิด → ออกด้วย stop / target / หรือปิดทุกตัวก่อนตลาดปิด (ไม่ถือข้ามคืน)

ยีน (ให้ GA เลือก)
  M        นาทีที่สแกน (15–120 · ทุก 15 นาที ตรงกับรอบของบอท)
  K        จำนวนตัวต่อฝั่ง (1–5)
  pc       วัดความแรงจาก: 0 = ราคาเปิดวันนี้ → นาที M · 1 = ราคาปิดเมื่อวาน → นาที M (รวม gap)
  side     0 = long อย่างเดียว · 1 = short อย่างเดียว · 2 = ทั้งสองฝั่ง
  th       ต้องขึ้น (long) / ลง (short) อย่างน้อยกี่ % (0–5%)
  gap_lo / gap_hi  ตัวกรอง gap เปิดของฝั่ง long (ฝั่ง short ใช้แบบกลับด้าน: −gap_hi ถึง −gap_lo)
  k_stop   ระยะ stop = k × 3 × ATR(5 นาที) ณ นาที M
  R        target กี่ R
ข้อมูล: days = {symbol: {"YYYY-MM-DD": bars}} โดย bars เป็น list ของ (m,o,h,l,c,v) หรือ compact (m,o,h,l,c) แบบ array
"""
import bisect
from array import array
import strategy as S

SESSION, STEP, FLAT_BEFORE = 390, 15, 35
RANGES = {
    "M": (15, 120, True), "K": (1, 5, True), "pc": (0, 1, True), "side": (0, 2, True), "th": (0.0, 0.05, False),
    "gap_lo": (-0.10, 0.10, False), "gap_hi": (-0.10, 0.10, False), "k_stop": (0.3, 2.0, False), "R": (0.5, 4.0, False),
}
M_GRID = list(range(15, 121, 15))
BASES, SIDES = ["open", "prevclose"], ["long", "short", "both"]
TYPES = [f"{b}-{s}" for b in BASES for s in SIDES]   # 6 เกาะ

def fix(g):
    g.setdefault("side", 0)
    for k, (lo, hi, isint) in RANGES.items():
        v = min(hi, max(lo, g[k])); g[k] = int(round(v)) if isint else round(v, 3)
    g["M"] = min(M_GRID, key=lambda m: abs(m - g["M"]))
    if g["gap_lo"] > g["gap_hi"]: g["gap_lo"], g["gap_hi"] = g["gap_hi"], g["gap_lo"]
    g["type"] = f"{BASES[g['pc']]}-{SIDES[g['side']]}"
    return g

def random_genome(rng, typ=None):
    g = {k: (rng.randint(lo, hi) if isint else rng.uniform(lo, hi)) for k, (lo, hi, isint) in RANGES.items()}
    if typ:
        b, s = typ.split("-"); g["pc"] = BASES.index(b); g["side"] = SIDES.index(s)
    return fix(g)

def mutate(g, rng, rate=0.3, scale=0.15):
    c = fix(dict(g))
    for k, (lo, hi, isint) in RANGES.items():
        if k not in ("pc", "side") and rng.random() < rate:
            c[k] = c[k] + rng.gauss(0, (hi - lo) * scale)
    return fix(c)

def crossover(a, b, rng):
    a, b = fix(dict(a)), fix(dict(b))
    c = {k: (a[k] if rng.random() < 0.5 else b[k]) for k in RANGES}; c["pc"], c["side"] = a["pc"], a["side"]
    return fix(c)

def _gap_on(g):
    return g["gap_lo"] > -0.095 or g["gap_hi"] < 0.095

def gid(g):
    g = fix(dict(g))
    gf = f"-G{g['gap_lo']*100:+.0f}..{g['gap_hi']*100:+.0f}" if _gap_on(g) else ""
    return f"scan-{g['type']}-M{g['M']}-K{g['K']}-th{g['th']*100:.1f}-k{g['k_stop']:.2f}-R{g['R']:.1f}{gf}"

def describe_th(g):
    g = fix(dict(g))
    base = "ราคาเปิดวันนี้" if g["pc"] == 0 else "ราคาปิดเมื่อวาน (รวม gap)"
    side = {0: f"ซื้อ (long) {g['K']} ตัวที่ขึ้นแรงสุด ≥ {g['th']*100:.1f}%",
            1: f"short {g['K']} ตัวที่ลงแรงสุด ≥ {g['th']*100:.1f}%",
            2: f"ซื้อ {g['K']} ตัวที่ขึ้นแรงสุด และ short {g['K']} ตัวที่ลงแรงสุด (≥ {g['th']*100:.1f}%)"}[g["side"]]
    gf = f" · ตัวกรอง gap เปิด {g['gap_lo']*100:+.1f}% ถึง {g['gap_hi']*100:+.1f}% (ฝั่ง short กลับด้าน)" if _gap_on(g) else ""
    return (f"นาทีที่ {g['M']} หลังตลาดเปิด สแกน universe วัดการเปลี่ยนแปลงจาก{base} → {side}{gf}"
            f" · stop {g['k_stop']:.2f} × 3 ATR(5 นาที) · target {g['R']:.1f}R · ปิดทุกตัวก่อนตลาดปิด")

# ---------------- เก็บข้อมูลแบบประหยัดหน่วยความจำ ----------------
def compact(bars):
    """list[(m,o,h,l,c,v)] → (array m, o, h, l, c)  ประหยัดหน่วยความจำ ~5 เท่า"""
    return (array("h", (b[0] for b in bars)), array("d", (b[1] for b in bars)), array("d", (b[2] for b in bars)),
            array("d", (b[3] for b in bars)), array("d", (b[4] for b in bars)))

class Info:
    __slots__ = ("sym", "m", "o", "h", "l", "c", "open", "pc", "gap", "c_at", "atr_at", "i_at")
    def __init__(self, sym, bars, pc):
        if not isinstance(bars, tuple): bars = compact(bars)
        self.sym, self.pc = sym, pc
        self.m, self.o, self.h, self.l, self.c = bars
        self.open = self.o[0]; self.gap = self.open / pc - 1 if pc else 0.0
        n = len(self.m)
        tr = [self.h[0] - self.l[0]] + [max(self.h[i] - self.l[i], abs(self.h[i] - self.c[i-1]), abs(self.l[i] - self.c[i-1])) for i in range(1, n)]
        self.c_at, self.atr_at, self.i_at = {}, {}, {}
        for M in M_GRID:
            i = bisect.bisect_right(self.m, M - 5) - 1   # แท่งสุดท้ายที่ปิดแล้ว ณ นาที M
            if i >= 0:
                self.i_at[M] = i; self.c_at[M] = self.c[i]
                self.atr_at[M] = sum(tr[max(0, i - 13):i + 1]) / (i + 1 - max(0, i - 13))

def build_panel(days, min_price=5.0):
    """{date: [Info, ...]}"""
    panel = {}
    for sym, dd in days.items():
        prev = None
        for d in sorted(dd):
            bars = dd[d]
            if not isinstance(bars, tuple): bars = compact(bars)
            pc = prev; prev = bars[4][-1] if len(bars[0]) else prev
            if len(bars[0]) < 20 or bars[1][0] < min_price: continue
            panel.setdefault(d, []).append(Info(sym, bars, pc))
    return panel

def score(g, x):
    M = g["M"]
    if M not in x.c_at: return None
    base = x.pc if (g["pc"] == 1 and x.pc) else x.open
    return x.c_at[M] / base - 1

def rank(g, infos, exclude=(), no_short=()):
    """คืน [(score, Info, dir)] dir = +1 long / −1 short"""
    sc = [(score(g, x), x) for x in infos if x.sym not in exclude]
    sc = [(s, x) for s, x in sc if s is not None]
    out = []
    if g["side"] in (0, 2):
        L = [(s, x) for s, x in sc if s >= g["th"] and (not x.pc or g["gap_lo"] <= x.gap <= g["gap_hi"])]
        L.sort(key=lambda t: -t[0]); out += [(s, x, 1) for s, x in L[:g["K"]]]
    if g["side"] in (1, 2):
        Sh = [(s, x) for s, x in sc if s <= -g["th"] and x.sym not in no_short and (not x.pc or -g["gap_hi"] <= x.gap <= -g["gap_lo"])]
        Sh.sort(key=lambda t: t[0]); out += [(s, x, -1) for s, x in Sh[:g["K"]]]
    return out

def simulate(x, e, d, risk, R, flat_m, slip):
    """ออกจากตำแหน่งบนแท่ง 5 นาที · d = +1 long / −1 short · คืน (exit, how)"""
    entry = x.o[e] * (1 + slip * d); stop, target = entry - d * risk, entry + d * R * risk
    for j in range(e, len(x.m)):
        m, o, h, l = x.m[j], x.o[j], x.h[j], x.l[j]
        if m >= flat_m: return entry, o, "time"
        if d > 0:
            if j > e and o <= stop: return entry, o, "stop"
            if l <= stop: return entry, stop, "stop"
            if h >= target: return entry, target, "target"
        else:
            if j > e and o >= stop: return entry, o, "stop"
            if h >= stop: return entry, stop, "stop"
            if l <= target: return entry, target, "target"
    return entry, x.c[-1], "time"

def backtest(g, panel, start=None, end=None, slip=0.0005, no_short=()):
    g = fix(dict(g)); trades = []; M = g["M"]
    flat_m = next(mm for mm in range(M, SESSION + 1, STEP) if mm >= SESSION - FLAT_BEFORE)
    for d in sorted(panel):
        if (start and d < start) or (end and d > end): continue
        for s, x, di in rank(g, panel[d], no_short=no_short):
            e = x.i_at[M] + 1
            if e >= len(x.m): continue
            risk = g["k_stop"] * 3 * x.atr_at[M]
            if risk <= 0: continue
            entry, ex, how = simulate(x, e, di, risk, g["R"], flat_m, slip)
            ex *= (1 - slip * di)
            trades.append({"sym": x.sym, "sig": d, "entry_d": d, "exit_d": d, "entry": entry, "exit": ex, "how": how, "dir": di,
                           "R": di * (ex - entry) / risk, "ret": di * (ex / entry - 1), "open": False})
    return trades

def baseline(panel, start=None, end=None):
    """เทียบ: ซื้อทุกตัวใน universe ตอนเปิด ขายตอนปิด (เฉลี่ยต่อหุ้นต่อวัน)"""
    r = [x.c[-1] / x.open - 1 for d, xs in panel.items() if (not start or d >= start) and (not end or d <= end) for x in xs]
    return sum(r) / len(r) if r else 0.0
