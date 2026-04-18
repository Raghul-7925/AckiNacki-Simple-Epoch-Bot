import json
import time
import os
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

DATA_FILE = "data.json"

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = TOTAL_EPOCHS * EPOCH_SECONDS


def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


def get_part(epoch):
    if epoch <= 96:
        return "Part 1 (High reward)"
    elif epoch <= 192:
        return "Part 2 (Medium reward)"
    else:
        return "Part 3 (Low reward)"


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.lower()
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    data = load_data()
    now = int(time.time())

    if chat_id not in data:
        data[chat_id] = {}

    if text == "!start":
        data[chat_id][user_id] = {"start_time": now}
        save_data(data)

        start_dt = datetime.fromtimestamp(now)
        reset_dt = datetime.fromtimestamp(now + TOTAL_SECONDS)

        await update.message.reply_text(
            f"🟢 Epoch started\n\n"
            f"🕒 Start: {start_dt.strftime('%d %b %I:%M %p')}\n"
            f"🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')}"
        )

    elif text == "!epoch me":

        if user_id not in data[chat_id]:
            await update.message.reply_text("❌ Use !start first")
            return

        start_time = data[chat_id][user_id]["start_time"]
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

        await update.message.reply_text(
            "📊 Your Epoch Status\n\n"
            f"⏱️ Passed: {h}h {m}m\n"
            f"🔢 Epoch: {epoch}/288\n\n"
            f"📍 {part}\n\n"
            f"⏳ Remaining: {rh}h {rm}m\n"
            f"🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')}"
        )


app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT, message_handler))


async def handler(request):
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)
    return {"statusCode": 200, "body": "ok"}
