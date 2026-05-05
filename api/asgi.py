import base64
import json
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


async def send_text(chat_id, text, forum=False):
    kw = {}
    if forum:
        kw["message_thread_id"] = 3
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


def ensure_state_defaults(state):
    if "start_block" not in state:
        state["start_block"] = EPOCH_RESET_BLOCK
    if "history" not in state or not isinstance(state["history"], list):
        state["history"] = []


def add_history(state, item):
    state["history"].append(item)


def format_duration(seconds):
    seconds = max(0, int(round(seconds / 60.0) * 60))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def format_time(dt):
    return f"{dt.strftime('%d %b %I:%M %p')} IST [UTC: {dt.astimezone(UTC).strftime('%H:%M')}]"


def sync_epoch_state(state, current_block):
    now = datetime.now(IST)

    while True:
        start = int(state["start_block"])
        reset = start + BLOCKS_PER_EPOCH

        if current_block < reset:
            break

        add_history(state, {
            "kind": "auto_reset",
            "date": now.strftime("%d %b %Y"),
            "epoch_start_block": start,
            "epoch_start_ist": now.strftime("%I:%M %p"),
            "epoch_start_utc": now.astimezone(UTC).strftime("%H:%M"),
            "reset_block": reset,
            "recorded_ist": now.strftime("%I:%M %p"),
            "recorded_utc": now.astimezone(UTC).strftime("%H:%M"),
            "epoch_duration": format_duration(BLOCKS_PER_EPOCH * AVG_BLOCK_TIME),
        })

        state["start_block"] = reset


def record_manual_set(state, entered_block, current_block, start_block, reset_block, now_ist):
    add_history(state, {
        "kind": "manual_set",
        "date": now_ist.strftime("%d %b %Y"),
        "entered_block": entered_block,
        "current_block": current_block,
        "epoch_start_block": start_block,
        "epoch_start_ist": now_ist.strftime("%I:%M %p"),
        "epoch_start_utc": now_ist.astimezone(UTC).strftime("%H:%M"),
        "reset_block": reset_block,
        "recorded_ist": now_ist.strftime("%I:%M %p"),
        "recorded_utc": now_ist.astimezone(UTC).strftime("%H:%M"),
        "epoch_duration": format_duration(BLOCKS_PER_EPOCH * AVG_BLOCK_TIME),
    })


def calculate_epoch_stats(state, current_block):
    start = int(state["start_block"])

    produced = max(0, current_block - start)
    in_epoch = produced % BLOCKS_PER_EPOCH
    next_reset = start + BLOCKS_PER_EPOCH
    left = max(0, next_reset - current_block)

    elapsed = in_epoch * AVG_BLOCK_TIME
    remaining = left * AVG_BLOCK_TIME

    now = datetime.now(IST)

    t1 = now - timedelta(seconds=elapsed)
    t2 = t1 + timedelta(seconds=TIER_1_END * AVG_BLOCK_TIME)
    t3 = t1 + timedelta(seconds=TIER_2_END * AVG_BLOCK_TIME)

    tier = (
        "Tier 1 (High reward)" if in_epoch < TIER_1_END else
        "Tier 2 (Medium reward)" if in_epoch < TIER_2_END else
        "Tier 3 (Low reward)"
    )

    return {
        "current": current_block,
        "produced": produced,
        "in_epoch": in_epoch,
        "next": next_reset,
        "left": left,
        "elapsed": elapsed,
        "remaining": remaining,
        "reset_time": now + timedelta(seconds=remaining),
        "t1": t1,
        "t2": t2,
        "t3": t3,
        "tier": tier,
    }


async def build_dashboard(state, current_block):
    s = calculate_epoch_stats(state, current_block)

    return (
        f"⏳ Timer Since Epoch Reset: {format_duration(s['elapsed'])}\n"
        f"⏱️ Time left to rest: {format_duration(s['remaining'])}\n\n"

        f"📊 Block Progress\n"
        f"• Current Block Height: {s['current']:,}\n"
        f"• Epoch 202 Reset at: {s['next']:,}\n"
        f"• Blocks produced today: {s['produced']:,}\n"
        f"• Blocks Left to Reset: {s['left']:,}\n"
        f"• Progress: {(s['in_epoch'] / BLOCKS_PER_EPOCH) * 100:.1f}%\n\n"

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


async def update_pin_message(chat, state, time_left_text):
    pin_id = state.get("pin_msg_id")
    if not pin_id:
        return

    try:
        await bot.edit_message_text(
            chat_id=int(chat),
            message_id=int(pin_id),
            text=f"⏳ Time to next epoch: {time_left_text}",
        )
    except:
        pass


async def send_dashboard(chat, state, current_block, forum=False):
    text = await build_dashboard(state, current_block)

    if state.get("msg_id"):
        try:
            await bot.delete_message(chat_id=int(chat), message_id=int(state["msg_id"]))
        except:
            pass

    msg = await send_text(chat, text, forum=forum)
    state["msg_id"] = msg.message_id

    s = calculate_epoch_stats(state, current_block)
    await update_pin_message(chat, state, format_duration(s["remaining"]))


async def handle(update: Update):
    if not update.effective_user or not update.effective_chat:
        return

    user_id = str(update.effective_user.id)
    chat = str(update.effective_chat.id)
    forum = bool(getattr(update.effective_chat, "is_forum", False))

    store, sha = load_data()
    state = store.get(chat, {})
    ensure_state_defaults(state)

    if not update.message:
        return

    text = (update.message.text or "").strip()
    low = text.lower()

    if low in ["/start", "🔄 refresh"]:
        if state.get("pin_msg_id"):
            try:
                await bot.unpin_chat_message(chat_id=int(chat))
            except:
                pass
            state.pop("pin_msg_id", None)

        current_block = await get_current_block_height()
        if current_block is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        sync_epoch_state(state, current_block)

        if low == "/start" and not state.get("seen_start"):
            await send_text(chat, "👋 Welcome to Epoch Helper Bot!", forum=forum)
            state["seen_start"] = True

        loading_msg = await send_text(chat, "⏳ Updating.....", forum=forum)
        await asyncio.sleep(2)
        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        await send_dashboard(chat, state, current_block, forum=forum)
        store[chat] = state
        save_data(store, sha)
        return

    if low in ["/status", "📊 status"]:
        loading_msg = await send_text(chat, "⏳ Updating.....", forum=forum)
        await asyncio.sleep(2)
        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        current_block = await get_current_block_height()
        if current_block is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        sync_epoch_state(state, current_block)
        await send_dashboard(chat, state, current_block, forum=forum)
        store[chat] = state
        save_data(store, sha)
        return

    if low in ["/blocks", "🔺 block height"]:
        b = await get_current_block_height()
        if b is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
        else:
            await send_text(chat, f"Block height {b:,}", forum=forum)
        return

    if low in ["/help", "ℹ️ help"]:
        help_text = (
            "🧭 Bot Commands\n\n"
            "🔄 /start - refresh, update, ping\n"
            "📊 /status - update the dashboard\n"
            "🔺 /blocks - show current block height\n"
            "📈 /analysis - show reports\n"
            "⚙️ /setblock <height> - set epoch start\n"
            "📌 /pin - send one single updating message\n"
            "ℹ️ /help - show this help"
        )
        await send_text(chat, help_text, forum=forum)
        return

    if low == "/pin":
        current_block = await get_current_block_height()
        if current_block is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        sync_epoch_state(state, current_block)
        s = calculate_epoch_stats(state, current_block)
        msg = await send_text(chat, f"⏳ Time to next epoch: {format_duration(s['remaining'])}", forum=forum)
        try:
            await bot.pin_chat_message(chat_id=int(chat), message_id=msg.message_id, disable_notification=True)
        except:
            pass
        state["pin_msg_id"] = msg.message_id

        store[chat] = state
        save_data(store, sha)
        return

    if low.startswith("/setblock"):
        if user_id not in OWNER_LIST:
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
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        now_ist = datetime.now(IST)

        if entered_block > current_block:
            start_block = entered_block - BLOCKS_PER_EPOCH
            reset_block = entered_block
        else:
            start_block = entered_block
            reset_block = entered_block + BLOCKS_PER_EPOCH

        state["start_block"] = start_block
        record_manual_set(state, entered_block, current_block, start_block, reset_block, now_ist)

        store[chat] = state
        save_data(store, sha)

        await send_text(chat, f"✅ Epoch start block set to: {entered_block:,}", forum=forum)
        return

    if low in ["/analysis", "📈 analysis"]:
        current_block = await get_current_block_height()
        if current_block is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        sync_epoch_state(state, current_block)

        hist = state.get("history", [])
        if not hist:
            await send_text(chat, "📊 No epoch records yet.", forum=forum)
            return

        out = "📊 Daily Epoch History\n\n"
        for h in hist[-30:]:
            kind = h.get("kind", "manual_set")
            if kind == "auto_reset":
                out += (
                    f"📅 {h['date']} | Auto Reset\n"
                    f"• Epoch Start Block: {h['epoch_start_block']:,}\n"
                    f"• Epoch Start Time: {h.get('epoch_start_ist', h['recorded_ist'])} | UTC: {h.get('epoch_start_utc', h['recorded_utc'])}\n"
                    f"• Reset Block: {h['reset_block']:,}\n"
                    f"• IST: {h['recorded_ist']} | UTC: {h['recorded_utc']}\n"
                    f"• Epoch Duration: {h.get('epoch_duration', format_duration(BLOCKS_PER_EPOCH * AVG_BLOCK_TIME))}\n\n"
                )
            else:
                out += (
                    f"📅 {h['date']} | Manual Set\n"
                    f"• Epoch Start Block: {h['epoch_start_block']:,}\n"
                    f"• Epoch Start Time: {h.get('epoch_start_ist', h['recorded_ist'])} | UTC: {h.get('epoch_start_utc', h['recorded_utc'])}\n"
                    f"• Reset Block: {h['reset_block']:,}\n"
                    f"• IST: {h['recorded_ist']} | UTC: {h['recorded_utc']}\n"
                    f"• Epoch Duration: {h.get('epoch_duration', format_duration(BLOCKS_PER_EPOCH * AVG_BLOCK_TIME))}\n\n"
                )

        store[chat] = state
        save_data(store, sha)
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
