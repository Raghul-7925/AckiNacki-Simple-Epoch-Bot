import base64
import json
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

KEYBOARD = ReplyKeyboardMarkup(
    [
        ["📊 Status", "🔺 Block Height"],
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
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return int(data["data"]["blockchain"]["blocks"]["nodes"][0]["seq_no"])
    except:
        return None


async def get_current_block_height():
    h = await fetch_block_height(GRAPHQL_URL_PRIMARY)
    if h:
        return h
    return await fetch_block_height(GRAPHQL_URL_FALLBACK)


def format_duration(seconds):
    seconds = int(round(seconds / 60.0) * 60)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"


def format_time(dt):
    utc = dt.astimezone(UTC)
    return f"{dt.strftime('%d %b %I:%M %p')} IST [UTC: {utc.strftime('%I:%M %p')}]"


def calculate(state, current_block):
    start_block = state.get("start_block", EPOCH_RESET_BLOCK)

    produced = current_block - start_block
    in_epoch = produced % BLOCKS_PER_EPOCH
    next_reset = start_block + BLOCKS_PER_EPOCH
    left = next_reset - current_block

    elapsed = in_epoch * AVG_BLOCK_TIME
    remaining = left * AVG_BLOCK_TIME

    now = datetime.now(IST)

    t1_start = now - timedelta(seconds=elapsed)
    t2_start = t1_start + timedelta(seconds=TIER_1_END * AVG_BLOCK_TIME)
    t3_start = t1_start + timedelta(seconds=TIER_2_END * AVG_BLOCK_TIME)

    if in_epoch < TIER_1_END:
        tier = "Tier 1 (High reward)"
    elif in_epoch < TIER_2_END:
        tier = "Tier 2 (Medium reward)"
    else:
        tier = "Tier 3 (Low reward)"

    return {
        "current": current_block,
        "produced": produced,
        "in_epoch": in_epoch,
        "next": next_reset,
        "left": left,
        "elapsed": elapsed,
        "remaining": remaining,
        "reset_time": now + timedelta(seconds=remaining),
        "t1": t1_start,
        "t2": t2_start,
        "t3": t3_start,
        "tier": tier,
    }


async def build_dashboard(state, current_block):
    s = calculate(state, current_block)

    return (
        f"⏳ Timer Since Epoch Reset: {format_duration(s['elapsed'])}\n"
        f"⏱️ Time left to rest: {format_duration(s['remaining'])}\n\n"

        f"📊 Block Progress\n"
        f"• Current Block Height: {s['current']:,}\n"
        f"• Epoch 202 Reset at: {s['next']:,}\n"
        f"• Blocks produced today: {s['produced']:,}\n"
        f"• Blocks Left to Reset: {s['left']:,}\n"
        f"• Progress: {(s['in_epoch']/BLOCKS_PER_EPOCH)*100:.1f}%\n\n"

        f"🔁 Reset Estimation\n"
        f"• {format_time(s['reset_time'])}\n\n"

        f"🏆 Reward Tiers\n\n"

        f"Tier 1 (High Reward) 🥇\n"
        f"• Start: {format_time(s['t1'])}\n\n"

        f"Tier 2 (Medium Reward) 🥈\n"
        f"• Start: {format_time(s['t2'])}\n\n"

        f"Tier 3 (Low Reward) 🥉\n"
        f"• Start: {format_time(s['t3'])}\n\n"

        f"📈 Current Status\n"
        f"• {s['tier']}"
    )


async def handle(update: Update):
    if not update.message:
        return

    chat = str(update.effective_chat.id)
    user_id = str(update.effective_user.id)

    store, sha = load_data()
    state = store.get(chat, {"start_block": EPOCH_RESET_BLOCK})

    text = (update.message.text or "").lower()

    if text in ["/status", "📊 status", "/start"]:
        b = await get_current_block_height()
        msg = await build_dashboard(state, b)
        await bot.send_message(chat, msg, reply_markup=KEYBOARD)

    elif text in ["/blocks", "🔺 block height"]:
        b = await get_current_block_height()
        await bot.send_message(chat, f"Block height {b:,}")

    elif text.startswith("/setblock"):
        if user_id not in OWNER_LIST:
            return
        state["start_block"] = int(text.split()[1])
        await bot.send_message(chat, "Block updated")

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
        except:
            pass

        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"ok"})
