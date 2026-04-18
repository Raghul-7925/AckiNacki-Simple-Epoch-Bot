import json
import time
import os
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from telegram import Bot, Update, ReplyKeyboardMarkup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
KV_URL = os.environ.get("KV_REST_API_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN")

bot = Bot(token=BOT_TOKEN)

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = TOTAL_EPOCHS * EPOCH_SECONDS

# ---------------- KV ----------------

def kv_set(key, value):
    try:
        req = Request(
            f"{KV_URL}/set",
            data=json.dumps({
                "key": key,
                "value": json.dumps(value)
            }).encode(),
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
        val = data.get("result")

        if not val:
            return {}

        return json.loads(val)

    except Exception as e:
        print("KV GET ERROR:", e)
        return {}

# ---------------- MENU ----------------

def menu():
    return ReplyKeyboardMarkup(
        [["▶️ Start Epoch", "📊 Status"], ["🔄 Reset"]],
        resize_keyboard=True
    )

# ---------------- STATUS ----------------

def build(start):
    now = int(time.time())
    elapsed = now - start

    epoch = min((elapsed // EPOCH_SECONDS) + 1, TOTAL_EPOCHS)

    h = elapsed // 3600
    m = (elapsed % 3600) // 60

    return f"⏱️ {h}h {m}m\nEpoch {epoch}/288"

# ---------------- MAIN ----------------

async def handle(update: Update):
    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)

    key = f"{chat}:{user}"
    data = kv_get(key)

    text = (update.message.text or "").lower()

    # START
    if text in ["▶️ start epoch", "/start"]:
        data = {"start_time": int(time.time())}
        kv_set(key, data)

        await bot.send_message(chat, "✅ Saved", reply_markup=menu())

    # STATUS
    elif text == "📊 status":
        if "start_time" not in data:
            await bot.send_message(chat, "❌ Start first", reply_markup=menu())
            return

        msg = build(data["start_time"])
        await bot.send_message(chat, msg, reply_markup=menu())

    # RESET
    elif text == "🔄 reset":
        kv_set(key, {})
        await bot.send_message(chat, "Reset done", reply_markup=menu())

    else:
        await bot.send_message(chat, "Use menu", reply_markup=menu())


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
        await send({"type": "http.response.body", "body": b"ok"})
