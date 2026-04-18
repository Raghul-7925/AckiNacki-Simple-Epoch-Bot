import time
import os
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = TOTAL_EPOCHS * EPOCH_SECONDS

# In-memory store (Vercel-safe)
DATA = {}


def get_part(epoch):
    if epoch <= 96:
        return "Part 1 (High reward)"
    elif epoch <= 192:
        return "Part 2 (Medium reward)"
    else:
        return "Part 3 (Low reward)"


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").lower()
    chat_id = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    now = int(time.time())

    if chat_id not in DATA:
        DATA[chat_id] = {}

    # ---------- START ----------
    if text == "!start":
        DATA[chat_id][user_id] = {"start_time": now}

        start_dt = datetime.fromtimestamp(now)
        reset_dt = datetime.fromtimestamp(now + TOTAL_SECONDS)

        await update.message.reply_text(
            f"🟢 Epoch started\n\n"
            f"🕒 Start: {start_dt.strftime('%d %b %I:%M %p')}\n"
            f"🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')}"
        )

    # ---------- STATUS ----------
    elif text == "!epoch me":

        if user_id not in DATA[chat_id]:
            await update.message.reply_text("❌ Use !start first")
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


# Webhook entry
async def handler(request):
    try:
        data = await request.json()
        update = Update.de_json(data, app.bot)
        await app.process_update(update)
        return {"statusCode": 200, "body": "ok"}
    except Exception as e:
        return {"statusCode": 200, "body": str(e)}
