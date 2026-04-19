import base64
import json
import time
import os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from telegram import Bot, Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

# ---------------- WSGI FIX (DO NOT REMOVE) ----------------
def app(environ, start_response):
    start_response('200 OK', [('Content-Type', 'text/plain')])
    return [b'OK']

# ---------------- CONFIG ----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "data.json")

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = EPOCH_SECONDS * TOTAL_EPOCHS

DAILY_TAPS = 12000
TAPS_PER_EPOCH = 70
MAX_EPOCHS_DAILY = DAILY_TAPS // TAPS_PER_EPOCH  # 172

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

# ---------------- GITHUB ----------------
def headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

def load_data():
    try:
        req = Request(GITHUB_API)
        for k,v in headers().items():
            req.add_header(k,v)
        res = urlopen(req).read()
        d = json.loads(res)
        content = base64.b64decode(d["content"]).decode()
        return json.loads(content), d["sha"]
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
    for k,v in headers().items():
        req.add_header(k,v)
    req.add_header("Content-Type", "application/json")
    urlopen(req)

# ---------------- UI ----------------
def menu():
    return ReplyKeyboardMarkup(
        [["▶️ Start Epoch","📊 Status"],["🔄 Reset"]],
        resize_keyboard=True
    )

def bar(v, t, w=15):
    f = int((v/t)*w) if t else 0
    return "█"*f + "░"*(w-f)

# ---------------- CORE ----------------
def build(start):
    now = int(time.time())
    elapsed = now - start

    epoch = min((elapsed//EPOCH_SECONDS)+1, TOTAL_EPOCHS)

    taps_done = min(epoch, MAX_EPOCHS_DAILY) * TAPS_PER_EPOCH
    taps_left = max(DAILY_TAPS - taps_done, 0)

    high = min(epoch,96)
    low = max(epoch-96,0)

    h = elapsed//3600
    m = (elapsed%3600)//60

    text = (
        f"📊 Live Dashboard\n\n"
        f"⏱️ {h}h {m}m\n"
        f"🔢 Epoch: {epoch}/288\n\n"
        f"🪙 Daily Plan\n"
        f"80% zone: {high}/96\n"
        f"20% zone: {low}/76\n\n"
        f"📈 Progress\n"
        f"Epoch : [{bar(epoch,288)}] {epoch}/288\n"
        f"Taps  : [{bar(taps_done,12000)}] {taps_done}/12000\n\n"
        f"📊 Taps\n"
        f"Done: {taps_done}\n"
        f"Left: {taps_left}"
    )

    return text, epoch

# ---------------- DASHBOARD ----------------
async def dashboard(chat, state):
    text, epoch = build(state["start_time"])

    if state.get("msg_id"):
        try:
            await bot.edit_message_text(chat, state["msg_id"], text)
            return epoch
        except:
            pass

    msg = await bot.send_message(chat, text, reply_markup=menu())
    state["msg_id"] = msg.message_id

    try:
        c = await bot.get_chat(chat)
        if c.type != "private":
            await bot.pin_chat_message(chat, msg.message_id, disable_notification=True)
    except:
        pass

    return epoch

# ---------------- HANDLER ----------------
async def handle(update: Update):
    if not update.message:
        return

    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)
    key = f"{chat}:{user}"

    store, sha = load_data()
    state = store.get(key, {})

    text = (update.message.text or "").lower()

    if text in ["▶️ start epoch","/start"]:
        state = {"start_time": int(time.time()), "msg_id": None}
        store[key] = state
        save_data(store, sha)
        await bot.send_message(chat,"Started",reply_markup=menu())

    elif text == "📊 status":
        if "start_time" not in state:
            await bot.send_message(chat,"Start first",reply_markup=menu())
            return

        await dashboard(chat,state)
        store[key] = state
        save_data(store, sha)

    elif text == "🔄 reset":
        if key in store:
            del store[key]
            save_data(store, sha)
        await bot.send_message(chat,"Cleared",reply_markup=menu())

# ---------------- ENTRY ----------------
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
        await send({"type":"http.response.body","body":b"ok"}) = pending
            store[k] = state
            github_save_store(store, sha)

            await q.edit_message_text("Select Minute (IST):", reply_markup=minute_keyboard())
            return

        if data.startswith("m_"):
            if pending.get("step") != "minute" or "hour" not in pending:
                await q.edit_message_text("❌ Use 🕒 Set Time again.")
                return

            pending["minute"] = int(data.split("_")[1])
            pending["step"] = "ampm"
            state["pending"] = pending
            store[k] = state
            github_save_store(store, sha)

            await q.edit_message_text("Select AM/PM:", reply_markup=ampm_keyboard())
            return

        if data.startswith("ampm_"):
            if pending.get("step") != "ampm" or "hour" not in pending or "minute" not in pending:
                await q.edit_message_text("❌ Use 🕒 Set Time again.")
                return

            hour = int(pending["hour"])
            minute = int(pending["minute"])
            ampm = data.split("_")[1]

            if ampm == "PM" and hour != 12:
                hour += 12
            if ampm == "AM" and hour == 12:
                hour = 0

            now_ist = datetime.now(IST)
            chosen_ist = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If the selected time is ahead of now, use the previous day
            if chosen_ist > now_ist:
                chosen_ist -= timedelta(days=1)

            start_ts = int(chosen_ist.timestamp())

            state["start_time"] = start_ts
            state["pending"] = {}
            store[k] = state
            github_save_store(store, sha)

            await q.edit_message_text(
                f"✅ Epoch set to {chosen_ist.strftime('%d %b %I:%M %p')} IST"
            )

            await render_dashboard(
                chat_id,
                state,
                prefix=f"✅ Epoch manually set to {chosen_ist.strftime('%I:%M %p')} IST\n\n"
            )
            store[k] = state
            github_save_store(store, sha)
            return

        return

    # TEXT COMMANDS / BUTTONS
    if not update.message:
        return

    text = (update.message.text or "").strip().lower()

    # START NOW
    if text in ["▶️ start epoch", "/start"]:
        now_ts = int(time.time())
        state["start_time"] = now_ts
        state["pending"] = {}
        store[k] = state
        github_save_store(store, sha)

        await render_dashboard(chat_id, state, prefix="🟢 Epoch started\n\n")
        store[k] = state
        github_save_store(store, sha)
        return

    # STATUS
    if text == "📊 status":
        if "start_time" not in state:
            await bot.send_message(chat_id, "❌ Start first", reply_markup=get_menu())
            return

        await render_dashboard(chat_id, state)
        store[k] = state
        github_save_store(store, sha)
        return

    # MANUAL SET TIME
    if text == "🕒 set time":
        state["pending"] = {"step": "hour"}
        store[k] = state
        github_save_store(store, sha)

        await bot.send_message(
            chat_id,
            "Select Hour (IST):",
            reply_markup=hour_keyboard()
        )
        return

    # RESET
    if text == "🔄 reset":
        # Try removing the dashboard message so the chat stays clean
        if state.get("msg_id"):
            try:
                await bot.delete_message(chat_id=chat_id, message_id=state["msg_id"])
            except Exception:
                try:
                    await bot.unpin_chat_message(chat_id=chat_id)
                except Exception:
                    pass

        if k in store:
            del store[k]
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
            "1️⃣ ▶️ Start Epoch — start from now.\n"
            "2️⃣ 🕒 Set Time — manually set IST time.\n"
            "3️⃣ 📊 Status — updates the same pinned dashboard.\n"
            "4️⃣ 🔄 Reset — deletes your saved data.\n\n"
            "⏱️ Each epoch = 5 minutes 30 seconds\n"
            "🔢 Total = 288 epochs\n"
            "🪙 Daily tap limit = 12,000 taps\n"
            "📌 First 96 epochs = 80% reward zone\n"
            "📌 Next 76 epochs = 20% reward zone",
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
        })w to use this bot:\n\n"
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
