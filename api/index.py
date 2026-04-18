import json
import time
import os
from urllib.request import Request, urlopen
from telegram import Bot, Update, ReplyKeyboardMarkup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
KV_URL = os.environ.get("KV_REST_API_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN")

bot = Bot(token=BOT_TOKEN)

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

def menu():
    return ReplyKeyboardMarkup(
        [["▶️ Start Epoch", "📊 Status"], ["🔄 Reset"]],
        resize_keyboard=True
    )

# ---------------- MAIN ----------------

async def handle(update: Update):
    if not update.message:
        return

    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)
    key = f"{chat_id}:{user_id}"

    text = (update.message.text or "").lower()

    # ---------------- START ----------------
    if text in ["▶️ start epoch", "/start"]:
        data = {
            "start_time": int(time.time())
        }

        kv_set(key, data)

        await bot.send_message(
            chat_id,
            "✅ Saved successfully",
            reply_markup=menu()
        )

    # ---------------- STATUS ----------------
    elif text == "📊 status":
        data = kv_get(key)

        print("DEBUG DATA:", data)  # check logs

        if not data or "start_time" not in data:
            await bot.send_message(
                chat_id,
                "❌ Start first",
                reply_markup=menu()
            )
            return

        elapsed = int(time.time()) - data["start_time"]

        h = elapsed // 3600
        m = (elapsed % 3600) // 60

        await bot.send_message(
            chat_id,
            f"⏱️ {h}h {m}m\nData OK ✅",
            reply_markup=menu()
        )

    # ---------------- RESET ----------------
    elif text == "🔄 reset":
        kv_set(key, {})
        await bot.send_message(
            chat_id,
            "🗑️ Reset done",
            reply_markup=menu()
        )

    else:
        await bot.send_message(
            chat_id,
            "👇 Use menu",
            reply_markup=menu()
        )

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
