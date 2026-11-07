"""PaperBot core: indicators, signals, backtest, metrics, GA helpers.
ใช้ร่วมกันทั้ง bot.py (เทรดจริงในบัญชี paper) และ evolve.py (พัฒนากฎ)
bars = {symbol: [(date 'YYYY-MM-DD', open, high, low, close), ...]} เรียงจากเก่าไปใหม่
"""
import math, random

# ---------------- genome (กฎเทรด 1 ชุด) ----------------
TYPES = ["breakout", "pullback", "trend", "bollinger", "macd", "roc", "nr"]
RANGES = {  # name: (min, max, is_int)
    "n": (10, 60, True),        # breakout: จำนวนวันย้อนหลังของจุดสูงสุด
    "fast": (5, 30, True),      # trend: SMA เร็ว
    "slow": (40, 200, True),    # trend/pullback: SMA ช้า
    "rsi_th": (5, 35, False),   # pullback: RSI(2) ต่ำกว่าค่านี้ = ย่อตัว
    "k_stop": (0.5, 3.0, False),  # stop ห่างกี่ ATR
    "R": (0.5, 4.0, False),     # target กี่ R
    "H": (2, 20, True),         # ถือนานสุดกี่วัน
    "bb_n": (10, 40, True),     # bollinger: จำนวนวันของเส้นกลาง
    "bb_k": (1.0, 3.0, False),  # bollinger: ซื้อเมื่อต่ำกว่าเส้นกลาง k×SD
    "roc_n": (5, 60, True),     # roc: วัดผลตอบแทนย้อนหลังกี่วัน
    "roc_th": (0.0, 0.25, False),  # roc: ต้องขึ้นมาแล้วอย่างน้อยกี่ %
    "nr": (4, 10, True),        # nr: แท่งเมื่อวานแคบที่สุดในกี่วัน
    "regime": (0, 200, True),   # ตัวกรองทุกประเภท: ราคาต้องอยู่เหนือ SMA(regime) · < 30 = ปิดตัวกรอง
}
DEFAULTS = {"bb_n": 20, "bb_k": 2.0, "roc_n": 20, "roc_th": 0.05, "nr": 7, "regime": 0}

def random_genome(rng):
    g = {"type": rng.choice(TYPES)}
    for k, (lo, hi, isint) in RANGES.items():
        g[k] = rng.randint(lo, hi) if isint else round(rng.uniform(lo, hi), 2)
    return fix(g)

def fix(g):
    for k, v in DEFAULTS.items():
        g.setdefault(k, v)   # กฎเก่าที่ยังไม่มียีนใหม่
    for k, (lo, hi, isint) in RANGES.items():
        v = min(hi, max(lo, g[k]))
        g[k] = int(round(v)) if isint else round(v, 2)
    if g["fast"] >= g["slow"]:
        g["fast"] = max(5, min(30, g["slow"] // 3))
    if g["regime"] < 30:
        g["regime"] = 0
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

def gid(g):
    """ชื่อสั้นของกฎ เช่น breakout-n20-k1.5-R2.0-H10 (+ -rg100 ถ้าเปิดตัวกรอง regime)"""
    g = fix(dict(g))
    core = {"breakout": f"n{g['n']}", "pullback": f"s{g['slow']}-rsi{g['rsi_th']:.0f}", "trend": f"f{g['fast']}-s{g['slow']}",
            "bollinger": f"b{g['bb_n']}-{g['bb_k']:.1f}sd", "macd": f"f{g['fast']}-s{g['slow']}", "roc": f"r{g['roc_n']}-{g['roc_th']*100:.0f}pct",
            "nr": f"nr{g['nr']}"}[g["type"]]
    rg = f"-rg{g['regime']}" if g["regime"] else ""
    return f"{g['type']}-{core}-k{g['k_stop']:.1f}-R{g['R']:.1f}-H{g['H']}{rg}"

def describe_th(g):
    g = fix(dict(g))
    t = {"breakout": f"ซื้อเมื่อราคาปิดทะลุจุดสูงสุด {g['n']} วัน",
         "pullback": f"ซื้อเมื่อราคาอยู่เหนือ SMA{g['slow']} แต่ RSI(2) ย่อลงต่ำกว่า {g['rsi_th']:.0f}",
         "trend": f"ซื้อเมื่อ SMA{g['fast']} ตัดขึ้นเหนือ SMA{g['slow']}",
         "bollinger": f"ซื้อเมื่อราคาปิดต่ำกว่าเส้นกลาง {g['bb_n']} วันลงไป {g['bb_k']:.1f} SD (Bollinger · คาดว่าจะเด้งกลับ)",
         "macd": f"ซื้อเมื่อ MACD (EMA{g['fast']}−EMA{g['slow']}) ตัดขึ้นเหนือเส้น signal 9 วัน",
         "roc": f"ซื้อเมื่อราคาขึ้นมาแล้ว ≥ {g['roc_th']*100:.0f}% ใน {g['roc_n']} วัน และทำจุดสูงสุดใหม่ 5 วัน (momentum)",
         "nr": f"ซื้อเมื่อราคาปิดทะลุจุดสูงสุดของเมื่อวาน ซึ่งเป็นแท่งที่แคบที่สุดใน {g['nr']} วัน (NR{g['nr']})"}[g["type"]]
    rg = f" · เฉพาะตอนราคาอยู่เหนือ SMA{g['regime']}" if g["regime"] else ""
    return f"{t}{rg} · stop {g['k_stop']:.1f} ATR · target {g['R']:.1f}R · ถือไม่เกิน {g['H']} วัน"

# ---------------- indicators (cache ต่อ symbol) ----------------
class Ind:
    def __init__(self, rows):
        self.d = [r[0] for r in rows]; self.o = [r[1] for r in rows]; self.h = [r[2] for r in rows]
        self.l = [r[3] for r in rows]; self.c = [r[4] for r in rows]; self._sma = {}; self._hh = {}
        n = len(rows); tr = [0.0] * n
        for i in range(1, n):
            pc = self.c[i - 1]; tr[i] = max(self.h[i] - self.l[i], abs(self.h[i] - pc), abs(self.l[i] - pc))
        self.atr = [None] * n
        for i in range(14, n):
            self.atr[i] = sum(tr[i - 13:i + 1]) / 14
        # RSI(2) แบบ Wilder
        self.rsi2 = [None] * n; ag = al = 0.0
        for i in range(1, n):
            ch = self.c[i] - self.c[i - 1]; up, dn = max(ch, 0), max(-ch, 0)
            if i <= 2: ag += up / 2; al += dn / 2
            else: ag = (ag * 1 + up) / 2; al = (al * 1 + dn) / 2
            if i >= 2: self.rsi2[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)

    def sma(self, p):
        if p not in self._sma:
            out = [None] * len(self.c); s = 0.0
            for i, v in enumerate(self.c):
                s += v
                if i >= p: s -= self.c[i - p]
                if i >= p - 1: out[i] = s / p
            self._sma[p] = out
        return self._sma[p]

    def ema(self, p):
        key = ("ema", p)
        if key not in self._sma:
            a = 2 / (p + 1); out = []; e = None
            for v in self.c:
                e = v if e is None else a * v + (1 - a) * e; out.append(e)
            self._sma[key] = out
        return self._sma[key]

    def macd(self, f, s):
        key = ("macd", f, s)
        if key not in self._sma:
            m = [x - y for x, y in zip(self.ema(f), self.ema(s))]
            a = 2 / 10; sig = []; e = None
            for v in m:
                e = v if e is None else a * v + (1 - a) * e; sig.append(e)
            self._sma[key] = (m, sig)
        return self._sma[key]

    def sd(self, p):
        key = ("sd", p)
        if key not in self._sma:
            out = [None] * len(self.c)
            for i in range(p - 1, len(self.c)):
                w = self.c[i - p + 1:i + 1]; m = sum(w) / p
                out[i] = math.sqrt(sum((x - m) ** 2 for x in w) / p)
            self._sma[key] = out
        return self._sma[key]

    def hh(self, p):  # จุดสูงสุดของ p วันก่อนหน้า (ไม่รวมวันนี้)
        if p not in self._hh:
            out = [None] * len(self.h)
            for i in range(p, len(self.h)):
                out[i] = max(self.h[i - p:i])
            self._hh[p] = out
        return self._hh[p]

def signal(g, ind, i):
    """True ถ้าราคาปิดวัน i ให้สัญญาณซื้อ (ใช้ข้อมูลถึงวัน i เท่านั้น)"""
    if ind.atr[i] is None:
        return False
    rg = g.get("regime", 0)
    if rg:
        s = ind.sma(rg)[i]
        if s is None or ind.c[i] <= s:
            return False
    t = g["type"]
    if t == "breakout":
        hh = ind.hh(g["n"])[i]
        return hh is not None and ind.c[i] > hh
    if t == "pullback":
        s = ind.sma(g["slow"])[i]; r = ind.rsi2[i]
        return s is not None and r is not None and ind.c[i] > s and r < g["rsi_th"]
    if t == "trend":
        f, s = ind.sma(g["fast"]), ind.sma(g["slow"])
        return i > 0 and None not in (f[i], s[i], f[i - 1], s[i - 1]) and f[i] > s[i] and f[i - 1] <= s[i - 1]
    if t == "bollinger":
        n = g.get("bb_n", 20); m = ind.sma(n)[i]; sd = ind.sd(n)[i]
        return m is not None and sd and ind.c[i] < m - g.get("bb_k", 2.0) * sd
    if t == "macd":
        if i < g["slow"] + 9: return False
        m, sg = ind.macd(g["fast"], g["slow"])
        return m[i] > sg[i] and m[i - 1] <= sg[i - 1]
    if t == "roc":
        n = g.get("roc_n", 20)
        if i < max(n, 5): return False
        return ind.c[i] / ind.c[i - n] - 1 >= g.get("roc_th", 0.05) and ind.c[i] > max(ind.h[i - 5:i])
    if t == "nr":
        n = g.get("nr", 7)
        if i < n + 1: return False
        rng = [ind.h[k] - ind.l[k] for k in range(i - n, i)]
        return rng[-1] == min(rng) and ind.c[i] > ind.h[i - 1]
    return False

# ---------------- backtest ----------------
def backtest(g, inds, start=None, end=None, slip=0.0005):
    """เข้าที่ราคาเปิดวันถัดจากสัญญาณ · bracket: stop/target · ปิดที่ราคาเปิดของวันที่ H
    ชน stop และ target ในแท่งเดียว = stop (ระวังไว้ก่อน) · gap ทะลุ stop = ขายที่ราคาเปิด (ขาดทุนเกิน 1R ได้)
    start/end = ช่วงวันที่ของ "วันสัญญาณ" (string) · คืนค่า list ของ trade dict"""
    trades = []
    for sym, ind in inds.items():
        n = len(ind.c); i = 0
        while i < n - 1:
            d = ind.d[i]
            if (start and d < start) or (end and d > end) or not signal(g, ind, i):
                i += 1; continue
            e = i + 1; entry = ind.o[e] * (1 + slip); risk = g["k_stop"] * ind.atr[i]
            stop, target = entry - risk, entry + g["R"] * risk
            exit_px = None; how = "time"; j = e
            last = min(n - 1, e + g["H"])
            while j < last:
                o, h, l = ind.o[j], ind.h[j], ind.l[j]
                if j > e and o <= stop: exit_px, how = o, "stop"; break
                if j > e and o >= target: exit_px, how = o, "target"; break
                if l <= stop: exit_px, how = stop, "stop"; break
                if h >= target: exit_px, how = target, "target"; break
                j += 1
            if exit_px is None:
                if e + g["H"] > n - 1:  # ข้อมูลยังไม่พอ = trade ยังเปิดอยู่
                    trades.append({"sym": sym, "sig": d, "entry_d": ind.d[e], "entry": entry, "stop": stop, "target": target, "open": True})
                    break
                exit_px = ind.o[last]
            exit_px *= (1 - slip)
            trades.append({"sym": sym, "sig": d, "entry_d": ind.d[e], "exit_d": ind.d[j if how != "time" else last],
                           "entry": entry, "exit": exit_px, "how": how, "R": (exit_px - entry) / risk, "ret": exit_px / entry - 1, "open": False})
            i = (j if how != "time" else last)  # ไม่เปิดซ้ำระหว่างถือ
    return trades

def metrics(trades):
    closed = [t for t in trades if not t["open"]]
    n = len(closed)
    if n == 0:
        return {"n": 0, "avgR": 0.0, "win": 0.0, "tstat": 0.0, "sumR": 0.0, "avgRet": 0.0}
    R = [t["R"] for t in closed]; m = sum(R) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in R) / (n - 1)) if n > 1 else 0
    # t-stat ใช้ sd อย่างน้อย 0.5R กันกรณี trade น้อยแล้วผลบังเอิญเหมือนกันหมดจน t พุ่งเกินจริง
    return {"n": n, "avgR": m, "sd": sd, "win": sum(1 for x in R if x > 0) / n, "tstat": m / max(sd, 0.5) * math.sqrt(n),
            "sumR": sum(R), "avgRet": sum(t["ret"] for t in closed) / n}

def fitness(m, min_n=15):
    """คะแนนใน GA = t-stat ของ R (หักคะแนนถ้า trade น้อย)"""
    return m["tstat"] * m["n"] / min_n - 1 if m["n"] < min_n else m["tstat"]

def robust_fitness(trades, edges, min_n=15):
    """คะแนนที่ต้อง "ดีสม่ำเสมอ": t-stat รวม × (0.4 + 0.6 × สัดส่วนช่วงเวลาที่ avg R > 0)
    edges = วันที่แบ่ง train ออกเป็นหลายช่วง (เช่น 3 ช่วง) · กฎที่รวยช่วงเดียวจะได้คะแนนลดลง"""
    m = metrics(trades); base = fitness(m, min_n)
    if m["n"] == 0: return base, 0.0
    bins = [[] for _ in range(len(edges) + 1)]
    for t in trades:
        if t["open"]: continue
        k = sum(1 for e in edges if t["sig"] >= e); bins[k].append(t["R"])
    used = [b for b in bins if b]
    pos = sum(1 for b in used if sum(b) > 0) / len(used) if used else 0.0
    return (base * (0.4 + 0.6 * pos) if base > 0 else base), pos

def stability(g, evaluate, mutate_fn, rng, k=6):
    """ทดสอบความไวของพารามิเตอร์: ขยับค่ากฎเล็กน้อย k ครั้ง แล้วดูว่ายังได้ avg R > 0 กี่ %
    กฎที่ดีจริงมักอยู่บน "ที่ราบสูง" (ค่าใกล้เคียงก็ดี) ไม่ใช่ "ยอดเขาแหลม" (ขยับนิดเดียวก็พัง)"""
    ok = 0
    for _ in range(k):
        n = mutate_fn(dict(g), rng, rate=1.0, scale=0.06)
        if evaluate(n)["avgR"] > 0: ok += 1
    return ok / k

def luck_bar(n_tested):
    """t-stat ที่ "โชคล้วน ๆ" ก็ทำได้ เมื่อทดลองกฎ n_tested ชุด ≈ sqrt(2 ln N)"""
    return math.sqrt(2 * math.log(max(2, n_tested)))

def buy_hold(inds, start, end=None):
    rs = []
    for ind in inds.values():
        idx = [k for k, d in enumerate(ind.d) if d >= start and (not end or d <= end)]
        if len(idx) > 1:
            rs.append(ind.c[idx[-1]] / ind.o[idx[0]] - 1)
    return sum(rs) / len(rs) if rs else 0.0
