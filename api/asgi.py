import base64
import json
import time
import os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from telegram import (
    Bot,
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "data.json")

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))

OWNER_ID = 1837260280

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288
TOTAL_SECONDS = EPOCH_SECONDS * TOTAL_EPOCHS

DAILY_TAP_LIMIT = 12000
TAPS_PER_EPOCH = 70
DAILY_USABLE_EPOCHS = DAILY_TAP_LIMIT // TAPS_PER_EPOCH  # 172
HIGH_REWARD_EPOCHS = 96
LOW_REWARD_EPOCHS = DAILY_USABLE_EPOCHS - HIGH_REWARD_EPOCHS  # 76

GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"


def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "acki-nacki-epoch-bot",
    }


def github_load_store():
    try:
        req = Request(GITHUB_API_URL)
        for k, v in gh_headers().items():
            req.add_header(k, v)

        with urlopen(req, timeout=20) as res:
            body = json.loads(res.read().decode())

        raw = base64.b64decode(body["content"]).decode()
        store = json.loads(raw) if raw.strip() else {}

        if not isinstance(store, dict):
            store = {}

        return store, body.get("sha")

    except HTTPError as e:
        if e.code == 404:
            return {}, None
        print("GITHUB LOAD ERROR:", e)
        return {}, None
    except Exception as e:
        print("GITHUB LOAD ERROR:", e)
        return {}, None


def github_save_store(store, sha):
    payload = {
        "message": "update epoch data",
        "content": base64.b64encode(
            json.dumps(store, indent=2).encode()
        ).decode(),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    def put(body):
        req = Request(
            GITHUB_API_URL,
            data=json.dumps(body).encode(),
            method="PUT",
        )
        for k, v in gh_headers().items():
            req.add_header(k, v)
        req.add_header("Content-Type", "application/json")
        with urlopen(req, timeout=20) as res:
            return json.loads(res.read().decode())

    try:
        return put(payload)
    except HTTPError as e:
        if e.code == 409:
            latest_store, latest_sha = github_load_store()
            if isinstance(latest_store, dict):
                latest_store.update(store)
                payload["content"] = base64.b64encode(
                    json.dumps(latest_store, indent=2).encode()
                ).decode()
                payload["sha"] = latest_sha
                return put(payload)
        print("GITHUB SAVE ERROR:", e)
        return None
    except Exception as e:
        print("GITHUB SAVE ERROR:", e)
        return None


def state_key(chat_id, user_id):
    return f"{chat_id}:{user_id}"


def get_menu():
    return ReplyKeyboardMarkup(
        [
            ["▶️ Start Epoch", "📊 Status"],
            ["🕒 Set Time", "🔄 Reset"],
            ["ℹ️ Help"],
        ],
        resize_keyboard=True,
    )


def hour_keyboard():
    rows = []
    hours = list(range(1, 13))
    for i in range(0, 12, 3):
        rows.append(
            [InlineKeyboardButton(str(h), callback_data=f"h_{h}") for h in hours[i:i + 3]]
        )
    return InlineKeyboardMarkup(rows)


def minute_keyboard():
    mins = list(range(0, 60, 5))
    rows = []
    for i in range(0, 12, 3):
        rows.append(
            [InlineKeyboardButton(f"{m:02}", callback_data=f"m_{m}") for m in mins[i:i + 3]]
        )
    return InlineKeyboardMarkup(rows)


def ampm_keyboard():
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("AM", callback_data="ampm_AM"),
            InlineKeyboardButton("PM", callback_data="ampm_PM"),
        ]]
    )


def get_part(epoch):
    if epoch <= 96:
        return "Part 1 (High reward)"
    elif epoch <= 192:
        return "Part 2 (Medium reward)"
    else:
        return "Part 3 (Low reward)"


def bar(done, total, width=18):
    total = max(int(total), 1)
    done = max(0, min(int(done), total))
    filled = int(round((done / total) * width))
    if filled < 0:
        filled = 0
    if filled > width:
        filled = width
    return "█" * filled + "░" * (width - filled)


def epoch_stats(start_time, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())

    elapsed = max(now_ts - start_time, 0)
    epoch = min((elapsed // EPOCH_SECONDS) + 1, TOTAL_EPOCHS)
    part = get_part(epoch)

    remaining_seconds = max(TOTAL_SECONDS - elapsed, 0)
    remaining_epochs = max(TOTAL_EPOCHS - epoch, 0)

    p1 = datetime.fromtimestamp(start_time, IST)
    p2 = datetime.fromtimestamp(start_time + (96 * EPOCH_SECONDS), IST)
    p3 = datetime.fromtimestamp(start_time + (192 * EPOCH_SECONDS), IST)
    reset_dt = datetime.fromtimestamp(start_time + TOTAL_SECONDS, IST)

    usable_epochs_today = min(epoch, DAILY_USABLE_EPOCHS)
    taps_done = usable_epochs_today * TAPS_PER_EPOCH
    taps_left = max(DAILY_TAP_LIMIT - taps_done, 0)

    high_used = min(usable_epochs_today, HIGH_REWARD_EPOCHS)
    low_used = max(usable_epochs_today - HIGH_REWARD_EPOCHS, 0)

    high_left = max(HIGH_REWARD_EPOCHS - high_used, 0)
    low_left = max(LOW_REWARD_EPOCHS - low_used, 0)

    cycle_h = elapsed // 3600
    cycle_m = (elapsed % 3600) // 60
    left_h = remaining_seconds // 3600
    left_m = (remaining_seconds % 3600) // 60

    return {
        "elapsed": elapsed,
        "epoch": epoch,
        "part": part,
        "cycle_h": cycle_h,
        "cycle_m": cycle_m,
        "left_h": left_h,
        "left_m": left_m,
        "reset_dt": reset_dt,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "usable_epochs_today": usable_epochs_today,
        "taps_done": taps_done,
        "taps_left": taps_left,
        "high_used": high_used,
        "low_used": low_used,
        "high_left": high_left,
        "low_left": low_left,
        "epoch_bar": bar(epoch, TOTAL_EPOCHS),
        "tap_bar": bar(taps_done, DAILY_TAP_LIMIT),
        "daily_epoch_bar": bar(usable_epochs_today, DAILY_USABLE_EPOCHS),
    }


def build_dashboard(start_time, prefix=""):
    info = epoch_stats(start_time)

    text = (
        f"{prefix}"
        f"📊 Live Dashboard\n\n"
        f"⏱️ {info['cycle_h']}h {info['cycle_m']}m\n"
        f"🔢 Epoch: {info['epoch']}/288\n"
        f"📍 {info['part']}\n\n"
        f"🪙 Daily Reward Plan\n"
        f"• Tap limit: 12,000 taps/day\n"
        f"• Usable epochs today: {info['usable_epochs_today']}/172\n"
        f"• 80% reward zone: 1–96 epochs\n"
        f"• 20% reward zone: 97–172 epochs\n"
        f"• 80% zone used: {info['high_used']}/96\n"
        f"• 20% zone used: {info['low_used']}/76\n"
        f"• 80% zone left: {info['high_left']}/96\n"
        f"• 20% zone left: {info['low_left']}/76\n\n"
        f"📈 Progress\n"
        f"Epoch Cycle  : [{info['epoch_bar']}] {info['epoch']}/288\n"
        f"Daily Taps   : [{info['tap_bar']}] {info['taps_done']:,}/12,000\n"
        f"Daily Epochs : [{info['daily_epoch_bar']}] {info['usable_epochs_today']}/172\n\n"
        f"📊 Taps Summary\n"
        f"• Taps done: {info['taps_done']:,}\n"
        f"• Taps left: {info['taps_left']:,}\n\n"
        f"🧭 Phase Timings:\n"
        f"• Part 1: {info['p1'].strftime('%d %b %I:%M %p')} IST\n"
        f"• Part 2: {info['p2'].strftime('%d %b %I:%M %p')} IST\n"
        f"• Part 3: {info['p3'].strftime('%d %b %I:%M %p')} IST\n\n"
        f"⏳ Left: {info['left_h']}h {info['left_m']}m\n"
        f"🔁 Reset: {info['reset_dt'].strftime('%d %b %I:%M %p')} IST"
    )
    return text, info


async def render_dashboard(chat_id, state, prefix=""):
    text, info = build_dashboard(state["start_time"], prefix=prefix)

    # Try to update the existing dashboard first
    if state.get("msg_id"):
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=state["msg_id"],
                text=text,
            )
            return info
        except Exception:
            pass

    # If no previous message or edit failed, create one and pin it in groups
    msg = await bot.send_message(chat_id, text, reply_markup=get_menu())
    state["msg_id"] = msg.message_id

    try:
        chat = await bot.get_chat(chat_id)
        if chat.type != "private":
            await bot.pin_chat_message(
                chat_id=chat_id,
                message_id=msg.message_id,
                disable_notification=True
            )
    except Exception:
        pass

    return info


async def handle(update: Update):
    chat = update.effective_chat
    user = update.effective_user

    if not chat or not user:
        return

    # DM: everyone can use. Group/supergroup: only you.
    if chat.type != "private" and int(user.id) != OWNER_ID:
        return

    chat_id = str(chat.id)
    user_id = str(user.id)
    k = state_key(chat_id, user_id)

    store, sha = github_load_store()
    state = store.get(k, {})
    if not isinstance(state, dict):
        state = {}

    # CALLBACK FLOW (Set Time)
    if update.callback_query:
        q = update.callback_query
        await q.answer()

        data = q.data

        pending = state.get("pending", {})
        if not isinstance(pending, dict):
            pending = {}

        if data.startswith("h_"):
            if pending.get("step") != "hour":
                await q.edit_message_text("❌ Use 🕒 Set Time again.")
                return

            pending["hour"] = int(data.split("_")[1])
            pending["step"] = "minute"
            state["pending"] = pending
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
        })
