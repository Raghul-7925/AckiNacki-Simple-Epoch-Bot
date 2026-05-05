import base64
import json
import time
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from telegram import Bot, Update, ReplyKeyboardMarkup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "data.json")

OWNER_IDS = "1837260280"
TARGET_THREAD_ID = 3

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

BLOCKS_PER_EPOCH = 262_000
EPOCH_RESET_BLOCK = 52_662_000
AVG_BLOCK_TIME = 0.35

TIER_1_END = BLOCKS_PER_EPOCH // 3
TIER_2_END = (BLOCKS_PER_EPOCH * 2) // 3

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]

GRAPHQL_URL_PRIMARY = "https://mainnet.ackinacki.org/graphql"
GRAPHQL_URL_FALLBACK = "https://mainnet-cf.ackinacki.org/graphql"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

# ✅ Updated Keyboard
KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📊 Status", "📦 Block Height"],
        ["⚙️ Set Block", "📈 Analysis"],
        ["ℹ️ Help"],
    ],
    resize_keyboard=True,
)


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
        "branch": "main",
    }
    if sha:
        body["sha"] = sha

    req = Request(GITHUB_API, data=json.dumps(body).encode(), method="PUT")
    for k, v in gh_headers().items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    urlopen(req)


async def fetch_block_height(url):
    query = """
    query GetBlocks($limit: Int!) {
        blockchain {
            blocks(last: $limit) {
                nodes {
                    seq_no
                }
            }
        }
    }
    """

    payload = {"query": query, "variables": {"limit": 1}}

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=timeout) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    blocks = data.get("data", {}).get("blockchain", {}).get("blocks", {}).get("nodes", [])
                    if blocks:
                        return int(blocks[0]["seq_no"])
    except:
        pass

    return None


async def get_current_block_height():
    h = await fetch_block_height(GRAPHQL_URL_PRIMARY)
    if h is not None:
        return h
    return await fetch_block_height(GRAPHQL_URL_FALLBACK)


def format_duration(seconds):
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    secs = seconds % 60
    return f"{minutes}m {secs}s"


def calculate_epoch_stats(state, current_block):
    start_block = int(state.get("start_block", EPOCH_RESET_BLOCK))

    blocks_since_reset = max(0, current_block - start_block)

    blocks_in_current_epoch = blocks_since_reset % BLOCKS_PER_EPOCH
    next_reset_block = start_block + BLOCKS_PER_EPOCH
    blocks_until_reset = next_reset_block - current_block

    elapsed_seconds = blocks_in_current_epoch * AVG_BLOCK_TIME
    time_left_seconds = blocks_until_reset * AVG_BLOCK_TIME

    reset_time = datetime.now(IST) + timedelta(seconds=time_left_seconds)

    return {
        "current_block": current_block,
        "blocks_in_current_epoch": blocks_in_current_epoch,
        "next_reset_block": next_reset_block,
        "blocks_until_reset": blocks_until_reset,
        "reset_time": reset_time,
        "elapsed_seconds": elapsed_seconds,
        "time_left_seconds": time_left_seconds,
    }


async def build_dashboard(state, current_block):
    stats = calculate_epoch_stats(state, current_block)

    return (
        f"⏳ Timer Since Epoch Reset: {format_duration(stats['elapsed_seconds'])}\n"
        f"⏱️ Time left to rest: {format_duration(stats['time_left_seconds'])}\n\n"

        f"📊 Block Progress\n"
        f"• Current Block Height: {stats['current_block']:,}\n"
        f"• Blocks produced today: {stats['blocks_in_current_epoch']:,}\n"
        f"• Blocks Left to Reset: {stats['blocks_until_reset']:,}\n\n"

        f"🏆 Reward Tiers\n\n"

        f"Tier 1 (High Reward) 🥇\n"
        f"• Start: {stats['reset_time'].strftime('%d %b %I:%M %p')} IST\n\n"

        f"Tier 2 (Medium Reward) 🥈\n"
        f"• Start: {stats['reset_time'].strftime('%d %b %I:%M %p')} IST\n\n"

        f"Tier 3 (Low Reward) 🥉\n"
        f"• Start: {stats['reset_time'].strftime('%d %b %I:%M %p')} IST"
    )


async def send_dashboard(chat, state, current_block):
    text = await build_dashboard(state, current_block)

    if state.get("msg_id"):
        try:
            await bot.edit_message_text(
                chat_id=int(chat),
                message_id=int(state["msg_id"]),
                text=text,
                reply_markup=KEYBOARD
            )
            return
        except:
            pass

    msg = await bot.send_message(int(chat), text, reply_markup=KEYBOARD)
    state["msg_id"] = msg.message_id


async def handle(update: Update):
    if not update.message:
        return

    user_id = str(update.effective_user.id)
    chat = str(update.effective_chat.id)

    store, sha = load_data()
    state = store.get(chat, {"start_block": EPOCH_RESET_BLOCK})

    text = (update.message.text or "").strip().lower()

    if text in ["/start", "📊 status", "/status"]:
        current_block = await get_current_block_height()
        await send_dashboard(chat, state, current_block)

    elif text in ["/blocks", "🔺 block height"]:
        b = await get_current_block_height()
        await bot.send_message(chat, f"Block height {b:,}")

    elif text.startswith("/setblock"):
        if user_id not in OWNER_LIST:
            return

        parts = text.split()
        if len(parts) < 2:
            return

        state["start_block"] = int(parts[1])
        await bot.send_message(chat, f"✅ Block set: {parts[1]}")

    store[chat] = state
    save_data(store, sha)


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
