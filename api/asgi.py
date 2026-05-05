import base64
import json
import time
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from telegram import Bot, Update

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = os.environ.get("GITHUB_FILE", "data.json")

OWNER_IDS = "1837260280"
TARGET_THREAD_ID = 3

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
CEST = timezone(timedelta(hours=2))

BLOCKS_PER_EPOCH = 262_000
EPOCH_RESET_BLOCK = 52_662_000
AVG_BLOCK_TIME = 0.35

TIER_1_END = BLOCKS_PER_EPOCH // 3
TIER_2_END = (BLOCKS_PER_EPOCH * 2) // 3

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]

GRAPHQL_URL_PRIMARY = "https://mainnet.ackinacki.org/graphql"
GRAPHQL_URL_FALLBACK = "https://mainnet-cf.ackinacki.org/graphql"

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
        "branch": "main",
    }
    if sha:
        body["sha"] = sha

    req = Request(GITHUB_API, data=json.dumps(body).encode(), method="PUT")
    for k, v in gh_headers().items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    urlopen(req)


def message_kwargs(forum=False):
    if forum:
        return {"message_thread_id": TARGET_THREAD_ID}
    return {}


async def send_text(chat_id, text, forum=False, **kwargs):
    kw = {}
    kw.update(message_kwargs(forum))
    kw.update(kwargs)
    return await bot.send_message(int(chat_id), text, **kw)


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

    payload = {
        "query": query,
        "variables": {"limit": 1}
    }

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
        return None

    return None


async def get_current_block_height():
    h = await fetch_block_height(GRAPHQL_URL_PRIMARY)
    if h is not None:
        return h
    return await fetch_block_height(GRAPHQL_URL_FALLBACK)


async def calculate_epoch_stats(state):
    current_block = await get_current_block_height()
    if current_block is None:
        return None

    start_block = int(state.get("start_block", EPOCH_RESET_BLOCK))

    if current_block < start_block:
        blocks_since_reset = 0
    else:
        blocks_since_reset = current_block - start_block

    blocks_in_current_epoch = blocks_since_reset % BLOCKS_PER_EPOCH
    epochs_passed = blocks_since_reset // BLOCKS_PER_EPOCH

    current_epoch = 202 + epochs_passed
    next_reset_block = start_block + ((epochs_passed + 1) * BLOCKS_PER_EPOCH)
    blocks_until_reset = next_reset_block - current_block
    progress_percent = (blocks_in_current_epoch / BLOCKS_PER_EPOCH) * 100

    estimated_reset_seconds = max(0, blocks_until_reset) * AVG_BLOCK_TIME
    reset_time = datetime.now(IST) + timedelta(seconds=estimated_reset_seconds)

    if blocks_in_current_epoch <= TIER_1_END:
        current_tier = "Tier 1 (High reward)"
        tier_blocks_progress = blocks_in_current_epoch
        tier_total_blocks = TIER_1_END
    elif blocks_in_current_epoch <= TIER_2_END:
        current_tier = "Tier 2 (Medium reward)"
        tier_blocks_progress = blocks_in_current_epoch - TIER_1_END
        tier_total_blocks = TIER_2_END - TIER_1_END
    else:
        current_tier = "Tier 3 (Low reward)"
        tier_blocks_progress = blocks_in_current_epoch - TIER_2_END
        tier_total_blocks = BLOCKS_PER_EPOCH - TIER_2_END

    tier_1_start_timestamp = int(time.time()) - (blocks_since_reset * AVG_BLOCK_TIME)
    tier_1_start_time = datetime.fromtimestamp(tier_1_start_timestamp, IST)

    tier_2_start_timestamp = tier_1_start_timestamp + (TIER_1_END * AVG_BLOCK_TIME)
    tier_2_start_time = datetime.fromtimestamp(tier_2_start_timestamp, IST)

    tier_3_start_timestamp = tier_1_start_timestamp + (TIER_2_END * AVG_BLOCK_TIME)
    tier_3_start_time = datetime.fromtimestamp(tier_3_start_timestamp, IST)

    return {
        "current_block": current_block,
        "blocks_since_reset": blocks_since_reset,
        "blocks_in_current_epoch": blocks_in_current_epoch,
        "current_epoch": current_epoch,
        "next_reset_block": next_reset_block,
        "blocks_until_reset": blocks_until_reset,
        "progress_percent": progress_percent,
        "reset_time": reset_time,
        "current_tier": current_tier,
        "tier_blocks_progress": tier_blocks_progress,
        "tier_total_blocks": tier_total_blocks,
        "tier_1_start_time": tier_1_start_time,
        "tier_2_start_time": tier_2_start_time,
        "tier_3_start_time": tier_3_start_time,
    }


def format_time_with_zones(dt_ist):
    utc_dt = dt_ist.astimezone(UTC)
    cest_dt = dt_ist.astimezone(CEST)

    ist_str = dt_ist.strftime("%d %b %I:%M %p")
    utc_str = utc_dt.strftime("%I:%M %p")
    cest_str = cest_dt.strftime("%I:%M %p")

    return f"{ist_str} IST [UTC: {utc_str} | CEST: {cest_str}]"


def format_duration(seconds):
    seconds = max(0, int(seconds))
    if seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours}h {minutes}m {secs}s"


async def build_dashboard(state):
    stats = await calculate_epoch_stats(state)
    if not stats:
        return "⚠️ Unable to fetch block data. Please try again."

    elapsed_seconds = stats["blocks_in_current_epoch"] * AVG_BLOCK_TIME
    remaining_seconds = max(0, stats["blocks_until_reset"]) * AVG_BLOCK_TIME
    timer_text = format_duration(elapsed_seconds)
    rest_text = format_duration(remaining_seconds)

    text = (
        f"⏳ Timer Since Epoch Reset: {timer_text}\n"
        f"⏱️ Time left to rest : {rest_text}\n\n"

        f"📊 Block Progress\n"
        f"• Current Block Height: {stats['current_block']:,}\n"
        f"• Epoch {stats['current_epoch']} Reset at: {stats['next_reset_block']:,}\n"
        f"• Blocks produced today: {stats['blocks_in_current_epoch']:,}/{BLOCKS_PER_EPOCH:,}\n"
        f"• Blocks Left to Reset: {stats['blocks_until_reset']:,}\n"
        f"• Progress: {stats['progress_percent']:.1f}%\n\n"

        f"🔁 Reset Estimation\n"
        f"• {format_time_with_zones(stats['reset_time'])}\n\n"

        f"🏆 Reward Tiers\n\n"

        f"Tier 1 (High Reward) 🥇\n"
        f"• Blocks: 0 - {TIER_1_END:,}\n"
        f"• Start: {format_time_with_zones(stats['tier_1_start_time'])}\n\n"

        f"Tier 2 (Medium Reward) 🥈\n"
        f"• Blocks: {TIER_1_END:,} - {TIER_2_END:,}\n"
        f"• Start: {format_time_with_zones(stats['tier_2_start_time'])}\n\n"

        f"Tier 3 (Low Reward) 🥉\n"
        f"• Blocks: {TIER_2_END:,} - {BLOCKS_PER_EPOCH:,}\n"
        f"• Start: {format_time_with_zones(stats['tier_3_start_time'])}\n\n"

        f"📈 Current Status\n"
        f"• {stats['current_tier']}\n"
        f"• Blocks in Tier: {stats['tier_blocks_progress']:,} / {stats['tier_total_blocks']:,}"
    )

    return text


async def send_dashboard(chat, state, forum=False):
    text = await build_dashboard(state)

    if state.get("msg_id"):
        try:
            await bot.delete_message(chat_id=int(chat), message_id=int(state["msg_id"]))
        except:
            pass

    msg = await send_text(chat, text, forum=forum)
    state["msg_id"] = msg.message_id


async def handle(update: Update):
    if not update.effective_user or not update.effective_chat:
        return

    user_id = str(update.effective_user.id)
    chat = str(update.effective_chat.id)
    forum = bool(getattr(update.effective_chat, "is_forum", False))

    key = chat
    store, sha = load_data()
    state = store.get(key, {})

    if not update.message:
        return

    text = (update.message.text or "").strip()
    low = text.lower()

    if low == "/start":
        is_new = not bool(state)
        if "start_block" not in state:
            state["start_block"] = EPOCH_RESET_BLOCK
        if is_new:
            await send_text(chat, "👋 Welcome to Epoch Helper Bot!", forum=forum)
        await send_dashboard(chat, state, forum=forum)
        store[key] = state
        save_data(store, sha)
        return

    if low == "/status":
        await send_dashboard(chat, state, forum=forum)
        store[key] = state
        save_data(store, sha)
        return

    if low == "/block":
        b = await get_current_block_height()
        if b is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
        else:
            await send_text(chat, f"📦 Current Block: {b:,}", forum=forum)
        return

    if low.startswith("/setblock"):
        if user_id not in OWNER_LIST:
            await send_text(chat, "❌ You are not allowed to use /setblock.", forum=forum)
            return

        parts = text.split()
        if len(parts) < 2:
            await send_text(chat, "❌ Usage: /setblock <block_height>", forum=forum)
            return

        try:
            entered_block = int(parts[1])
        except:
            await send_text(chat, "❌ Invalid block height.", forum=forum)
            return

        current_block = await get_current_block_height()
        if current_block is None:
            await send_text(chat, "⚠️ Unable to fetch current block height. Try again.", forum=forum)
            return

        now = datetime.now(IST)

        if entered_block > current_block:
            start_block = entered_block - BLOCKS_PER_EPOCH
            reset_block = entered_block
            mode = "future reset block"
        else:
            start_block = entered_block
            reset_block = entered_block + BLOCKS_PER_EPOCH
            mode = "previous day reset block"

        state["start_block"] = start_block
        state["reset_block"] = reset_block
        state["last_set_block"] = entered_block
        state["last_set_mode"] = mode
        state["last_current_block"] = current_block

        history = state.get("history", [])
        history.append({
            "date": now.strftime("%d %b %Y"),
            "entered_block": entered_block,
            "current_block": current_block,
            "start_block": start_block,
            "reset_block": reset_block,
            "mode": mode,
            "ist_time": now.strftime("%I:%M %p"),
            "utc_time": now.astimezone(UTC).strftime("%I:%M %p"),
        })
        state["history"] = history

        store[key] = state
        save_data(store, sha)

        await send_text(
            chat,
            (
                f"✅ Block stored\n"
                f"• Current block: {current_block:,}\n"
                f"• Entered block: {entered_block:,}\n"
                f"• Mode: {mode}\n"
                f"• Epoch start block: {start_block:,}\n"
                f"• Reset block: {reset_block:,}"
            ),
            forum=forum,
        )
        return

    if low == "/analysis":
        hist = state.get("history", [])
        if not hist:
            await send_text(chat, "No data", forum=forum)
            return

        out = "📊 Epoch History\n\n"
        for h in hist[-20:]:
            out += (
                f"{h['date']} | {h['mode']}\n"
                f"Entered: {h['entered_block']:,}\n"
                f"Current: {h['current_block']:,}\n"
                f"Epoch start: {h['start_block']:,}\n"
                f"Reset block: {h['reset_block']:,}\n"
                f"IST: {h['ist_time']} | UTC: {h['utc_time']}\n\n"
            )

        await send_text(chat, out, forum=forum)
        return


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
