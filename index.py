import json
import time
import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

DATA_FILE = "data.json"

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = TOTAL_EPOCHS * EPOCH_SECONDS


# ---------- STORAGE ----------

def load_data():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


# ---------- BUTTON MENU ----------

def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔘 New Epoch", callback_data="start")],
        [InlineKeyboardButton("📊 Check Status", callback_data="status")]
    ])


# ---------- START ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⏱️ Epoch Helper Bot\n\n"
        "Use the buttons below:",
        reply_markup=main_menu()
    )


# ---------- BUTTON HANDLER ----------

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = str(query.from_user.id)
    data = load_data()

    now = int(time.time())

    # ---------- NEW EPOCH ----------
    if query.data == "start":
        data[user_id] = {
            "start_time": now
        }
        save_data(data)

        start_dt = datetime.fromtimestamp(now)
        reset_dt = datetime.fromtimestamp(now + TOTAL_SECONDS)

        msg = (
            "🟢 New Epoch Started\n\n"
            f"🕒 Start Time: {start_dt.strftime('%d %b %I:%M %p')}\n"
            f"🔁 Reset Time: {reset_dt.strftime('%d %b %I:%M %p')}"
        )

        await query.edit_message_text(msg, reply_markup=main_menu())


    # ---------- CHECK STATUS ----------
    elif query.data == "status":

        if user_id not in data:
            await query.edit_message_text(
                "❌ Start first using 'New Epoch'",
                reply_markup=main_menu()
            )
            return

        start_time = data[user_id]["start_time"]

        elapsed = now - start_time

        # epoch
        epoch = int(elapsed // EPOCH_SECONDS) + 1
        if epoch > TOTAL_EPOCHS:
            epoch = TOTAL_EPOCHS

        # part
        if epoch <= 96:
            part = "Part 1 (High reward)"
        elif epoch <= 192:
            part = "Part 2 (Medium reward)"
        else:
            part = "Part 3 (Low reward)"

        # time passed
        h = elapsed // 3600
        m = (elapsed % 3600) // 60

        # remaining
        remaining = TOTAL_SECONDS - elapsed
        if remaining < 0:
            remaining = 0

        rh = remaining // 3600
        rm = (remaining % 3600) // 60

        # reset time
        reset_time = start_time + TOTAL_SECONDS
        reset_dt = datetime.fromtimestamp(reset_time)

        msg = (
            "📊 Epoch Status\n\n"
            f"⏱️ Time Passed: {h}h {m}m\n"
            f"🔢 Epoch: {epoch} / {TOTAL_EPOCHS}\n\n"
            f"📍 {part}\n\n"
            f"⏳ Remaining: {rh}h {rm}m\n"
            f"🔁 Reset: {reset_dt.strftime('%d %b %I:%M %p')}"
        )

        await query.edit_message_text(msg, reply_markup=main_menu())


# ---------- VERCEL HANDLER ----------

app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CallbackQueryHandler(button))


async def handler(request):
    data = await request.json()
    update = Update.de_json(data, app.bot)
    await app.process_update(update)

    return {
        "statusCode": 200,
        "body": "ok"
      }
