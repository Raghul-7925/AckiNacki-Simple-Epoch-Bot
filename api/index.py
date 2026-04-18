import base64
import json
import time
import os
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from telegram import Bot, Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

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


def epoch_info(start_time, now_ts=None):
    if now_ts is None:
        now_ts = int(time.time())

    elapsed = max(now_ts - start_time, 0)
    epoch = min((elapsed // EPOCH_SECONDS) + 1, TOTAL_EPOCHS)

    remaining_seconds = max(TOTAL_SECONDS - elapsed, 0)
    remaining_epochs = max(TOTAL_EPOCHS - epoch, 0)

    part = get_part(epoch)

    p1 = datetime.fromtimestamp(start_time, IST)
    p2 = datetime.fromtimestamp(start_time + (96 * EPOCH_SECONDS), IST)
    p3 = datetime.fromtimestamp(start_time + (192 * EPOCH_SECONDS), IST)
    reset_dt = datetime.fromtimestamp(start_time + TOTAL_SECONDS, IST)

    return {
        "elapsed": elapsed,
        "epoch": epoch,
        "remaining_seconds": remaining_seconds,
        "remaining_epochs": remaining_epochs,
        "part": part,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "reset_dt": reset_dt,
    }


def build_dashboard(start_time, prefix=""):
    info = epoch_info(start_time)
    h = info["elapsed"] // 3600
    m = (info["elapsed"] % 3600) // 60

    rh = info["remaining_seconds"] // 3600
    rm = (info["remaining_seconds"] % 3600) // 60

    text = (
        f"{prefix}"
        f"📊 Live Dashboard\n\n"
        f"⏱️ {h}h {m}m\n"
        f"🔢 Epoch: {info['epoch']}/288\n"
        f"📍 {info['part']}\n\n"
        f"🧭 Phase Timings:\n"
        f"• Part 1: {info['p1'].strftime('%d %b %I:%M %p')} IST\n"
        f"• Part 2: {info['p2'].strftime('%d %b %I:%M %p')} IST\n"
        f"• Part 3: {info['p3'].strftime('%d %b %I:%M %p')} IST\n\n"
        f"⏳ Left: {rh}h {rm}m\n"
        f"🔁 Reset: {info['reset_dt'].strftime('%d %b %I:%M %p')} IST"
    )
    return text, info


async def send_or_edit_dashboard(chat_id, state, prefix=""):
    text, info = build_dashboard(state["start_time"], prefix=prefix)

    if state.get("msg_id"):
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=state["msg_id"],
                text=text,
            )
        except Exception:
            msg = await bot.send_message(chat_id, text, reply_markup=get_menu())
            state["msg_id"] = msg.message_id
    else:
        msg = await bot.send_message(chat_id, text, reply_markup=get_menu())
        state["msg_id"] = msg.message_id

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
    key = state_key(chat_id, user_id)

    store, sha = github_load_store()
    state = store.get(key, {})
    if not isinstance(state, dict):
        state = {}

    # ----- CALLBACKS -----
    if update.callback_query:
        q = update.callback_query
        await q.answer()

        data = q.data
        pending = state.get("pending", {})
        if not isinstance(pending, dict):
            pending = {}

        if data.startswith("h_"):
            if pending.get("step") != "hour":
                await bot.send_message(chat_id, "❌ Use 🕒 Set Time again.", reply_markup=get_menu())
                return

            pending["hour"] = int(data.split("_")[1])
            pending["step"] = "minute"
            state["pending"] = pending
            store[key] = state
            github_save_store(store, sha)

            await bot.send_message(chat_id, "Select Minute:", reply_markup=minute_keyboard())
            return

        if data.startswith("m_"):
            if pending.get("step") != "minute" or "hour" not in pending:
                await bot.send_message(chat_id, "❌ Use 🕒 Set Time again.", reply_markup=get_menu())
                return

            pending["minute"] = int(data.split("_")[1])
            pending["step"] = "ampm"
            state["pending"] = pending
            store[key] = state
            github_save_store(store, sha)

            await bot.send_message(chat_id, "Select AM/PM:", reply_markup=ampm_keyboard())
            return

        if data.startswith("ampm_"):
            if pending.get("step") != "ampm" or "hour" not in pending or "minute" not in pending:
                await bot.send_message(chat_id, "❌ Use 🕒 Set Time again.", reply_markup=get_menu())
                return

            hour = int(pending["hour"])
            minute = int(pending["minute"])
            ampm = data.split("_")[1]

            if ampm == "PM" and hour != 12:
                hour += 12
            if ampm == "AM" and hour == 12:
                hour = 0

            now_ist = datetime.now(IST)
            custom_ist = now_ist.replace(hour=hour, minute=minute, second=0, microsecond=0)

            # If the chosen time is ahead of now, assume the last occurrence
            if custom_ist > now_ist:
                custom_ist -= timedelta(days=1)

            start_ts = int(custom_ist.timestamp())
            info = epoch_info(start_ts)

            state["start_time"] = start_ts
            state["last_epoch"] = info["epoch"]
            state["pending"] = {}
            state["msg_id"] = None

            store[key] = state
            await send_or_edit_dashboard(
                chat_id,
                state,
                prefix=f"✅ Epoch set to {custom_ist.strftime('%d %b %I:%M %p')} IST\n\n"
            )
            store[key] = state
            github_save_store(store, sha)
            return

        return

    # ----- TEXT -----
    if not update.message:
        return

    text = (update.message.text or "").strip().lower()

    # START
    if text in ["▶️ start epoch", "/start"]:
        now_ts = int(time.time())
        info = epoch_info(now_ts)

        state["start_time"] = now_ts
        state["last_epoch"] = info["epoch"]
        state["pending"] = {}
        state["msg_id"] = None

        store[key] = state
        await send_or_edit_dashboard(
            chat_id,
            state,
            prefix="🟢 Epoch started\n\n"
        )
        store[key] = state
        github_save_store(store, sha)
        return

    # STATUS
    if text == "📊 status":
        if "start_time" not in state:
            await bot.send_message(chat_id, "❌ Start first", reply_markup=get_menu())
            return

        info = epoch_info(state["start_time"])

        store[key] = state
        await send_or_edit_dashboard(chat_id, state, prefix="")

        # alerts on part change
        previous_epoch = int(state.get("last_epoch", 0) or 0)
        current_epoch = int(info["epoch"])

        if current_epoch != previous_epoch:
            if current_epoch == 97:
                await bot.send_message(chat_id, "🚀 Part 2 Started")
            elif current_epoch == 193:
                await bot.send_message(chat_id, "⚠️ Part 3 Started")

            state["last_epoch"] = current_epoch

        store[key] = state
        github_save_store(store, sha)
        return

    # SET TIME
    if text == "🕒 set time":
        state["pending"] = {"step": "hour"}
        store[key] = state
        github_save_store(store, sha)

        await bot.send_message(chat_id, "Select Hour (IST):", reply_markup=hour_keyboard())
        return

    # RESET
    if text == "🔄 reset":
        if key in store:
            del store[key]
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
