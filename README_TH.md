# 🤖 PaperBot — บอทเทรดบัญชีทดลอง Alpaca ที่พัฒนาตัวเองได้

> **เงินจำลองเท่านั้น** โค้ดล็อก `paper=True` ไม่มีโหมดเงินจริง · ใช้เพื่อการเรียนรู้ ไม่ใช่คำแนะนำการลงทุน

## วงจรการทำงาน
```
 ┌─────────────┐   ┌──────────────┐   ┌───────────────────┐   ┌──────────────┐
 │① evolve.py  │──▶│② แชมป์        │──▶│③ bot.py (จ–ศ)       │──▶│④ เก็บข้อมูล      │
 │ GA 3 เกาะ    │   │ กฎที่ชนะ       │   │ bracket order ใน   │   │ trade จริง +   │
 │ (ส. 10:00)  │   │ forward test │   │ Alpaca paper 21:45 │   │ ผลเงาผู้ท้าชิง    │
 └─────▲───────┘   └──────────────┘   └───────────────────┘   └──────┬───────┘
       └──────────────── ผลจริงย้อนกลับไปตัดสินว่าใครได้เป็นแชมป์ ◀──────────────┘
```

## ติดตั้ง (ครั้งเดียว)
1. ติดตั้ง Python 3.10+ จาก python.org (ติ๊ก **Add python.exe to PATH**)
2. ดับเบิลคลิก **setup.bat** → Notepad จะเปิดไฟล์ `.env` → วาง **Paper** API Key ID และ Secret → บันทึก → ปิด
3. setup จะ: ทดสอบการเชื่อมต่อ → รัน evolve รอบแรก → ตั้ง Task Scheduler 2 งาน → เปิด dashboard

## ไฟล์
| ไฟล์ | หน้าที่ |
|---|---|
| `bot.py` | รอบประจำวัน: ปิด trade ที่ครบเวลา · บันทึก trade ที่โดน stop/target · ส่ง bracket order ตามกฎของแชมป์ |
| `evolve.py` | Genetic Algorithm 3 เกาะ (breakout / pullback / trend) · train 70% / holdout 30% · คัดผู้สมัคร · เลื่อนขั้นแชมป์จาก forward test |
| `strategy.py` | indicator, สัญญาณ, backtest, metrics (ใช้ร่วมกัน) |
| `dashboard.py` | สร้าง `data/dashboard.html` (กราฟ Lightweight Charts) |
| `config.json` | หุ้น 8 ตัว, ความเสี่ยงต่อ trade (0.5% ของ equity), จำนวน position สูงสุด ฯลฯ |
| `data/` | log, trades, equity, population (สมองของบอท) |
| `*.bat` | setup · run · evolve · dashboard · uninstall-tasks |

## กติกาสำคัญ (ทำไมออกแบบแบบนี้)
- **Bracket order**: ทุก trade มี stop และ target ตั้งแต่วินาทีแรก (แบบ day-trader-skill)
- **ถือไม่เกิน H วัน**: ครบแล้วปิดที่ราคาตลาด
- **ความเสี่ยงต่อ trade 0.5%** ของ equity (แชมป์ทดลองงานใช้ครึ่งเดียว) · position ละไม่เกิน 20% · ถือพร้อมกันไม่เกิน 4 ตัว
- **forward test คือผู้ตัดสิน**: กฎที่ GA หาเจอดูดีบนข้อมูลเก่าเสมอ (overfitting) จึงต้องพิสูจน์บนวันที่ยังไม่เกิดขึ้นตอนสร้างกฎ ≥ 15 trade ก่อนเลื่อนขั้น
- **เส้นโชคช่วย**: ยิ่งลองกฎมาก t-stat ที่ได้จากโชคล้วน ๆ ยิ่งสูง (≈ √(2 ln N)) ดูใน dashboard

## ให้ Claude ช่วยวิเคราะห์
ในแชท Claude desktop บอกว่า "วิเคราะห์ PaperBot" แล้วอนุญาตให้เข้าถึงโฟลเดอร์ `Documents\PaperBot` Claude จะอ่าน `data/` (ไม่อ่าน `.env`) แล้วเสนอการปรับปรุง

## ข้อจำกัด
- คอมต้องเปิดและล็อกอินอยู่ตอน 21:45 (จ–ศ) และ 10:00 วันเสาร์ ถ้าพลาดวันไหน รอบถัดไปจะจัดการต่อเอง
- แท่งรายวัน: เหมาะกับถือ 2–20 วัน ไม่ใช่ day trade
- Paper fill มักดีกว่าตลาดจริงเล็กน้อย

## เครดิต (ต่อยอดจากโปรเจกต์ของคนอื่น)
- [alpaca-py](https://github.com/alpacahq/alpaca-py) — SDK ทางการของ Alpaca (Apache-2.0)
- [TradingView Lightweight Charts](https://github.com/tradingview/lightweight-charts) — กราฟใน dashboard (Apache-2.0, ไฟล์ใน `lib/`)
- [day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) — แนวคิด bracket order, ชนทั้งคู่ = stop, verdict เทียบจุดคุ้มทุน
- mt-data-mcp / FinStoch / TradingView scripts — แนวคิดหลายโมเดลและ walk-forward (ดู Time Machine Lab)

## ☁️ รันบน GitHub Actions (ไม่ต้องเปิดคอม)
- workflow: `.github/workflows/paperbot.yml` · จ–ศ 14:45 UTC (21:45 ไทย) = `bot.py run` · เสาร์ 03:00 UTC (10:00 ไทย) = `evolve.py`
- key อยู่ใน **Settings → Secrets and variables → Actions**: `APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`
- รันเอง: แท็บ **Actions → PaperBot → Run workflow** เลือก `check` / `run` / `evolve`
- ดูผลบนมือถือ: แอป GitHub → repo นี้ → Actions → กดรอบล่าสุด → ตารางสรุป (Summary)
- ผลทุกรอบถูก commit กลับเข้าโฟลเดอร์ `data/` อัตโนมัติ
- ⚠️ ใช้ที่เดียว: ถ้ารันบน GitHub แล้ว ให้ปิดตัวตั้งเวลาในคอมด้วย `uninstall-tasks.bat`

## ⚡ (เดิม) บอท Day trade 4 หุ้น — ถูกแทนด้วย Scanner ด้านล่างแล้ว
```
ทุก 15 นาทีที่ตลาด US เปิด (GitHub Actions)
  ① บันทึก trade ที่ปิดแล้ว → ② เหลือ ≤ 35 นาทีก่อนปิด? ปิดทุกตัว
  → ③ ดูแท่ง 5 นาทีวันนี้ (IEX real-time) → สัญญาณของแชมป์? → bracket order (DAY)
เสาร์: evolve_dt.py หากฎใหม่จากแท่ง 5 นาทีย้อนหลัง 6 เดือน (SIP)
```
- กฎ 2 ตระกูล: **ORB** (ทะลุจุดสูงสุดของ 15–60 นาทีแรก) และ **VWAP cross** (ตัดขึ้นเหนือราคาเฉลี่ยถ่วงปริมาณ)
- แบ่งกัน: swing = AAPL MSFT GOOG TSM · day = TSLA NVDA META NFLX · ใช้เงินบอทละครึ่ง (`capital_share`)
- 1 trade/หุ้น/วัน · ปิดทุกตำแหน่งก่อนตลาดปิด · ถ้ารอบปิดท้ายพลาด รอบแรกของวันถัดไปจะปิดตำแหน่งค้างทันที
- เวลา Actions: ~32 รอบ/วัน × ~1 นาที ≈ 700–800 นาที/เดือน (โควตา private ฟรี 2,000)
- รันเอง: Actions → PaperBot → Run workflow → `dt` หรือ `evolve`

## 🧠 เทคนิคการเรียนรู้ทั้งหมด (อัปเดต 2026-11-07)
| ชั้น | เทคนิค | ทำหน้าที่ |
|---|---|---|
| กฎ swing (7 ตระกูล) | breakout · pullback (RSI2) · trend (SMA cross) · **bollinger** (mean reversion) · **macd** · **roc** (momentum) · **nr** (NR-n breakout) | ให้ GA มีวัตถุดิบหลากหลาย |
| กฎ day (4 ตระกูล) | orb · vwap · **momo** (แรงซื้อเช้า) · **dip** (ต่ำกว่า VWAP แล้วเด้ง) | ครอบคลุมทั้งตามเทรนด์และสวนเทรนด์ |
| ตัวกรอง | **regime** (swing: เทรดเฉพาะเหนือ SMA ยาว) · **gap** (day: เลือกวันตาม gap เปิด) | GA เลือกเปิด/ปิดเอง |
| การค้นหา | Genetic Algorithm แบบ **island model** (1 เกาะต่อ 1 ตระกูล) + สะสมผู้สมัครจากรอบก่อน | กันทุกตัวหน้าตาเหมือนกัน |
| คะแนน | **robust fitness** = t-stat × ความสม่ำเสมอ (train แบ่ง 3 ช่วง) | ลงโทษกฎที่รวยช่วงเดียว |
| กันหลอกตัวเอง | holdout 30% · **stability test** (ขยับพารามิเตอร์ ±6% แล้วต้องยังกำไร ≥ 50%) · เส้นโชคช่วย √(2 ln N) | แยก "เก่งจริง" ออกจาก "บังเอิญ" |
| ผู้ตัดสินสุดท้าย | **forward test** แบบเงาของผู้สมัครทุกตัว (≥15 swing / ≥20 day trade) | ข้อมูลที่ไม่มีใครเคยเห็น |

## 🔭 Day trade Scanner (dt.py + scanstrat.py + evolve_scan.py) — ใช้แทนบอท day 4 หุ้น
```
ทุกเสาร์: หุ้น US ทั้งหมด (~5,000+) → คัด 300 ตัวที่มูลค่าซื้อขาย/วันสูงสุด (ราคา ≥ $5, ไม่รวมหุ้น swing) → data/universe.json
          โหลดแท่ง 5 นาที 120 วันของ 300 ตัว → GA หากฎ (เกาะ open / prevclose)
ทุกวัน ณ นาทีที่ M ของแชมป์: สแกน 300 ตัว → จัดอันดับ "ขึ้นแรงที่สุดตั้งแต่เช้า" → ซื้อ K อันดับแรก (bracket DAY)
ก่อนตลาดปิด 35 นาที: ขายทุกตัว
```
- ยีน: M (15–120 นาที) · K (1–5 ตัว) · วัดจากราคาเปิดหรือราคาปิดเมื่อวาน · th ขั้นต่ำ · ตัวกรอง gap · stop (× ATR) · target R
- เทียบกับ baseline: ซื้อทุกตัวใน universe ตอนเปิด ขายตอนปิด
- ⚠️ ข้อจำกัด: universe เลือกจากสภาพคล่อง "ปัจจุบัน" แล้วใช้กับอดีต (survivorship bias เล็กน้อย) · ราคาสดใช้ IEX ส่วนประวัติใช้ SIP
