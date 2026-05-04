import base64
import json
import time
import os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from telegram import Bot, Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "data.json")

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))

EPOCH_SECONDS = 330
TOTAL_EPOCHS = 288

DAILY_TAP_LIMIT = 12000
TAPS_PER_EPOCH = 70
DAILY_USABLE_EPOCHS = DAILY_TAP_LIMIT // TAPS_PER_EPOCH

BLOCKS_PER_EPOCH = 262000


# ---------------- GITHUB ----------------
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

def load_data():
    try:
        req = Request(GITHUB_API)
        for k, v in gh_headers().items():
            req.add_header(k, v)
        res = urlopen(req).read()
        data = json.loads(res)
        content = base64.b64decode(data["content"]).decode()
        return json.loads(content), data["sha"]
    except:
        return {}, None

def save_data(store, sha):
    body = {
        "message": "update",
        "content": base64.b64encode(json.dumps(store).encode()).decode(),
        "branch": "main"
    }
    if sha:
        body["sha"] = sha

    req = Request(GITHUB_API, data=json.dumps(body).encode(), method="PUT")
    for k, v in gh_headers().items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    urlopen(req)


# ---------------- BLOCK FETCH ----------------
def get_block_height():
    url = "https://mainnet.ackinacki.org/graphql"

    payload = json.dumps({
        "query": """
        query GetBlocks($limit: Int!) {
          blockchain {
            blocks(last: $limit) {
              nodes {
                seq_no
              }
            }
          }
        }
        """,
        "variables": {"limit": 1}
    }).encode()

    req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")

    with urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode())

    return data["data"]["blockchain"]["blocks"]["nodes"][0]["seq_no"]


def block_epoch(state):
    try:
        if "start_block" not in state:
            return None

        current_block = get_block_height()
        start_block = state["start_block"]

        passed = current_block - start_block

        epoch = (passed // BLOCKS_PER_EPOCH) + 1
        epoch = max(1, min(epoch, TOTAL_EPOCHS))

        remaining = BLOCKS_PER_EPOCH - (passed % BLOCKS_PER_EPOCH)

        return {
            "block": current_block,
            "epoch": epoch,
            "remaining": remaining
        }

    except Exception as e:
        print("Block error:", e)
        return None


# ---------------- UI ----------------
def menu():
    return ReplyKeyboardMarkup(
        [["▶️ Start Epoch", "📊 Status"],
         ["🕒 Set Time", "🔄 Reset"]],
        resize_keyboard=True
    )


# ---------------- TIME LOGIC ----------------
def stats(start):
    now = int(time.time())
    elapsed = now - start

    epoch = min((elapsed // EPOCH_SECONDS) + 1, TOTAL_EPOCHS)

    taps_done = min(epoch, DAILY_USABLE_EPOCHS) * TAPS_PER_EPOCH
    taps_left = max(DAILY_TAP_LIMIT - taps_done, 0)

    h = elapsed // 3600
    m = (elapsed % 3600) // 60

    return {
        "epoch": epoch,
        "h": h,
        "m": m,
        "taps_done": taps_done,
        "taps_left": taps_left,
        "usable": min(epoch, DAILY_USABLE_EPOCHS)
    }


# ---------------- DASHBOARD ----------------
def build(start, state):
    s = stats(start)
    b = block_epoch(state)

    block_text = ""
    if b:
        block_text = (
            f"🔗 Block: {b['block']}\n"
            f"🧮 Chain Epoch: {b['epoch']}/288\n"
            f"📉 Blocks left: {b['remaining']:,}\n"
            f"📌 Start Block: {state.get('start_block')}\n\n"
        )

    return (
        f"📊 Live Dashboard\n\n"
        f"{block_text}"
        f"⏱️ {s['h']}h {s['m']}m\n"
        f"🔢 Epoch (Time): {s['epoch']}/288\n\n"
        f"🪙 Daily\n"
        f"• Epochs: {s['usable']}/172\n"
        f"• Taps: {s['taps_done']:,}/12,000\n\n"
        f"📊 Taps\n"
        f"• Done: {s['taps_done']:,}\n"
        f"• Left: {s['taps_left']:,}"
    )


async def dashboard(chat, state):
    text = build(state["start_time"], state)

    if state.get("msg_id"):
        try:
            await bot.edit_message_text(chat_id=int(chat), message_id=int(state["msg_id"]), text=text, reply_markup=menu())
            return
        except:
            pass

    msg = await bot.send_message(int(chat), text, reply_markup=menu())
    state["msg_id"] = msg.message_id


# ---------------- HANDLER ----------------
async def handle(update: Update):
    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)
    key = f"{chat}:{user}"

    store, sha = load_data()
    state = store.get(key, {})

    if not update.message:
        return

    text = update.message.text.strip()
    low = text.lower()

    if low in ["▶️ start epoch", "/start"]:
        state = {"start_time": int(time.time()), "msg_id": None}
        store[key] = state
        save_data(store, sha)
        await dashboard(chat, state)

    elif low == "📊 status":
        if "start_time" not in state:
            await bot.send_message(int(chat), "❌ Start first", reply_markup=menu())
            return
        await dashboard(chat, state)

    elif low.startswith("/setblock"):
        try:
            block = int(text.split()[1])
            state["start_block"] = block

            store[key] = state
            save_data(store, sha)

            await bot.send_message(int(chat), f"✅ Start block set: {block}")
            await dashboard(chat, state)

        except:
            await bot.send_message(int(chat), "❌ Use: /setblock 52662000")

    elif low == "🔄 reset":
        if key in store:
            del store[key]
            save_data(store, sha)

        await bot.send_message(int(chat), "🗑️ Reset done", reply_markup=menu())

    else:
        await bot.send_message(int(chat), "👇 Use menu", reply_markup=menu())


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
            print(e)

        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"ok"})
