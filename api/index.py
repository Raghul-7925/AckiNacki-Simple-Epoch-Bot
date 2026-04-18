import json
import time
import os
from datetime import datetime
from telegram import Bot, Update

BOT_TOKEN = os.environ.get("BOT_TOKEN")
bot = Bot(token=BOT_TOKEN)

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = TOTAL_EPOCHS * EPOCH_SECONDS

DATA = {}


def get_part(epoch):
    if epoch <= 96:
        return "Part 1 (High reward)"
    elif epoch <= 192:
        return "Part 2 (Medium reward)"
    else:
        return "Part 3 (Low reward)"


async def handle_message(update: Update):
    if not update.message:
        return

    text = (update.message.text or "").lower()
    chat_id = str(update.message.chat.id)
    user_id = str(update.message.from_user.id)

    now = int(time.time())

    if chat_id not in DATA:
        DATA[chat_id] = {}

    # START
    if text == "!start":
        DATA[chat_id][user_id] = {"start_time": now}

        start_dt = datetime.fromtimestamp(now)
        reset_dt = datetime.fromtimestamp(now + TOTAL_SECONDS)

        await bot.send_message(
            chat_id=chat_id,
            text=(
                f"🟢 Epoch started\n\n"
                f"🕒 Start: {start_dt.strftime('%d %b %I:%M %p')}\n"
                f"🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')}"
            )
        )

    # STATUS
    elif text == "!epoch me":

        if user_id not in DATA[chat_id]:
            await bot.send_message(chat_id=chat_id, text="❌ Use !start first")
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

        reset_dt = datetime.fromtimestamp(start_time + TOTAL_SECONDS)

        await bot.send_message(
            chat_id=chat_id,
            text=(
                "📊 Your Epoch Status\n\n"
                f"⏱️ Passed: {h}h {m}m\n"
                f"🔢 Epoch: {epoch}/288\n\n"
                f"📍 {part}\n\n"
                f"⏳ Remaining: {rh}h {rm}m\n"
                f"🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')}"
            )
        )


# 🔥 Vercel ASGI entrypoint
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
            await handle_message(update)
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
