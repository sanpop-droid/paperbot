"""dashboard.py — สร้าง data/dashboard.html (เปิดด้วยเบราว์เซอร์ได้เลย)
กราฟใช้ TradingView Lightweight Charts (Apache-2.0) โหลดจาก unpkg"""
import json, html, os
import strategy as S
from common import load_json, path

def svg_ga(run):
    """กราฟ: t-stat ช่วง train (เส้นทึบ) vs holdout (เส้นประ) ของแต่ละเกาะ ข้ามรุ่น + เส้น 'โชคช่วย'"""
    if not run: return "<p>ยังไม่มีรอบวิวัฒนาการ</p>"
    W, H, pad = 640, 260, 36
    gens = run["gens"]; islands = sorted({g.get("island", "all") for g in gens})
    vals = [g["is_t"] for g in gens] + [g["ho_t"] for g in gens] + [run["luck_t"], 0]
    lo, hi = min(vals) - 0.5, max(vals) + 0.5; G = max(g["gen"] for g in gens)
    X = lambda k: pad + (W - pad - 10) * (k - 1) / max(1, G - 1); Y = lambda v: H - 24 - (H - 34) * (v - lo) / (hi - lo)
    cols = {"breakout": "#2f6fb0", "pullback": "#c8643b", "trend": "#1f9d62", "all": "#7b5cc4"}
    out = [f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto" role="img" aria-label="กราฟ train vs holdout">']
    step = max(1, round((hi - lo) / 6))
    for v in range(int(lo), int(hi) + 1, step):
        out.append(f'<line x1="{pad}" x2="{W-10}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="var(--line)"/><text x="4" y="{Y(v)+4:.1f}" font-size="11" fill="var(--mut)">{v}</text>')
    out.append(f'<line x1="{pad}" x2="{W-10}" y1="{Y(run["luck_t"]):.1f}" y2="{Y(run["luck_t"]):.1f}" stroke="#d6a21e" stroke-width="2" stroke-dasharray="2 3"/>'
               f'<text x="{W-12}" y="{Y(run["luck_t"])-5:.1f}" text-anchor="end" font-size="11" fill="#d6a21e">เส้นโชคช่วย t≈{run["luck_t"]}</text>')
    for isl in islands:
        g = [x for x in gens if x.get("island", "all") == isl]; c = cols.get(isl, "#888")
        for key, dash in (("is_t", ""), ("ho_t", ' stroke-dasharray="5 4"')):
            pts = " ".join(f"{X(x['gen']):.1f},{Y(x[key]):.1f}" for x in g)
            out.append(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="2"{dash}/>')
    for k in range(1, G + 1, max(1, G // 6)):
        out.append(f'<text x="{X(k):.1f}" y="{H-6}" font-size="11" fill="var(--mut)" text-anchor="middle">รุ่น {k}</text>')
    out.append("</svg>")
    leg = " ".join(f'<span><i style="background:{cols.get(i,"#888")}"></i>{i}</span>' for i in islands)
    return "".join(out) + f'<p class="note">{leg} · เส้นทึบ = คะแนนช่วง train · เส้นประ = holdout (ข้อมูลที่ GA ไม่เคยเห็น)</p>'

FLOW = '''<svg viewBox="0 0 640 150" style="width:100%;height:auto" role="img" aria-label="วงจรการพัฒนาบอท">
<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="var(--mut)"/></marker></defs>
<g font-size="12" text-anchor="middle" fill="var(--ink)">
<rect x="5" y="20" width="140" height="50" rx="9" fill="var(--card)" stroke="#2f6fb0"/><text x="75" y="41" font-weight="700">① evolve.py</text><text x="75" y="58" fill="var(--mut)" font-size="11">GA หา/คัดกฎ (สัปดาห์ละครั้ง)</text>
<rect x="170" y="20" width="140" height="50" rx="9" fill="var(--card)" stroke="#c8643b"/><text x="240" y="41" font-weight="700">② แชมป์</text><text x="240" y="58" fill="var(--mut)" font-size="11">กฎที่ชนะ forward test</text>
<rect x="335" y="20" width="140" height="50" rx="9" fill="var(--card)" stroke="#1f9d62"/><text x="405" y="41" font-weight="700">③ bot.py ทุกวัน</text><text x="405" y="58" fill="var(--mut)" font-size="11">bracket order ใน Alpaca paper</text>
<rect x="500" y="20" width="135" height="50" rx="9" fill="var(--card)" stroke="#7b5cc4"/><text x="567" y="41" font-weight="700">④ เก็บข้อมูล</text><text x="567" y="58" fill="var(--mut)" font-size="11">trade จริง + ผลเงา</text>
<line x1="145" y1="45" x2="168" y2="45" stroke="var(--mut)" marker-end="url(#a)"/><line x1="310" y1="45" x2="333" y2="45" stroke="var(--mut)" marker-end="url(#a)"/><line x1="475" y1="45" x2="498" y2="45" stroke="var(--mut)" marker-end="url(#a)"/>
<path d="M567,70 V120 H75 V72" fill="none" stroke="var(--mut)" marker-end="url(#a)"/><text x="320" y="112" fill="var(--mut)" font-size="11">ผู้ท้าชิงทุกตัวเทรดแบบเงาไปพร้อมกัน → ใครชนะ forward test จริงได้ขึ้นเป็นแชมป์</text>
</g></svg>'''

def day_md():
    """ส่วน Day trade ของสรุป (บอท dt.py)"""
    P = load_json("population_scan.json", {}); tr = load_json("dt_trades.json", []); st = load_json("dt_state.json", {"open": {}})
    U = load_json("universe.json", {})
    if not P and not tr: return []
    c = P.get("champion"); m = S.metrics([{**t, "open": False, "ret": 0} for t in tr]) if tr else None
    pnl = sum(t["pnl"] for t in tr)
    out = ["", "---", f"## ⚡ Day trade scanner (universe {len(U.get('symbols', []))} ตัว · อัปเดต {U.get('date', '-')})",
           f"**trade ที่ปิดแล้ว** {len(tr)} · **avg R** {('%+.3f' % m['avgR']) if m else '-'} · **win** {('%.0f%%' % (m['win']*100)) if m else '-'} · **P&L รวม** ${pnl:+,.2f} · **ถืออยู่** {len(st.get('open', {}))}", ""]
    if c: out += [f"**👑 แชมป์:** `{c['id']}`{' (ทดลองงาน)' if c.get('probation') else ''}  \n{c.get('desc','')}", ""]
    r = (P.get("runs") or [None])[-1]
    if r: out += [f"> evolve ล่าสุด {r['date']}: {r['decision']} · เทียบ: ซื้อทุกตัวเช้า-ขายเย็น เฉลี่ย {r.get('bh_holdout', 0)*100:+.2f}%/วัน (holdout)", ""]
    sc = st.get("scanned", {})
    if sc:
        d0 = max(sc); out += [f"**สแกนล่าสุด {d0}:** " + (", ".join(f"{p['sym']} {p['score']*100:+.1f}%" for p in sc[d0]) or "ไม่มีตัวผ่านเกณฑ์"), ""]
    if st.get("open"):
        out += ["| ถืออยู่ | จำนวน | stop | target |", "|---|---|---|---|"] + [f"| {s} | {o['qty']} | {o['stop']:.2f} | {o['target']:.2f} |" for s, o in st["open"].items()] + [""]
    if tr:
        out += ["| หุ้น | วัน | เข้า→ออก | แบบ | R | P&L |", "|---|---|---|---|---|---|"]
        out += [f"| {t['sym']} | {t['entry_d']} | {t.get('t_in','')}→{t.get('t_out','')} | {t['how']} | {t['R']:+.2f} | {t['pnl']:+,.2f} |" for t in reversed(tr[-15:])]
    return out

def build():
    P = load_json("population.json", {}); eq = load_json("equity.json", []); tr = load_json("trades.json", [])
    st = load_json("state.json", {"open": {}}); B = load_json("bars.json", {}); bars = B.get("bars", {})
    inds = {s: S.Ind([tuple(r) for r in v]) for s, v in bars.items() if v}
    champ = P.get("champion"); run = (P.get("runs") or [None])[-1]
    rows = []
    for c in P.get("candidates", []):
        f = S.metrics(S.backtest(c["g"], inds, start=c["born"])) if inds else c.get("forward", {"n": 0, "avgR": 0})
        rows.append((c, f))
    rows.sort(key=lambda x: (-(x[1]["avgR"] if x[1]["n"] >= 5 else -9), -x[0]["holdout"]["tstat"]))
    # benchmark: ซื้อแล้วถือ 8 หุ้นเท่ากัน เริ่มวันแรกที่มี equity
    bench = []
    if eq and inds:
        e0 = eq[0]["equity"]; d0 = eq[0]["date"]
        base = {s: next((ind.c[k] for k, d in enumerate(ind.d) if d >= d0), None) for s, ind in inds.items()}
        for e in eq:
            vals = []
            for s, ind in inds.items():
                px = next((ind.c[k] for k in range(len(ind.d) - 1, -1, -1) if ind.d[k] <= e["date"]), None)
                if px and base[s]: vals.append(px / base[s])
            if vals: bench.append({"time": e["date"], "value": round(e0 * sum(vals) / len(vals), 2)})
    eqs = [{"time": e["date"], "value": e["equity"]} for e in eq]
    candles = {s: [{"time": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4]} for r in v[-250:]] for s, v in bars.items()}
    marks = {}
    for t in tr:
        marks.setdefault(t["sym"], []).append({"time": t["entry_d"], "position": "belowBar", "color": "#2f6fb0", "shape": "arrowUp", "text": "ซื้อ"})
        marks.setdefault(t["sym"], []).append({"time": t["exit_d"], "position": "aboveBar", "color": "#1f9d62" if t["R"] > 0 else "#d0443b", "shape": "arrowDown", "text": f"{t['R']:+.1f}R"})
    for s, o in st.get("open", {}).items():
        marks.setdefault(s, []).append({"time": o["entry_day"], "position": "belowBar", "color": "#2f6fb0", "shape": "arrowUp", "text": "ถืออยู่"})
    for s in marks: marks[s].sort(key=lambda m: m["time"])
    esc = html.escape
    fmtR = lambda m: ("%+.3f" % m["avgR"]) if m["n"] else "-"
    real = S.metrics([{**t, "open": False, "ret": 0} for t in tr]) if tr else None
    cand_html = "".join(
        f"<tr><td><b>{esc(c['id'])}</b>{' 👑' if champ and c['id']==champ['id'] else ''}<div class='note'>{esc(c.get('desc',''))}</div></td>"
        f"<td>{c['born']}</td><td>{c['train']['tstat']:.2f}</td><td class='{'up' if c['holdout']['avgR']>0 else 'dn'}'>{c['holdout']['avgR']:+.3f} ({c['holdout']['n']})</td>"
        f"<td class='{'up' if f['avgR']>0 else 'dn' if f['n'] else ''}'>{fmtR(f)} ({f['n']})</td></tr>" for c, f in rows)
    tr_html = "".join(f"<tr><td>{esc(t['sym'])}</td><td>{t['entry_d']}</td><td>{t['exit_d']}</td><td>{t['how']}</td><td class='{'up' if t['R']>0 else 'dn'}'>{t['R']:+.2f}</td><td>${t['pnl']:+,.2f}</td></tr>" for t in reversed(tr[-60:]))
    op_html = "".join(f"<tr><td>{esc(s)}</td><td>{o['entry_day']}</td><td>{o['qty']}</td><td>${o['stop']:.2f}</td><td>${o['target']:.2f}</td><td>{o['H']} วัน</td></tr>" for s, o in st.get("open", {}).items())
    last_eq = eq[-1]["equity"] if eq else 0
    data = json.dumps({"eq": eqs, "bench": bench, "candles": candles, "marks": marks}, ensure_ascii=False)
    doc = f'''<!DOCTYPE html><html lang="th"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PaperBot Dashboard</title><script src="../lib/lightweight-charts.standalone.production.js"></script>
<script>window.LightweightCharts||document.write('<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"><\\/script>')</script>
<style>:root{{--bg:#f6f4ef;--card:#fff;--ink:#1d1c1a;--mut:#6b675f;--line:#e2ded4}}@media(prefers-color-scheme:dark){{:root{{--bg:#141413;--card:#1e1d1b;--ink:#ecebe6;--mut:#a29e95;--line:#34322e}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,"Leelawadee UI","Tahoma",sans-serif}}main{{max-width:1100px;margin:auto;padding:14px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin-bottom:12px}}h1{{font-size:20px;margin:4px 0}}h2{{font-size:16px;margin:0 0 8px}}
.k{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}}.k div{{background:var(--bg);border-radius:10px;padding:8px 10px}}.k b{{display:block;font-size:19px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{padding:6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{color:var(--mut);font-size:12px}}.tw{{overflow-x:auto}}
.up{{color:#1f9d62}}.dn{{color:#d0443b}}.note{{color:var(--mut);font-size:12.5px}}.warn{{background:#d6a21e22;border-left:4px solid #d6a21e;padding:8px 10px;border-radius:8px}}
.note i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin:0 4px 0 8px}}select{{font:inherit;padding:4px 8px;border-radius:8px;background:var(--bg);color:var(--ink);border:1px solid var(--line)}}
#eqc,#cc{{height:280px}}</style></head><body><main>
<h1>🤖 PaperBot · Alpaca Paper</h1><p class="note">อัปเดต {esc(B.get("updated","-"))} · ข้อมูลราคา feed {esc(str(B.get("feed","-")))} · เงินจำลองเท่านั้น ไม่ใช่คำแนะนำการลงทุน</p>
<div class="card"><h2>วงจรการพัฒนา</h2><div class="tw"><div style="min-width:560px">{FLOW}</div></div></div>
<div class="card"><div class="k"><div><span class="note">Equity</span><b>${last_eq:,.2f}</b></div>
<div><span class="note">Trade ที่ปิดแล้ว</span><b>{len(tr)}</b></div><div><span class="note">avg R (ของจริง)</span><b class="{'up' if real and real['avgR']>0 else 'dn'}">{fmtR(real) if real else '-'}</b></div>
<div><span class="note">ถืออยู่</span><b>{len(st.get("open",{}))}</b></div></div>
<p><b>👑 แชมป์:</b> {esc(champ['id']) if champ else 'ยังไม่มี'} {'<span class="dn">(ทดลองงาน · ความเสี่ยงครึ่งเดียว)</span>' if champ and champ.get('probation') else ''}<br><span class="note">{esc(champ.get('desc','')) if champ else 'รัน evolve.bat ก่อน'}</span></p>
{f'<p class="warn">การตัดสินใจรอบล่าสุด ({run["date"]}): {esc(run["decision"])}</p>' if run else ''}</div>
<div class="card"><h2>Equity เทียบ “ซื้อแล้วถือ 8 หุ้น”</h2><div id="eqc"></div><p class="note"><i style="background:#2f6fb0"></i>บอท <i style="background:#8d8a83"></i>ซื้อแล้วถือ</p></div>
<div class="card"><h2>กราฟราคา + จุดเทรดของบอท</h2><select id="sym"></select><div id="cc"></div></div>
<div class="card"><h2>บทเรียนจาก GA รอบล่าสุด: train ขึ้น ≠ อนาคตดี</h2><div class="tw"><div style="min-width:520px">{svg_ga(run)}</div></div>
<p class="note">ถ้าเส้นทึบสูงกว่าเส้นโชคช่วย แต่เส้นประไม่ขึ้นตาม แปลว่ากฎ "จำ" ข้อมูลเก่า (overfitting) · ทดลองกฎรวม {P.get("n_tested_total",0)} ครั้ง</p></div>
<div class="card"><h2>ผู้สมัคร (เทรดแบบเงา)</h2><div class="tw"><table><tr><th>กฎ</th><th>เกิด</th><th>train t</th><th>holdout avgR (n)</th><th>forward avgR (n)</th></tr>{cand_html}</table></div>
<p class="note">forward = ผลหลังวันเกิด (ข้อมูลที่ไม่มีใครเคยเห็นตอนสร้างกฎ) ซึ่งเชื่อถือได้ที่สุด · ต้องมี ≥ 15 trade จึงเลื่อนขั้นได้</p></div>
<div class="card"><h2>กำลังถือ</h2><div class="tw"><table><tr><th>หุ้น</th><th>เข้า</th><th>จำนวน</th><th>stop</th><th>target</th><th>ถือสูงสุด</th></tr>{op_html or '<tr><td colspan=6 class=note>ไม่มี</td></tr>'}</table></div></div>
<div class="card"><h2>Trade ที่ปิดแล้ว</h2><div class="tw"><table><tr><th>หุ้น</th><th>เข้า</th><th>ออก</th><th>แบบ</th><th>R</th><th>P&amp;L</th></tr>{tr_html or '<tr><td colspan=6 class=note>ยังไม่มี</td></tr>'}</table></div></div>
<p class="note">Charts by TradingView Lightweight Charts™ (Apache-2.0)</p></main>
<script>const D={data};
const dark=matchMedia('(prefers-color-scheme:dark)').matches,css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const opt=el=>({{width:el.clientWidth,height:280,layout:{{background:{{color:'transparent'}},textColor:css('--mut')}},grid:{{vertLines:{{color:css('--line')}},horzLines:{{color:css('--line')}}}},timeScale:{{borderColor:css('--line')}},rightPriceScale:{{borderColor:css('--line')}}}});
if(window.LightweightCharts){{
 const e=document.getElementById('eqc'),c1=LightweightCharts.createChart(e,opt(e));
 c1.addLineSeries({{color:'#2f6fb0',lineWidth:2}}).setData(D.eq);c1.addLineSeries({{color:'#8d8a83',lineWidth:1}}).setData(D.bench);c1.timeScale().fitContent();
 const cc=document.getElementById('cc'),c2=LightweightCharts.createChart(cc,opt(cc)),cs=c2.addCandlestickSeries({{upColor:'#1f9d62',downColor:'#d0443b',wickUpColor:'#1f9d62',wickDownColor:'#d0443b',borderVisible:false}});
 const sel=document.getElementById('sym');Object.keys(D.candles).forEach(s=>sel.add(new Option(s,s)));
 const show=s=>{{cs.setData(D.candles[s]);cs.setMarkers(D.marks[s]||[]);c2.timeScale().fitContent()}};sel.onchange=()=>show(sel.value);if(sel.options.length)show(sel.value);
 addEventListener('resize',()=>{{c1.applyOptions({{width:e.clientWidth}});c2.applyOptions({{width:cc.clientWidth}})}});
}}else{{document.getElementById('eqc').textContent='โหลดไลบรารีกราฟไม่ได้ (ต้องต่ออินเทอร์เน็ต)'}}
</script></body></html>'''
    with open(path("dashboard.html"), "w", encoding="utf-8") as f:
        f.write(doc)
    # สรุปแบบ Markdown สำหรับหน้า GitHub Actions (เปิดบนมือถือได้)
    md = [f"## 🤖 PaperBot · {B.get('updated','-')}", "",
          f"**Equity** ${last_eq:,.2f} · **trade ที่ปิดแล้ว** {len(tr)} · **avg R จริง** {fmtR(real) if real else '-'} · **ถืออยู่** {len(st.get('open',{}))}", "",
          f"**👑 แชมป์:** `{champ['id']}`{' (ทดลองงาน)' if champ.get('probation') else ''}  \n{champ.get('desc','')}" if champ else "**แชมป์:** ยังไม่มี", ""]
    if run: md += [f"> รอบ evolve ล่าสุด {run['date']}: {run['decision']}", ""]
    if st.get("open"):
        md += ["### กำลังถือ", "| หุ้น | เข้า | จำนวน | stop | target | ถือสูงสุด |", "|---|---|---|---|---|---|"]
        md += [f"| {s} | {o['entry_day']} | {o['qty']} | {o['stop']:.2f} | {o['target']:.2f} | {o['H']} วัน |" for s, o in st["open"].items()] + [""]
    if tr:
        md += ["### Trade ล่าสุด", "| หุ้น | เข้า | ออก | แบบ | R | P&L |", "|---|---|---|---|---|---|"]
        md += [f"| {t['sym']} | {t['entry_d']} | {t['exit_d']} | {t['how']} | {t['R']:+.2f} | {t['pnl']:+,.2f} |" for t in reversed(tr[-15:])] + [""]
    md += ["### ผู้สมัคร (forward test)", "| กฎ | เกิด | holdout avgR (n) | forward avgR (n) |", "|---|---|---|---|"]
    md += [f"| `{c['id']}` | {c['born']} | {c['holdout']['avgR']:+.3f} ({c['holdout']['n']}) | {fmtR(f)} ({f['n']}) |" for c, f in rows[:12]]
    log_tail = ""
    try:
        log_tail = "".join(open(path("log.txt"), encoding="utf-8").readlines()[-12:])
    except FileNotFoundError:
        pass
    if log_tail: md += ["", "### log ล่าสุด", "```", log_tail.rstrip(), "```"]
    md += day_md()
    md += ["", "_เงินจำลองเท่านั้น · dashboard แบบกราฟ: ไฟล์ data/dashboard.html_"]
    with open(path("summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    return path("dashboard.html")

if __name__ == "__main__":
    print("สร้างแล้ว:", build())
