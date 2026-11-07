"""PaperBot core: indicators, signals, backtest, metrics, GA helpers.
ใช้ร่วมกันทั้ง bot.py (เทรดจริงในบัญชี paper) และ evolve.py (พัฒนากฎ)
bars = {symbol: [(date 'YYYY-MM-DD', open, high, low, close), ...]} เรียงจากเก่าไปใหม่
"""
import math, random

# ---------------- genome (กฎเทรด 1 ชุด) ----------------
TYPES = ["breakout", "pullback", "trend"]
RANGES = {  # name: (min, max, is_int)
    "n": (10, 60, True),        # breakout: จำนวนวันย้อนหลังของจุดสูงสุด
    "fast": (5, 30, True),      # trend: SMA เร็ว
    "slow": (40, 200, True),    # trend/pullback: SMA ช้า
    "rsi_th": (5, 35, False),   # pullback: RSI(2) ต่ำกว่าค่านี้ = ย่อตัว
    "k_stop": (0.5, 3.0, False),  # stop ห่างกี่ ATR
    "R": (0.5, 4.0, False),     # target กี่ R
    "H": (2, 20, True),         # ถือนานสุดกี่วัน
}

def random_genome(rng):
    g = {"type": rng.choice(TYPES)}
    for k, (lo, hi, isint) in RANGES.items():
        g[k] = rng.randint(lo, hi) if isint else round(rng.uniform(lo, hi), 2)
    return fix(g)

def fix(g):
    for k, (lo, hi, isint) in RANGES.items():
        v = min(hi, max(lo, g[k]))
        g[k] = int(round(v)) if isint else round(v, 2)
    if g["fast"] >= g["slow"]:
        g["fast"] = max(5, min(30, g["slow"] // 3))
    return g

def mutate(g, rng, rate=0.3):
    c = dict(g)
    if rng.random() < 0.1:
        c["type"] = rng.choice(TYPES)
    for k, (lo, hi, isint) in RANGES.items():
        if rng.random() < rate:
            c[k] = c[k] + rng.gauss(0, (hi - lo) * 0.15)
    return fix(c)

def crossover(a, b, rng):
    c = {k: (a[k] if rng.random() < 0.5 else b[k]) for k in a if k in b}
    return fix(c)

def gid(g):
    """ชื่อสั้นของกฎ เช่น breakout-n20-k1.5-R2.0-H10"""
    core = {"breakout": f"n{g['n']}", "pullback": f"s{g['slow']}-rsi{g['rsi_th']:.0f}", "trend": f"f{g['fast']}-s{g['slow']}"}[g["type"]]
    return f"{g['type']}-{core}-k{g['k_stop']:.1f}-R{g['R']:.1f}-H{g['H']}"

def describe_th(g):
    t = {"breakout": f"ซื้อเมื่อราคาปิดทะลุจุดสูงสุด {g['n']} วัน",
         "pullback": f"ซื้อเมื่อราคาอยู่เหนือ SMA{g['slow']} แต่ RSI(2) ย่อลงต่ำกว่า {g['rsi_th']:.0f}",
         "trend": f"ซื้อเมื่อ SMA{g['fast']} ตัดขึ้นเหนือ SMA{g['slow']}"}[g["type"]]
    return f"{t} · stop {g['k_stop']:.1f} ATR · target {g['R']:.1f}R · ถือไม่เกิน {g['H']} วัน"

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
