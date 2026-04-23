import base64
import json
import time
import os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from telegram import (
    Bot,
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "data.json")

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
DAILY_RESET_SECONDS = (24 * 3600) + (55 * 60)  # 24h 55m = 89700 seconds


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


# ---------------- UI ----------------
def menu():
    return ReplyKeyboardMarkup(
        [
            ["▶️ Start Epoch", "📊 Status"],
            ["🕒 Set Time", "🔄 Reset"],
            ["📈 Analysis"]
        ],
        resize_keyboard=True
    )


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

    # Calculate which day and epoch within that day
    days_passed = elapsed // DAILY_RESET_SECONDS
    elapsed_in_day = elapsed % DAILY_RESET_SECONDS

    epoch = min((elapsed_in_day // EPOCH_SECONDS) + 1, TOTAL_EPOCHS)
    
    # Daily usable epochs (172 per day)
    daily_usable = 12000 // 70  # 172
    taps_done = min(epoch, daily_usable) * 70
    taps_left = max(12000 - taps_done, 0)

    h = elapsed_in_day // 3600
    m = (elapsed_in_day % 3600) // 60

    rem = DAILY_RESET_SECONDS - elapsed_in_day
    rh = rem // 3600
    rm = (rem % 3600) // 60

    # Times for this day
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


# Store day history
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
    
    # Check if this day already exists
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
    
    # Record this day
    add_day_record(state, state["start_time"])

    if state.get("msg_id"):
        try:
            await bot.edit_message_text(
                chat_id=int(chat),
                message_id=int(state["msg_id"]),
                text=text,
                reply_markup=menu()
            )
            return
        except Exception as e:
            print(f"Edit error: {e}")

    msg = await bot.send_message(int(chat), text, reply_markup=menu())
    state["msg_id"] = msg.message_id

    try:
        c = await bot.get_chat(int(chat))
        if c.type != "private":
            await bot.pin_chat_message(int(chat), msg.message_id, disable_notification=True)
    except:
        pass


def build_analysis(state):
    if "days" not in state or not state["days"]:
        return "📈 No data yet. Start an epoch first!"
    
    days = state["days"]
    emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    
    text = "📈 Analysis - Daily Cycle History\n\n"
    
    for d in days:
        emoji = emojis[min(d['day_num'] - 1, 9)]
        text += f"Day {emoji}\n"
        text += f"Start: {d['start_date']} | {d['start_time']}\n"
        text += f"Reset: {d['reset_date']} | {d['reset_time']}\n"
        text += "\n"
    
    return text


# ---------------- HANDLER ----------------
TEMP = {}

async def handle(update: Update):
    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)
    key = f"{chat}:{user}"

    store, sha = load_data()
    state = store.get(key, {})

    # CALLBACK (manual time)
    if update.callback_query:
        q = update.callback_query
        await q.answer()

        if user not in TEMP:
            TEMP[user] = {}

        d = q.data

        if d.startswith("h_"):
            TEMP[user]["h"] = int(d.split("_")[1])
            await bot.send_message(int(chat), "Select Minute:", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"{i:02}", callback_data=f"m_{i}") for i in range(0,60,10)]
            ]))
            return

        elif d.startswith("m_"):
            if "h" not in TEMP.get(user, {}):
                await q.edit_message_text("❌ Use 🕒 Set Time again")
                return
            TEMP[user]["m"] = int(d.split("_")[1])
            await bot.send_message(int(chat), "AM or PM?", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("AM", callback_data="am"), InlineKeyboardButton("PM", callback_data="pm")]
            ]))
            return

        elif d in ["am","pm"]:
            if "h" not in TEMP.get(user, {}) or "m" not in TEMP.get(user, {}):
                await q.edit_message_text("❌ Use 🕒 Set Time again")
                return
                
            h = TEMP[user]["h"]
            m = TEMP[user]["m"]

            if d == "pm" and h != 12:
                h += 12
            if d == "am" and h == 12:
                h = 0

            now = datetime.now(IST)
            t = now.replace(hour=h, minute=m, second=0)

            if t > now:
                t -= timedelta(days=1)

            state["start_time"] = int(t.timestamp())
            state["msg_id"] = None
            state["days"] = []

            store[key] = state
            save_data(store, sha)
            
            TEMP[user] = {}

            await q.edit_message_text(f"✅ Set {t.strftime('%I:%M %p')} IST")
            return

        return

    if not update.message:
        return

    text = (update.message.text or "").lower().strip()

    if text == "/start":
        if "start_time" in state:
            await bot.send_message(int(chat), "👋 Welcome back!\nRefreshing your current status...", reply_markup=menu())
            await dashboard(chat, state)
        else:
            await bot.send_message(int(chat), "👋 Welcome!\nUse ▶️ Start Epoch to begin.", reply_markup=menu())
        return

    elif text == "▶️ start epoch":
        state = {"start_time": int(time.time()), "msg_id": None, "days": []}
        store[key] = state
        save_data(store, sha)
        await dashboard(chat, state)
        store[key] = state
        save_data(store, sha)
        return

    elif text == "📊 status":
        if "start_time" not in state:
            await bot.send_message(int(chat), "❌ Start first", reply_markup=menu())
            return

        await dashboard(chat, state)
        store[key] = state
        save_data(store, sha)
        return

    elif text == "🕒 set time":
        TEMP[user] = {}
        await bot.send_message(int(chat), "Select Hour:", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(str(i), callback_data=f"h_{i}") for i in range(1,13)]
        ]))
        return

    elif text == "📈 analysis":
        if "start_time" not in state:
            await bot.send_message(int(chat), "❌ Start first", reply_markup=menu())
            return
        
        analysis = build_analysis(state)
        await bot.send_message(int(chat), analysis, parse_mode="HTML", reply_markup=menu())
        return

    elif text == "🔄 reset":
        if key in store:
            del store[key]
            save_data(store, sha)
        await bot.send_message(int(chat), "🗑️ Reset done", reply_markup=menu())
        return

    else:
        await bot.send_message(int(chat), "👇 Use menu", reply_markup=menu())
        return


# ---------------- ASGI ENTRY ----------------
async def app(scope, receive, send):
    if scope["type"] == "http":
        body=b""
        more=True
        while more:
            m=await receive()
            body+=m.get("body",b"")
            more=m.get("more_body",False)

        try:
            data=json.loads(body.decode())
            update=Update.de_json(data,bot)
            await handle(update)
        except Exception as e:
            print(e)

        await send({"type":"http.response.start","status":200})
        await send({"type":"http.response.body","body":b"ok"})
