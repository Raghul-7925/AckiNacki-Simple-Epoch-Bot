import json
import time
import os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen

from telegram import (
    Bot,
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

# ---------------- CONFIG ----------------

BOT_TOKEN = os.environ.get("BOT_TOKEN")
KV_URL = os.environ.get("KV_REST_API_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN")

bot = Bot(token=BOT_TOKEN)

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = EPOCH_SECONDS * TOTAL_EPOCHS

TEMP = {}

# ---------------- KV (FINAL CORRECT) ----------------

def kv_set(key, value):
    try:
        req = Request(
            f"{KV_URL}/set/{key}",
            data=json.dumps(value).encode(),
            method="POST"
        )
        req.add_header("Authorization", f"Bearer {KV_TOKEN}")
        req.add_header("Content-Type", "application/json")
        urlopen(req)
    except Exception as e:
        print("KV SET ERROR:", e)


def kv_get(key):
    try:
        req = Request(f"{KV_URL}/get/{key}")
        req.add_header("Authorization", f"Bearer {KV_TOKEN}")
        res = urlopen(req).read()

        data = json.loads(res)

        if "result" not in data:
            return {}

        val = data["result"]

        if val is None:
            return {}

        return val

    except Exception as e:
        print("KV GET ERROR:", e)
        return {}

# ---------------- MENU ----------------

def get_menu():
    return ReplyKeyboardMarkup(
        [
            ["▶️ Start Epoch", "📊 Status"],
            ["🕒 Set Time", "🔄 Reset"],
            ["ℹ️ Help"]
        ],
        resize_keyboard=True
    )

# ---------------- PART ----------------

def get_part(epoch):
    if epoch <= 96:
        return "Part 1 (High reward)"
    elif epoch <= 192:
        return "Part 2 (Medium reward)"
    else:
        return "Part 3 (Low reward)"

# ---------------- STATUS ----------------

def build_status(start_time):
    now = int(time.time())
    elapsed = now - start_time

    epoch = int(elapsed // EPOCH_SECONDS) + 1
    if epoch > TOTAL_EPOCHS:
        epoch = TOTAL_EPOCHS

    part = get_part(epoch)

    h = elapsed // 3600
    m = (elapsed % 3600) // 60

    remaining = max(TOTAL_SECONDS - elapsed, 0)
    rh = remaining // 3600
    rm = (remaining % 3600) // 60

    # Part timings
    p1 = start_time
    p2 = start_time + (96 * EPOCH_SECONDS)
    p3 = start_time + (192 * EPOCH_SECONDS)

    def to_ist(ts):
        return (datetime.utcfromtimestamp(ts) + timedelta(hours=5, minutes=30)).strftime('%I:%M %p')

    reset_dt = datetime.utcfromtimestamp(start_time + TOTAL_SECONDS) + timedelta(hours=5, minutes=30)

    return (
        f"📊 Live Dashboard\n\n"
        f"⏱️ {h}h {m}m\n"
        f"🔢 Epoch: {epoch}/288\n"
        f"📍 {part}\n\n"
        f"🧭 Phase Timings:\n"
        f"• Part 1: {to_ist(p1)}\n"
        f"• Part 2: {to_ist(p2)}\n"
        f"• Part 3: {to_ist(p3)}\n\n"
        f"⏳ Left: {rh}h {rm}m\n"
        f"🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')} IST"
    ), epoch

# ---------------- TIME PICKER ----------------

def hour_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(str(i), callback_data=f"h_{i}") for i in range(j, j+3)]
        for j in range(1, 13, 3)
    ])

def minute_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{i:02}", callback_data=f"m_{i}") for i in range(j, j+15, 5)]
        for j in range(0, 60, 15)
    ])

def ampm_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("AM", callback_data="ampm_AM"),
            InlineKeyboardButton("PM", callback_data="ampm_PM")
        ]
    ])

# ---------------- MAIN ----------------

async def handle(update: Update):
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    key = f"{chat_id}:{user_id}"

    user = kv_get(key)

    # ---------- CALLBACK ----------
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        data = q.data

        if user_id not in TEMP:
            TEMP[user_id] = {}

        if data.startswith("h_"):
            TEMP[user_id]["h"] = int(data.split("_")[1])
            await bot.send_message(chat_id, "Select Minute:", reply_markup=minute_keyboard())

        elif data.startswith("m_"):
            TEMP[user_id]["m"] = int(data.split("_")[1])
            await bot.send_message(chat_id, "Select AM/PM:", reply_markup=ampm_keyboard())

        elif data.startswith("ampm_"):
            h = TEMP[user_id]["h"]
            m = TEMP[user_id]["m"]
            ampm = data.split("_")[1]

            if ampm == "PM" and h != 12:
                h += 12
            if ampm == "AM" and h == 12:
                h = 0

            now_utc = datetime.utcnow()
            ist = now_utc + timedelta(hours=5, minutes=30)
            ist = ist.replace(hour=h, minute=m, second=0)
            utc = ist - timedelta(hours=5, minutes=30)

            user["start_time"] = int(utc.timestamp())
            user["msg_id"] = None
            user["last_epoch"] = 0

            kv_set(key, user)

            await bot.send_message(chat_id, f"✅ Epoch set to {ist.strftime('%I:%M %p')} IST", reply_markup=get_menu())

        return

    # ---------- TEXT ----------
    if not update.message:
        return

    text = (update.message.text or "").lower()

    # START
    if text in ["▶️ start epoch", "/start"]:
        user = {
            "start_time": int(time.time()),
            "msg_id": None,
            "last_epoch": 0
        }
        kv_set(key, user)

        await bot.send_message(chat_id, "🟢 Epoch started", reply_markup=get_menu())

    # STATUS
    elif text == "📊 status":
        if not user or "start_time" not in user:
            await bot.send_message(chat_id, "❌ Start first", reply_markup=get_menu())
            return

        msg, epoch = build_status(user["start_time"])

        if not user.get("msg_id"):
            m = await bot.send_message(chat_id, msg, reply_markup=get_menu())
            user["msg_id"] = m.message_id
        else:
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=user["msg_id"],
                    text=msg,
                    reply_markup=get_menu()
                )
            except:
                m = await bot.send_message(chat_id, msg, reply_markup=get_menu())
                user["msg_id"] = m.message_id

        # alerts
        if epoch != user.get("last_epoch", 0):
            if epoch == 97:
                await bot.send_message(chat_id, "🚀 Part 2 Started")
            elif epoch == 193:
                await bot.send_message(chat_id, "⚠️ Part 3 Started")

            user["last_epoch"] = epoch

        kv_set(key, user)

    # SET TIME
    elif text == "🕒 set time":
        TEMP[user_id] = {}
        await bot.send_message(chat_id, "Select Hour:", reply_markup=hour_keyboard())

    # RESET
    elif text == "🔄 reset":
        kv_set(key, {})
        await bot.send_message(chat_id, "🗑️ Data cleared", reply_markup=get_menu())

    # HELP
    elif text == "ℹ️ help":
        await bot.send_message(chat_id, "Use buttons below", reply_markup=get_menu())

    else:
        await bot.send_message(chat_id, "👇 Choose option", reply_markup=get_menu())

# ---------------- ENTRY ----------------

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
