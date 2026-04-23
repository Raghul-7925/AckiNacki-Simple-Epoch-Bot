import base64
import json
import time
import os
import re
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from telegram import Bot, Update

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "data.json")
OWNER_IDS = os.environ.get("1837260280")  # comma-separated Telegram user IDs

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
DAILY_RESET_SECONDS = (24 * 3600) + (55 * 60)  # 24h 55m = 89700 seconds

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]


# ---------------- GITHUB ----------------
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

def load_data():
    try:
        req = Request(GITHUB_API)
        for k, v in gh_headers().items():
            req.add_header(k, v)

        res = urlopen(req).read()
        data = json.loads(res)

        content = base64.b64decode(data["content"]).decode()
        return json.loads(content), data["sha"]
    except:
        return {}, None

def save_data(store, sha):
    body = {
        "message": "update",
        "content": base64.b64encode(json.dumps(store).encode()).decode(),
        "branch": "main"
    }
    if sha:
        body["sha"] = sha

    req = Request(GITHUB_API, data=json.dumps(body).encode(), method="PUT")
    for k, v in gh_headers().items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    urlopen(req)


# ---------------- CALC ----------------
def get_part(e):
    if e <= 96:
        return "Part 1 (High reward)"
    elif e <= 192:
        return "Part 2 (Medium reward)"
    else:
        return "Part 3 (Low reward)"


def stats(start):
    now = int(time.time())
    elapsed = now - start

    days_passed = elapsed // DAILY_RESET_SECONDS
    elapsed_in_day = elapsed % DAILY_RESET_SECONDS

    epoch = min((elapsed_in_day // EPOCH_SECONDS) + 1, TOTAL_EPOCHS)

    daily_usable = 12000 // 70  # 172
    taps_done = min(epoch, daily_usable) * 70
    taps_left = max(12000 - taps_done, 0)

    h = elapsed_in_day // 3600
    m = (elapsed_in_day % 3600) // 60

    rem = DAILY_RESET_SECONDS - elapsed_in_day
    rh = rem // 3600
    rm = (rem % 3600) // 60

    day_start = start + (days_passed * DAILY_RESET_SECONDS)
    p1 = datetime.fromtimestamp(day_start, IST)
    p2 = datetime.fromtimestamp(day_start + 96 * EPOCH_SECONDS, IST)
    p3 = datetime.fromtimestamp(day_start + 192 * EPOCH_SECONDS, IST)
    reset = datetime.fromtimestamp(day_start + DAILY_RESET_SECONDS, IST)

    return {
        "epoch": epoch,
        "part": get_part(epoch),
        "h": h,
        "m": m,
        "taps_done": taps_done,
        "taps_left": taps_left,
        "usable": min(epoch, daily_usable),
        "rh": rh,
        "rm": rm,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "reset": reset,
        "day": days_passed + 1
    }


def add_day_record(state, start_ts):
    if "days" not in state:
        state["days"] = []

    now = int(time.time())
    elapsed = now - start_ts
    days_passed = elapsed // DAILY_RESET_SECONDS

    day_start_ts = start_ts + (days_passed * DAILY_RESET_SECONDS)
    reset_ts = day_start_ts + DAILY_RESET_SECONDS

    day_start_dt = datetime.fromtimestamp(day_start_ts, IST)
    reset_dt = datetime.fromtimestamp(reset_ts, IST)

    record = {
        "day_num": days_passed + 1,
        "start_date": day_start_dt.strftime("%d %b %Y"),
        "start_time": day_start_dt.strftime("%I:%M %p"),
        "reset_date": reset_dt.strftime("%d %b %Y"),
        "reset_time": reset_dt.strftime("%I:%M %p")
    }

    if not any(d["day_num"] == record["day_num"] for d in state["days"]):
        state["days"].append(record)


# ---------------- DASHBOARD ----------------
def build(start):
    s = stats(start)

    text = (
        f"📊 Live Dashboard\n\n"
        f"⏱️ {s['h']}h {s['m']}m\n"
        f"🔢 Epoch: {s['epoch']}/288\n"
        f"📍 {s['part']}\n\n"

        f"🪙 Daily\n"
        f"• Epochs: {s['usable']}/172\n"
        f"• Taps: {s['taps_done']:,}/12,000\n\n"

        f"📊 Taps\n"
        f"• Done: {s['taps_done']:,}\n"
        f"• Left: {s['taps_left']:,}\n\n"

        f"🧭 Phase Timings:\n"
        f"• Part 1: {s['p1'].strftime('%d %b %I:%M %p')} IST\n"
        f"• Part 2: {s['p2'].strftime('%d %b %I:%M %p')} IST\n"
        f"• Part 3: {s['p3'].strftime('%d %b %I:%M %p')} IST\n\n"

        f"⏳ Left: {s['rh']}h {s['rm']}m\n"
        f"🔁 Reset: {s['reset'].strftime('%d %b %I:%M %p')} IST"
    )

    return text


async def dashboard(chat, state):
    text = build(state["start_time"])
    add_day_record(state, state["start_time"])

    if state.get("msg_id"):
        try:
            await bot.delete_message(
                chat_id=int(chat),
                message_id=int(state["msg_id"])
            )
        except Exception as e:
            print(f"Delete error: {e}")

    msg = await bot.send_message(int(chat), text)
    state["msg_id"] = msg.message_id

    try:
        c = await bot.get_chat(int(chat))
        if c.type != "private":
            await bot.pin_chat_message(
                int(chat),
                msg.message_id,
                disable_notification=True
            )
    except Exception as e:
        print(f"Pin error: {e}")


def build_analysis(state):
    if "days" not in state or not state["days"]:
        return "📈 No data yet. Start an epoch first!"

    days = state["days"]
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    text = "📈 Analysis - Daily Cycle History\n\n"

    for d in days:
        emoji = emojis[min(d["day_num"] - 1, 9)]
        text += f"Day {emoji}\n"
        text += f"Start: {d['start_date']} | {d['start_time']}\n"
        text += f"Reset: {d['reset_date']} | {d['reset_time']}\n\n"

    return text


def parse_set_time(raw_text):
    m = re.match(r"^\s*/set(?:\s+)?(\d{1,2}):(\d{2})\s*([ap]m)\s*$", raw_text, re.IGNORECASE)
    if not m:
        return None

    h = int(m.group(1))
    mi = int(m.group(2))
    ap = m.group(3).lower()

    if h < 1 or h > 12:
        return None
    if mi not in (0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55):
        return None

    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0

    now = datetime.now(IST)
    t = now.replace(hour=h, minute=mi, second=0, microsecond=0)

    if t > now:
        t -= timedelta(days=1)

    return int(t.timestamp()), t


# ---------------- HANDLER ----------------
async def handle(update: Update):
    # hard block: only owner IDs can trigger any behavior
    if not update.effective_user:
        return
    if not OWNER_LIST:
        return
    if str(update.effective_user.id) not in OWNER_LIST:
        return

    if not update.effective_chat:
        return

    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)
    key = f"{chat}:{user}"

    store, sha = load_data()
    state = store.get(key, {})

    if not update.message:
        return

    text = (update.message.text or "").strip()
    low = text.lower()

    if low == "/start":
        if "start_time" in state:
            await bot.send_message(int(chat), "👋 Welcome back!\nRefreshing your current status...")
            await dashboard(chat, state)
            store[key] = state
            save_data(store, sha)
        else:
            await bot.send_message(int(chat), "👋 Welcome!\nUse /epoch to start and /set HH:MM AM/PM to set time.")
        return

    elif low == "/epoch":
        state = {"start_time": int(time.time()), "msg_id": None, "days": []}
        store[key] = state
        save_data(store, sha)

        await bot.send_message(int(chat), "✅ Epoch started.")
        await dashboard(chat, state)

        store[key] = state
        save_data(store, sha)
        return

    elif low.startswith("/set"):
        parsed = parse_set_time(text)
        if not parsed:
            await bot.send_message(
                int(chat),
                "❌ Use /set HH:MM AM or /set HH:MM PM\nExample: /set 05:30 PM"
            )
            return

        ts, t = parsed

        if "start_time" not in state:
            state = {"start_time": ts, "msg_id": None, "days": []}
        else:
            state["start_time"] = ts
            state["msg_id"] = None
            state["days"] = []

        store[key] = state
        save_data(store, sha)

        await bot.send_message(int(chat), f"✅ Set {t.strftime('%I:%M %p')} IST")
        await dashboard(chat, state)

        store[key] = state
        save_data(store, sha)
        return

    elif low == "/status":
        if "start_time" not in state:
            await bot.send_message(int(chat), "❌ Start first using /epoch")
            return

        await dashboard(chat, state)
        store[key] = state
        save_data(store, sha)
        return

    elif low == "/analysis":
        if "start_time" not in state:
            await bot.send_message(int(chat), "❌ Start first using /epoch")
            return

        analysis = build_analysis(state)
        await bot.send_message(int(chat), analysis)
        return

    else:
        return


# ---------------- ASGI ENTRY ----------------
async def app(scope, receive, send):
    if scope["type"] == "http":
        body = b""
        more = True
        while more:
            m = await receive()
            body += m.get("body", b"")
            more = m.get("more_body", False)

        try:
            data = json.loads(body.decode())
            update = Update.de_json(data, bot)
            await handle(update)
        except Exception as e:
            print(e)

        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"ok"})
