"""scanstrat.py — Scanner: ดูหุ้นทั้ง universe (300 ตัวที่สภาพคล่องสูงสุด) แล้วซื้อตัวที่ "เช้านี้แรงที่สุด" K ตัว
ซื้อ ณ นาทีที่ M หลังตลาดเปิด → ขายด้วย stop / target / หรือปิดทุกตัวก่อนตลาดปิด (ไม่ถือข้ามคืน)

ยีน (ให้ GA เลือก)
  M        นาทีที่สแกน (15–120 · ทุก 15 นาที ตรงกับรอบของบอท)
  K        ซื้อกี่ตัว (1–5)
  pc       วัดความแรงจาก: 0 = ราคาเปิดวันนี้ → นาที M · 1 = ราคาปิดเมื่อวาน → นาที M (รวม gap)
  th       ต้องแรงอย่างน้อยกี่ % ถึงจะซื้อ (0–5%)
  gap_lo / gap_hi  ตัวกรอง gap เปิด (−10% ถึง +10%)
  k_stop   stop = k × 3 × ATR(5 นาที) ณ นาที M
  R        target กี่ R
ข้อมูล: days = {symbol: {"YYYY-MM-DD": [(m,o,h,l,c,v), ...]}} m = นาทีจาก 9:30
"""
import bisect
import strategy as S

SESSION, STEP, FLAT_BEFORE = 390, 15, 35
RANGES = {
    "M": (15, 120, True), "K": (1, 5, True), "pc": (0, 1, True), "th": (0.0, 0.05, False),
    "gap_lo": (-0.10, 0.10, False), "gap_hi": (-0.10, 0.10, False), "k_stop": (0.3, 2.0, False), "R": (0.5, 4.0, False),
}
M_GRID = list(range(15, 121, 15))
TYPES = ["open", "prevclose"]   # 2 เกาะ: วัดความแรงจากราคาเปิด / จากราคาปิดเมื่อวาน

def fix(g):
    for k, (lo, hi, isint) in RANGES.items():
        v = min(hi, max(lo, g[k])); g[k] = int(round(v)) if isint else round(v, 3)
    g["M"] = min(M_GRID, key=lambda m: abs(m - g["M"]))
    if g["gap_lo"] > g["gap_hi"]: g["gap_lo"], g["gap_hi"] = g["gap_hi"], g["gap_lo"]
    g["type"] = TYPES[g["pc"]]
    return g

def random_genome(rng, typ=None):
    g = {k: (rng.randint(lo, hi) if isint else rng.uniform(lo, hi)) for k, (lo, hi, isint) in RANGES.items()}
    if typ: g["pc"] = TYPES.index(typ)
    return fix(g)

def mutate(g, rng, rate=0.3, scale=0.15):
    c = dict(g)
    for k, (lo, hi, isint) in RANGES.items():
        if k != "pc" and rng.random() < rate:
            c[k] = c[k] + rng.gauss(0, (hi - lo) * scale)
    return fix(c)

def crossover(a, b, rng):
    c = {k: (a[k] if rng.random() < 0.5 else b[k]) for k in RANGES}; c["pc"] = a["pc"]
    return fix(c)

def gid(g):
    gf = f"-G{g['gap_lo']*100:+.0f}..{g['gap_hi']*100:+.0f}" if (g["gap_lo"] > -0.095 or g["gap_hi"] < 0.095) else ""
    return f"scan-{g['type']}-M{g['M']}-K{g['K']}-th{g['th']*100:.1f}-k{g['k_stop']:.2f}-R{g['R']:.1f}{gf}"

def describe_th(g):
    base = "ราคาเปิดวันนี้" if g["pc"] == 0 else "ราคาปิดเมื่อวาน (รวม gap)"
    gf = f" · เฉพาะหุ้นที่ gap เปิด {g['gap_lo']*100:+.1f}% ถึง {g['gap_hi']*100:+.1f}%" if (g["gap_lo"] > -0.095 or g["gap_hi"] < 0.095) else ""
    return (f"นาทีที่ {g['M']} หลังตลาดเปิด สแกนหุ้นทั้ง universe จัดอันดับตามการขึ้นจาก{base} "
            f"ซื้อ {g['K']} อันดับแรกที่ขึ้น ≥ {g['th']*100:.1f}%{gf} · stop {g['k_stop']:.2f} × 3 ATR(5 นาที) · target {g['R']:.1f}R · ขายทุกตัวก่อนตลาดปิด")

# ---------------- เตรียมข้อมูลครั้งเดียว (Panel) ----------------
class Info:
    __slots__ = ("sym", "bars", "m", "open", "pc", "gap", "c_at", "atr_at", "i_at")
    def __init__(self, sym, bars, pc):
        self.sym, self.bars, self.pc = sym, bars, pc
        self.m = [b[0] for b in bars]; self.open = bars[0][1]
        self.gap = bars[0][1] / pc - 1 if pc else 0.0
        tr = [bars[0][2] - bars[0][3]] + [max(bars[i][2] - bars[i][3], abs(bars[i][2] - bars[i-1][4]), abs(bars[i][3] - bars[i-1][4])) for i in range(1, len(bars))]
        self.c_at, self.atr_at, self.i_at = {}, {}, {}
        for M in M_GRID:
            i = bisect.bisect_right(self.m, M - 5) - 1   # แท่งสุดท้ายที่ปิดแล้ว ณ นาที M
            if i >= 0:
                self.i_at[M] = i; self.c_at[M] = bars[i][4]
                self.atr_at[M] = sum(tr[max(0, i - 13):i + 1]) / (i + 1 - max(0, i - 13))

def build_panel(days, min_price=5.0):
    """{date: [Info, ...]} — ข้าม Info ที่ราคาต่ำกว่า min_price หรือแท่งน้อยเกิน"""
    panel = {}
    for sym, dd in days.items():
        prev = None
        for d in sorted(dd):
            bars = dd[d]; pc = prev; prev = bars[-1][4] if bars else prev
            if len(bars) < 20 or bars[0][1] < min_price: continue
            panel.setdefault(d, []).append(Info(sym, bars, pc))
    return panel

def score(g, x):
    M = g["M"]
    if M not in x.c_at: return None
    if x.pc and not (g["gap_lo"] <= x.gap <= g["gap_hi"]): return None
    base = x.pc if (g["pc"] == 1 and x.pc) else x.open
    return x.c_at[M] / base - 1

def rank(g, infos, exclude=()):
    """คืน [(score, Info)] อันดับ 1..K ที่ผ่านเกณฑ์"""
    sc = []
    for x in infos:
        if x.sym in exclude: continue
        s = score(g, x)
        if s is not None and s >= g["th"]: sc.append((s, x))
    sc.sort(key=lambda t: -t[0])
    return sc[:g["K"]]

def backtest(g, panel, start=None, end=None, slip=0.0005):
    trades = []; M = g["M"]
    flat_m = next(mm for mm in range(M, SESSION + 1, STEP) if mm >= SESSION - FLAT_BEFORE)
    for d in sorted(panel):
        if (start and d < start) or (end and d > end): continue
        for s, x in rank(g, panel[d]):
            e = x.i_at[M] + 1; bars = x.bars
            if e >= len(bars): continue
            entry = bars[e][1] * (1 + slip); risk = g["k_stop"] * 3 * x.atr_at[M]
            if risk <= 0: continue
            stop, target = entry - risk, entry + g["R"] * risk; exit_px, how = None, "time"
            for j in range(e, len(bars)):
                m, o, h, l, c, v = bars[j]
                if m >= flat_m: exit_px = o; break
                if j > e and o <= stop: exit_px, how = o, "stop"; break
                if l <= stop: exit_px, how = stop, "stop"; break
                if h >= target: exit_px, how = target, "target"; break
            if exit_px is None: exit_px = bars[-1][4]
            exit_px *= (1 - slip)
            trades.append({"sym": x.sym, "sig": d, "entry_d": d, "exit_d": d, "entry": entry, "exit": exit_px, "how": how,
                           "R": (exit_px - entry) / risk, "ret": exit_px / entry - 1, "open": False})
    return trades

def baseline(panel, start=None, end=None):
    """เทียบ: ซื้อทุกตัวใน universe ตอนเปิด ขายตอนปิด (เฉลี่ยต่อหุ้นต่อวัน)"""
    r = [x.bars[-1][4] / x.open - 1 for d, xs in panel.items() if (not start or d >= start) and (not end or d <= end) for x in xs]
    return sum(r) / len(r) if r else 0.0
