import json
import time
import os
from datetime import datetime, timedelta
from telegram import (
    Bot,
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = TOTAL_EPOCHS * EPOCH_SECONDS

DATA = {}
TEMP = {}

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

# ---------------- KEYBOARDS ----------------

def hour_keyboard():
    rows = []
    for i in range(1, 13, 3):
        rows.append([
            InlineKeyboardButton(str(i), callback_data=f"h_{i}"),
            InlineKeyboardButton(str(i+1), callback_data=f"h_{i+1}"),
            InlineKeyboardButton(str(i+2), callback_data=f"h_{i+2}")
        ])
    return InlineKeyboardMarkup(rows)

def minute_keyboard():
    rows = []
    for i in range(0, 60, 15):
        rows.append([
            InlineKeyboardButton(f"{i:02}", callback_data=f"m_{i}"),
            InlineKeyboardButton(f"{i+5:02}", callback_data=f"m_{i+5}"),
            InlineKeyboardButton(f"{i+10:02}", callback_data=f"m_{i+10}")
        ])
    return InlineKeyboardMarkup(rows)

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
    now = int(time.time())

    if chat_id not in DATA:
        DATA[chat_id] = {}

    # ---------- CALLBACK (TIME SET FLOW) ----------
    if update.callback_query:
        query = update.callback_query
        await query.answer()

        data_cb = query.data

        if user_id not in TEMP:
            TEMP[user_id] = {}

        # Hour
        if data_cb.startswith("h_"):
            TEMP[user_id]["hour"] = int(data_cb.split("_")[1])
            await bot.send_message(chat_id, "Select Minute:", reply_markup=minute_keyboard())

        # Minute
        elif data_cb.startswith("m_"):
            TEMP[user_id]["minute"] = int(data_cb.split("_")[1])
            await bot.send_message(chat_id, "Select AM/PM:", reply_markup=ampm_keyboard())

        # AM/PM FINAL
        elif data_cb.startswith("ampm_"):
            ampm = data_cb.split("_")[1]
            h = TEMP[user_id]["hour"]
            m = TEMP[user_id]["minute"]

            # convert 12h → 24h
            if ampm == "PM" and h != 12:
                h += 12
            if ampm == "AM" and h == 12:
                h = 0

            # current UTC date
            now_utc = datetime.utcnow()

            # create IST datetime → convert to UTC
            ist_time = now_utc + timedelta(hours=5, minutes=30)
            ist_time = ist_time.replace(hour=h, minute=m, second=0)

            # convert IST → UTC
            utc_time = ist_time - timedelta(hours=5, minutes=30)

            timestamp = int(utc_time.timestamp())

            DATA[chat_id][user_id] = {"start_time": timestamp}

            await bot.send_message(
                chat_id,
                f"✅ Epoch manually set\n🕒 {ist_time.strftime('%I:%M %p')} IST",
                reply_markup=get_menu()
            )

        return

    # ---------- TEXT ----------
    if not update.message:
        return

    text = (update.message.text or "").lower()

    # START
    if text in ["▶️ start epoch", "/start"]:
        DATA[chat_id][user_id] = {"start_time": now}

        start_dt = datetime.utcfromtimestamp(now) + timedelta(hours=5, minutes=30)
        reset_dt = start_dt + timedelta(seconds=TOTAL_SECONDS)

        await bot.send_message(
            chat_id,
            f"🟢 Epoch started\n\n🕒 Start: {start_dt.strftime('%d %b %I:%M %p')} IST\n🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')} IST",
            reply_markup=get_menu()
        )

    # STATUS
    elif text == "📊 status":
        if user_id not in DATA[chat_id]:
            await bot.send_message(chat_id, "❌ Start first", reply_markup=get_menu())
            return

        start_time = DATA[chat_id][user_id]["start_time"]
        elapsed = now - start_time

        epoch = int(elapsed // EPOCH_SECONDS) + 1
        if epoch > TOTAL_EPOCHS:
            epoch = TOTAL_EPOCHS

        part = get_part(epoch)

        h = elapsed // 3600
        m = (elapsed % 3600) // 60

        remaining = TOTAL_SECONDS - elapsed
        if remaining < 0:
            remaining = 0

        rh = remaining // 3600
        rm = (remaining % 3600) // 60

        reset_dt = datetime.utcfromtimestamp(start_time + TOTAL_SECONDS) + timedelta(hours=5, minutes=30)

        await bot.send_message(
            chat_id,
            f"📊 Status\n\n⏱️ {h}h {m}m\n🔢 Epoch: {epoch}/288\n📍 {part}\n\n⏳ Left: {rh}h {rm}m\n🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')} IST",
            reply_markup=get_menu()
        )

    # SET TIME
    elif text == "🕒 set time":
        TEMP[user_id] = {}
        await bot.send_message(chat_id, "Select Hour (IST):", reply_markup=hour_keyboard())

    # RESET
    elif text == "🔄 reset":
        if user_id in DATA.get(chat_id, {}):
            del DATA[chat_id][user_id]

        await bot.send_message(chat_id, "🗑️ Data deleted", reply_markup=get_menu())

    # HELP
    elif text == "ℹ️ help":
        await bot.send_message(
            chat_id,
            "📘 Use:\n▶️ Start Epoch\n📊 Status\n🕒 Set Time\n🔄 Reset\n\nEach epoch = 5m30s\n288 epochs total",
            reply_markup=get_menu()
        )

    else:
        await bot.send_message(chat_id, "👇 Choose option", reply_markup=get_menu())


# ---------------- VERCEL ENTRY ----------------

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
