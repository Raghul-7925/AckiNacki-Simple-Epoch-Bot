import base64
import json
import time
import os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

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
TOTAL_SECONDS = EPOCH_SECONDS * TOTAL_EPOCHS

DAILY_TAP_LIMIT = 12000
TAPS_PER_EPOCH = 70
DAILY_USABLE_EPOCHS = DAILY_TAP_LIMIT // TAPS_PER_EPOCH


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
            ["🕒 Set Time", "🔄 Reset"]
        ],
        resize_keyboard=True
    )

def hour_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1", callback_data="h_1"),
         InlineKeyboardButton("2", callback_data="h_2"),
         InlineKeyboardButton("3", callback_data="h_3")],

        [InlineKeyboardButton("4", callback_data="h_4"),
         InlineKeyboardButton("5", callback_data="h_5"),
         InlineKeyboardButton("6", callback_data="h_6")],

        [InlineKeyboardButton("7", callback_data="h_7"),
         InlineKeyboardButton("8", callback_data="h_8"),
         InlineKeyboardButton("9", callback_data="h_9")],

        [InlineKeyboardButton("10", callback_data="h_10"),
         InlineKeyboardButton("11", callback_data="h_11"),
         InlineKeyboardButton("12", callback_data="h_12")],
    ])

def minute_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("00", callback_data="m_0"),
         InlineKeyboardButton("05", callback_data="m_5"),
         InlineKeyboardButton("10", callback_data="m_10")],

        [InlineKeyboardButton("15", callback_data="m_15"),
         InlineKeyboardButton("20", callback_data="m_20"),
         InlineKeyboardButton("25", callback_data="m_25")],

        [InlineKeyboardButton("30", callback_data="m_30"),
         InlineKeyboardButton("35", callback_data="m_35"),
         InlineKeyboardButton("40", callback_data="m_40")],

        [InlineKeyboardButton("45", callback_data="m_45"),
         InlineKeyboardButton("50", callback_data="m_50"),
         InlineKeyboardButton("55", callback_data="m_55")],
    ])

def ampm_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("AM", callback_data="am"),
         InlineKeyboardButton("PM", callback_data="pm")]
    ])


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

    epoch = min((elapsed // EPOCH_SECONDS) + 1, TOTAL_EPOCHS)

    taps_done = min(epoch, DAILY_USABLE_EPOCHS) * TAPS_PER_EPOCH
    taps_left = max(DAILY_TAP_LIMIT - taps_done, 0)

    h = elapsed // 3600
    m = (elapsed % 3600) // 60

    rem = TOTAL_SECONDS - elapsed
    rh = rem // 3600
    rm = (rem % 3600) // 60

    p1 = datetime.fromtimestamp(start, IST)
    p2 = datetime.fromtimestamp(start + 96 * EPOCH_SECONDS, IST)
    p3 = datetime.fromtimestamp(start + 192 * EPOCH_SECONDS, IST)
    reset = datetime.fromtimestamp(start + TOTAL_SECONDS, IST)

    return {
        "epoch": epoch,
        "part": get_part(epoch),
        "h": h,
        "m": m,
        "taps_done": taps_done,
        "taps_left": taps_left,
        "usable": min(epoch, DAILY_USABLE_EPOCHS),
        "rh": rh,
        "rm": rm,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "reset": reset
    }


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
        f"• Taps: {s['taps_done']:,}/{DAILY_TAP_LIMIT:,}\n\n"

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

    if state.get("msg_id"):
        try:
            await bot.edit_message_text(
                chat_id=int(chat),
                message_id=int(state["msg_id"]),
                text=text,
                reply_markup=menu()
            )
            return
        except:
            pass

    msg = await bot.send_message(int(chat), text, reply_markup=menu())
    state["msg_id"] = msg.message_id


# ---------------- HANDLER ----------------
TEMP = {}

async def handle(update: Update):
    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)
    key = f"{chat}:{user}"

    store, sha = load_data()
    state = store.get(key, {})

    # CALLBACK FLOW
    if update.callback_query:
        q = update.callback_query
        await q.answer()

        if user not in TEMP:
            TEMP[user] = {}

        d = q.data

        if d.startswith("h_"):
            TEMP[user]["h"] = int(d.split("_")[1])
            await bot.send_message(int(chat), "Select Minute:", reply_markup=minute_keyboard())
            return

        if d.startswith("m_"):
            if "h" not in TEMP[user]:
                return
            TEMP[user]["m"] = int(d.split("_")[1])
            await bot.send_message(int(chat), "Select AM/PM:", reply_markup=ampm_keyboard())
            return

        if d in ["am", "pm"]:
            if "h" not in TEMP[user] or "m" not in TEMP[user]:
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

            store[key] = state
            save_data(store, sha)

            TEMP[user] = {}

            await bot.send_message(int(chat), f"✅ Set {t.strftime('%I:%M %p')} IST")
            return

        return

    if not update.message:
        return

    # prevent spam during inline flow
    if user in TEMP and TEMP[user]:
        return

    text = (update.message.text or "").lower().strip()

    if text in ["▶️ start epoch", "/start"]:
        state = {"start_time": int(time.time()), "msg_id": None}
        store[key] = state
        save_data(store, sha)
        await dashboard(chat, state)

    elif text == "📊 status":
        if "start_time" not in state:
            await bot.send_message(int(chat), "❌ Start first", reply_markup=menu())
            return
        await dashboard(chat, state)

    elif text == "🕒 set time":
        TEMP[user] = {}
        await bot.send_message(int(chat), "Select Hour (IST):", reply_markup=hour_keyboard())

    elif text == "🔄 reset":
        if key in store:
            del store[key]
            save_data(store, sha)
        await bot.send_message(int(chat), "🗑️ Reset done", reply_markup=menu())

    else:
        await bot.send_message(int(chat), "👇 Use menu", reply_markup=menu())


# ---------------- ENTRY ----------------
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
