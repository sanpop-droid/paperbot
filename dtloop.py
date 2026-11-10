"""dtloop.py — GitHub Actions job=dtloop: ปลุกตัวเองทั้งวัน ไม่พึ่ง cron ที่ GitHub ชอบช้า
  1) รอจนตลาดเปิด (ถ้าเริ่มก่อนเปิด ≤ 2 ชม.) · ตลาดปิดของวันนี้ไปแล้ว → จบทันที
  2) ตลาดเปิด: python bot.py run วันละครั้ง แล้ว python dt.py ทุก 5 นาที จนตลาดปิด
  3) commit data ทุก ~30 นาที · ใกล้หมดเวลา job (340 นาที) แต่ตลาดยังเปิด → สั่ง workflow_dispatch job=dtloop ต่อ
คำสั่งซื้อขายมาจาก bot.py / dt.py เดิมเท่านั้น (ล็อก paper ที่ common.base_url) ไฟล์นี้แค่เรียกตามเวลา
"""
import os, sys, json, time, subprocess, urllib.request, datetime as dt
from common import load_json, save_json

STEP = 300              # วินาทีระหว่างรอบ dt
BUDGET = 340 * 60       # ต่ำกว่า timeout ของ step (348) / job (355) ให้มีเวลา commit + dispatch
WAIT_OPEN = 2 * 3600    # ตัวเริ่ม 13:00–14:40 UTC อยู่ก่อนตลาดเปิดไม่เกินนี้ทั้ง EST/EDT
COMMIT_EVERY = 1800

def log(msg):
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M} [loop] {msg}", flush=True)

def decide(clk, now, elapsed):
    """'run' = ตลาดเปิด, 'wait' = รอเปิด, 'stop' = จบวันนี้, 'next' = หมดเวลา job แต่ตลาดยังเปิด"""
    if elapsed >= BUDGET:
        return "next" if clk["is_open"] else "stop"
    if clk["is_open"]:
        return "run"
    return "wait" if (clk["next_open"] - now).total_seconds() <= WAIT_OPEN else "stop"

def clock():
    from bot import AlpacaBroker
    return AlpacaBroker().clock()

def sh(*cmd):
    # แยก process: dt.py พังรอบเดียวไม่ทำให้ loop หยุด (dt.py log ERROR เองอยู่แล้ว)
    r = subprocess.run([sys.executable, *cmd])
    if r.returncode:
        log(f"ERROR {' '.join(cmd)} exit {r.returncode}")

def commit():
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    subprocess.run(["bash", "-c", 'git add data && (git diff --cached --quiet || git commit -qm "data: dtloop $(date -u +%F)")'
                    ' && (git push -q || (git pull -q --rebase && git push -q))'])

def dispatch():
    # shortcut: concurrency เก็บ pending ได้ 1 → cron dt ที่เข้าคิวทีหลังอาจแทนที่รอบนี้ (เหลือ dt */5–*/15 เป็นสำรอง), ถ้าเกิดบ่อยค่อยแยก group ให้ dtloop
    repo, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GH_TOKEN")
    if not repo or not token:
        log("ERROR dispatch: ไม่มี GITHUB_REPOSITORY/GH_TOKEN"); return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/workflows/paperbot.yml/dispatches", method="POST",
        data=json.dumps({"ref": os.environ.get("GITHUB_REF_NAME", "main"), "inputs": {"job": "dtloop"}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        urllib.request.urlopen(req, timeout=30); log("ตลาดยังเปิด → สั่ง dtloop รอบต่อไปแล้ว")
    except Exception as e:
        log(f"ERROR dispatch: {e} (cron dt */15 ยังเป็นสำรอง)")

def main():
    t0 = last_commit = time.monotonic(); ran = False
    while True:
        try:
            clk = clock()
        except Exception as e:   # เน็ต/API สะดุดชั่วคราว → ลองใหม่รอบหน้า แทนที่จะทิ้งทั้งวัน
            log(f"ERROR clock: {e}"); time.sleep(STEP); continue
        act = decide(clk, dt.datetime.now(dt.timezone.utc), time.monotonic() - t0)
        if act == "run":
            mark = load_json("dtloop.json", {})
            if mark.get("swing_day") != clk["today"]:   # swing วันละครั้ง แม้ loop ถูกสั่งต่อหลายรอบ
                sh("bot.py", "run"); save_json("dtloop.json", {"swing_day": clk["today"]})
            sh("dt.py"); ran = True
        elif act == "wait":
            log(f"รอตลาดเปิด {clk['next_open']}")
        else:
            if ran: sh("dt.py")   # รอบสุดท้ายหลังปิด: บันทึก trade ที่ปิดตอนท้ายตลาด
            commit()
            if act == "next": dispatch()
            log("จบ dtloop" + (" (ส่งต่อรอบใหม่)" if act == "next" else ": ตลาดปิดแล้ว"))
            return
        if time.monotonic() - last_commit >= COMMIT_EVERY:
            commit(); last_commit = time.monotonic()
        time.sleep(STEP)

if __name__ == "__main__":
    main()
