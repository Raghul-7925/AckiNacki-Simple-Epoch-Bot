import base64
import json
import time
import os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from telegram import Bot, Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "data.json")

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = EPOCH_SECONDS * TOTAL_EPOCHS

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"


# ---------------- GITHUB ----------------

def headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "epoch-bot"
    }


def load_data():
    try:
        req = Request(GITHUB_API)
        for k, v in headers().items():
            req.add_header(k, v)

        res = urlopen(req).read()
        data = json.loads(res)

        content = base64.b64decode(data["content"]).decode()
        return json.loads(content), data["sha"]

    except HTTPError as e:
        if e.code == 404:
            return {}, None
        return {}, None
    except:
        return {}, None


def save_data(store, sha):
    body = {
        "message": "update",
        "content": base64.b64encode(json.dumps(store, indent=2).encode()).decode(),
        "branch": "main"
    }

    if sha:
        body["sha"] = sha

    req = Request(GITHUB_API, data=json.dumps(body).encode(), method="PUT")
    for k, v in headers().items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")

    urlopen(req)


# ---------------- MENU ----------------

def menu():
    return ReplyKeyboardMarkup(
        [
            ["▶️ Start Epoch", "📊 Status"],
            ["🕒 Set Time", "🔄 Reset"],
            ["ℹ️ Help"]
        ],
        resize_keyboard=True
    )


# ---------------- KEY ----------------

def key(chat, user):
    return f"{chat}:{user}"


# ---------------- STATUS ----------------

def get_part(e):
    if e <= 96:
        return "Part 1 (High reward)"
    elif e <= 192:
        return "Part 2 (Medium reward)"
    else:
        return "Part 3 (Low reward)"


def build(start):
    now = int(time.time())
    elapsed = now - start

    epoch = min((elapsed // EPOCH_SECONDS) + 1, TOTAL_EPOCHS)

    part = get_part(epoch)

    h = elapsed // 3600
    m = (elapsed % 3600) // 60

    rem = max(TOTAL_SECONDS - elapsed, 0)
    rh = rem // 3600
    rm = (rem % 3600) // 60

    p1 = datetime.fromtimestamp(start, IST)
    p2 = datetime.fromtimestamp(start + 96 * EPOCH_SECONDS, IST)
    p3 = datetime.fromtimestamp(start + 192 * EPOCH_SECONDS, IST)
    reset = datetime.fromtimestamp(start + TOTAL_SECONDS, IST)

    text = (
        f"📊 Live Dashboard\n\n"
        f"⏱️ {h}h {m}m\n"
        f"🔢 Epoch: {epoch}/288\n"
        f"📍 {part}\n\n"
        f"🧭 Phase Timings:\n"
        f"• Part 1: {p1.strftime('%d %b %I:%M %p')} IST\n"
        f"• Part 2: {p2.strftime('%d %b %I:%M %p')} IST\n"
        f"• Part 3: {p3.strftime('%d %b %I:%M %p')} IST\n\n"
        f"⏳ Left: {rh}h {rm}m\n"
        f"🔁 Reset: {reset.strftime('%d %b %I:%M %p')} IST"
    )

    return text, epoch


# ---------------- DASHBOARD ----------------

async def dashboard(chat_id, state):
    text, epoch = build(state["start_time"])

    if state.get("msg_id"):
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=state["msg_id"], text=text)
            return epoch
        except:
            pass

    msg = await bot.send_message(chat_id, text, reply_markup=menu())
    state["msg_id"] = msg.message_id

    try:
        chat = await bot.get_chat(chat_id)
        if chat.type != "private":
            await bot.pin_chat_message(chat_id, msg.message_id, disable_notification=True)
    except:
        pass

    return epoch


# ---------------- TIME PICKER ----------------

TEMP = {}

def hours():
    return InlineKeyboardMarkup([[InlineKeyboardButton(str(i), callback_data=f"h_{i}") for i in range(j, j+3)] for j in range(1, 13, 3)])

def mins():
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{i:02}", callback_data=f"m_{i}") for i in range(j, j+15, 5)] for j in range(0, 60, 15)])

def ampm():
    return InlineKeyboardMarkup([[InlineKeyboardButton("AM", callback_data="am"), InlineKeyboardButton("PM", callback_data="pm")]])


# ---------------- MAIN ----------------

async def handle(update: Update):
    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)
    k = key(chat, user)

    store, sha = load_data()
    state = store.get(k, {})

    # CALLBACK
    if update.callback_query:
        q = update.callback_query
        await q.answer()

        if user not in TEMP:
            TEMP[user] = {}

        data = q.data

        if data.startswith("h_"):
            TEMP[user]["h"] = int(data.split("_")[1])
            await bot.send_message(chat, "Select Minute:", reply_markup=mins())

        elif data.startswith("m_"):
            TEMP[user]["m"] = int(data.split("_")[1])
            await bot.send_message(chat, "Select AM/PM:", reply_markup=ampm())

        elif data in ["am", "pm"]:
            h = TEMP[user]["h"]
            m = TEMP[user]["m"]

            if data == "pm" and h != 12:
                h += 12
            if data == "am" and h == 12:
                h = 0

            now = datetime.now(IST)
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)

            if t > now:
                t -= timedelta(days=1)

            state["start_time"] = int(t.timestamp())
            state["msg_id"] = None
            state["last_epoch"] = 0

            store[k] = state
            save_data(store, sha)

            await bot.send_message(chat, f"✅ Set to {t.strftime('%I:%M %p')} IST", reply_markup=menu())

        return

    if not update.message:
        return

    text = (update.message.text or "").lower()

    # START
    if text in ["▶️ start epoch", "/start"]:
        state = {
            "start_time": int(time.time()),
            "msg_id": None,
            "last_epoch": 0
        }
        store[k] = state
        save_data(store, sha)

        await bot.send_message(chat, "🟢 Started", reply_markup=menu())

    # STATUS
    elif text == "📊 status":
        if "start_time" not in state:
            await bot.send_message(chat, "❌ Start first", reply_markup=menu())
            return

        epoch = await dashboard(chat, state)

        if epoch != state.get("last_epoch", 0):
            if epoch == 97:
                await bot.send_message(chat, "🚀 Part 2 Started")
            elif epoch == 193:
                await bot.send_message(chat, "⚠️ Part 3 Started")

        state["last_epoch"] = epoch
        store[k] = state
        save_data(store, sha)

    # SET TIME
    elif text == "🕒 set time":
        await bot.send_message(chat, "Select Hour:", reply_markup=hours())

    # RESET
    elif text == "🔄 reset":
        if k in store:
            del store[k]
            save_data(store, sha)
        await bot.send_message(chat, "🗑️ Cleared", reply_markup=menu())

    # HELP
    elif text == "ℹ️ help":
        await bot.send_message(chat, "Use buttons", reply_markup=menu())

    else:
        await bot.send_message(chat, "👇 Choose", reply_markup=menu())


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
            print("ERROR:", e)

        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"ok"})tate["pending"] = {}
        state["msg_id"] = None

        store[key] = state
        await send_or_edit_dashboard(
            chat_id,
            state,
            prefix="🟢 Epoch started\n\n"
        )
        store[key] = state
        github_save_store(store, sha)
        return

    # STATUS
    if text == "📊 status":
        if "start_time" not in state:
            await bot.send_message(chat_id, "❌ Start first", reply_markup=get_menu())
            return

        info = epoch_info(state["start_time"])

        store[key] = state
        await send_or_edit_dashboard(chat_id, state, prefix="")

        # alerts on part change
        previous_epoch = int(state.get("last_epoch", 0) or 0)
        current_epoch = int(info["epoch"])

        if current_epoch != previous_epoch:
            if current_epoch == 97:
                await bot.send_message(chat_id, "🚀 Part 2 Started")
            elif current_epoch == 193:
                await bot.send_message(chat_id, "⚠️ Part 3 Started")

            state["last_epoch"] = current_epoch

        store[key] = state
        github_save_store(store, sha)
        return

    # SET TIME
    if text == "🕒 set time":
        state["pending"] = {"step": "hour"}
        store[key] = state
        github_save_store(store, sha)

        await bot.send_message(chat_id, "Select Hour (IST):", reply_markup=hour_keyboard())
        return

    # RESET
    if text == "🔄 reset":
        if key in store:
            del store[key]
            github_save_store(store, sha)

        await bot.send_message(
            chat_id,
            "🗑️ Your data has been deleted.\n\nStart again using ▶️ Start Epoch.",
            reply_markup=get_menu()
        )
        return

    # HELP
    if text == "ℹ️ help":
        await bot.send_message(
            chat_id,
            "📘 How to use this bot:\n\n"
            "1️⃣ Click ▶️ Start Epoch to begin now.\n"
            "2️⃣ Click 🕒 Set Time to manually set a past IST time.\n"
            "3️⃣ Click 📊 Status to see the live dashboard.\n"
            "4️⃣ Click 🔄 Reset to delete your saved data.\n\n"
            "⏱️ Each epoch = 5 minutes 30 seconds\n"
            "🔢 Total = 288 epochs\n"
            "🧭 Part 1 / Part 2 / Part 3 timings are shown in Status.",
            reply_markup=get_menu()
        )
        return

    # DEFAULT
    await bot.send_message(chat_id, "👇 Choose an option", reply_markup=get_menu())


async def app(scope, receive, send):
    if scope["type"] == "http":
        body = b""
        more_body = True

        while more_body:
            message = await receive()
            body += message.get("body", b"")
            more_body = message.get("more_body", False)

        try:
            data = json.loads(body.decode())
            update = Update.de_json(data, bot)
            await handle(update)
        except Exception as e:
            print("ERROR:", e)

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [(b"content-type", b"text/plain")]
        })
        await send({
            "type": "http.response.body",
            "body": b"ok"
        })
