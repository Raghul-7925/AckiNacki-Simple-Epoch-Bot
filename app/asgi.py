import base64
import copy
import json
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from telegram import Bot, Update, ReplyKeyboardRemove

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

EPOCH_202_START_IST = datetime(2025, 5, 4, 17, 30, tzinfo=IST)
EPOCH_DURATION_SECONDS = BLOCKS_PER_EPOCH * AVG_BLOCK_TIME

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]

GRAPHQL_URL_PRIMARY = "https://mainnet.ackinacki.org/graphql"
GRAPHQL_URL_FALLBACK = "https://mainnet-cf.ackinacki.org/graphql"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

GLOBAL_KEY = "global_epoch_state"
CHAT_META_KEY = "chat_meta"


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


async def load_data_async():
    return await asyncio.to_thread(load_data)


async def save_data_async(store, sha):
    return await asyncio.to_thread(save_data, store, sha)


async def send_text(chat_id, text, forum=False):
    kw = {"reply_markup": ReplyKeyboardRemove()}
    if forum:
        kw["message_thread_id"] = TARGET_THREAD_ID
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


def ensure_global_defaults(state):
    if "start_block" not in state:
        state["start_block"] = EPOCH_RESET_BLOCK
    if "epoch_start_ts" not in state:
        state["epoch_start_ts"] = int(EPOCH_202_START_IST.timestamp())
    if "history" not in state or not isinstance(state["history"], list):
        state["history"] = []
    state.pop("msg_id", None)
    state.pop("pin_msg_id", None)
    state.pop("seen_start", None)


def ensure_chat_defaults(meta):
    if "msg_id" not in meta:
        meta["msg_id"] = None
    if "pin_msg_id" not in meta:
        meta["pin_msg_id"] = None
    if "seen_start" not in meta:
        meta["seen_start"] = False


def choose_global_candidate(store):
    best = None
    best_score = (-1, -1, -1)

    for k, v in store.items():
        if k in (GLOBAL_KEY, CHAT_META_KEY):
            continue
        if isinstance(v, dict) and ("start_block" in v or "history" in v or "epoch_start_ts" in v):
            sb = int(v.get("start_block", 0) or 0)
            hl = len(v.get("history", [])) if isinstance(v.get("history"), list) else 0
            ts = int(v.get("epoch_start_ts", 0) or 0)
            score = (sb, hl, ts)
            if score > best_score:
                best_score = score
                best = copy.deepcopy(v)

    return best


def get_global_state(store):
    if GLOBAL_KEY not in store or not isinstance(store.get(GLOBAL_KEY), dict):
        candidate = choose_global_candidate(store)
        if candidate is None:
            candidate = {}
        store[GLOBAL_KEY] = candidate

    if CHAT_META_KEY not in store or not isinstance(store.get(CHAT_META_KEY), dict):
        store[CHAT_META_KEY] = {}

    ensure_global_defaults(store[GLOBAL_KEY])
    return store[GLOBAL_KEY]


def get_chat_meta(store, chat):
    chat_meta = store.setdefault(CHAT_META_KEY, {})
    meta = chat_meta.get(chat)

    if not isinstance(meta, dict):
        meta = {}
        old = store.get(chat)
        if isinstance(old, dict):
            for key in ("msg_id", "pin_msg_id", "seen_start"):
                if key in old:
                    meta[key] = old[key]
        chat_meta[chat] = meta

    ensure_chat_defaults(meta)
    return meta


def add_history(state, item):
    state["history"].append(item)


def get_epoch_no_from_start(start_block):
    if start_block <= EPOCH_RESET_BLOCK:
        return 202
    return 202 + ((start_block - EPOCH_RESET_BLOCK) // BLOCKS_PER_EPOCH)


def get_epoch_start_dt(epoch_no):
    delta_epochs = epoch_no - 202
    return EPOCH_202_START_IST + timedelta(seconds=delta_epochs * EPOCH_DURATION_SECONDS)


def format_duration(seconds):
    seconds = max(0, int(round(seconds / 60.0) * 60))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def format_time(dt):
    return f"{dt.strftime('%d %b %I:%M %p')} IST [UTC: {dt.astimezone(UTC).strftime('%H:%M')}]"


def get_current_reward_tier(in_epoch):
    if in_epoch < TIER_1_END:
        return "Tier 1 - High Reward (<6k taps)"
    if in_epoch < TIER_2_END:
        return "Tier 2 - Medium Reward (>6k taps)"
    return "Tier 3 - Low Reward( > 12k taps)"


def sync_epoch_state(state, current_block):
    while True:
        start = int(state["start_block"])
        reset = start + BLOCKS_PER_EPOCH

        if current_block < reset:
            break

        epoch_no = get_epoch_no_from_start(start)
        epoch_start_dt = get_epoch_start_dt(epoch_no)
        epoch_reset_dt = epoch_start_dt + timedelta(seconds=EPOCH_DURATION_SECONDS)

        add_history(state, {
            "kind": "auto_reset",
            "date": epoch_reset_dt.strftime("%d %b %Y"),
            "epoch_no": epoch_no,
            "epoch_start_block": start,
            "epoch_start_ist": epoch_start_dt.strftime("%I:%M %p"),
            "epoch_start_utc": epoch_start_dt.astimezone(UTC).strftime("%H:%M"),
            "reset_block": reset,
            "reset_ist": epoch_reset_dt.strftime("%I:%M %p"),
            "reset_utc": epoch_reset_dt.astimezone(UTC).strftime("%H:%M"),
            "epoch_duration": format_duration(EPOCH_DURATION_SECONDS),
        })

        state["epoch_start_ts"] = int(epoch_reset_dt.timestamp())
        state["start_block"] = reset


def record_manual_set(state, entered_block, current_block, start_block, reset_block, now_ist):
    epoch_no = get_epoch_no_from_start(start_block)
    epoch_start_dt = get_epoch_start_dt(epoch_no)
    epoch_reset_dt = epoch_start_dt + timedelta(seconds=EPOCH_DURATION_SECONDS)

    add_history(state, {
        "kind": "manual_set",
        "date": now_ist.strftime("%d %b %Y"),
        "epoch_no": epoch_no,
        "entered_block": entered_block,
        "current_block": current_block,
        "epoch_start_block": start_block,
        "epoch_start_ist": epoch_start_dt.strftime("%I:%M %p"),
        "epoch_start_utc": epoch_start_dt.astimezone(UTC).strftime("%H:%M"),
        "reset_block": reset_block,
        "reset_ist": epoch_reset_dt.strftime("%I:%M %p"),
        "reset_utc": epoch_reset_dt.astimezone(UTC).strftime("%H:%M"),
        "epoch_duration": format_duration(EPOCH_DURATION_SECONDS),
    })


def calculate_epoch_stats(state, current_block):
    start = int(state["start_block"])

    produced = max(0, current_block - start)
    in_epoch = produced % BLOCKS_PER_EPOCH
    next_reset = start + BLOCKS_PER_EPOCH
    left = max(0, next_reset - current_block)

    elapsed = in_epoch * AVG_BLOCK_TIME
    remaining = left * AVG_BLOCK_TIME

    epoch_no = get_epoch_no_from_start(start)

    if "epoch_start_ts" in state:
        epoch_start_dt = datetime.fromtimestamp(int(state["epoch_start_ts"]), IST)
    else:
        epoch_start_dt = get_epoch_start_dt(epoch_no)

    reset_dt = datetime.now(IST) + timedelta(seconds=remaining)

    tier = get_current_reward_tier(in_epoch)

    return {
        "epoch_no": epoch_no,
        "current": current_block,
        "produced": produced,
        "in_epoch": in_epoch,
        "next": next_reset,
        "left": left,
        "elapsed": elapsed,
        "remaining": remaining,
        "reset_time": reset_dt,
        "epoch_start_dt": epoch_start_dt,
        "tier": tier,
    }


async def build_dashboard(global_state, current_block):
    s = calculate_epoch_stats(global_state, current_block)

    return (
        f"⏳ Timer Since Epoch Reset: {format_duration(s['elapsed'])}\n"
        f"⏱️ Time left to rest: {format_duration(s['remaining'])}\n\n"

        f"📊 Block Progress\n"
        f"• Current Block Height: {s['current']:,}\n"
        f"• Epoch {s['epoch_no']} Reset at: {s['next']:,}\n"
        f"• Blocks produced today: {s['produced']:,}\n"
        f"• Blocks Left to Reset: {s['left']:,}\n"
        f"• Progress: {(s['in_epoch'] / BLOCKS_PER_EPOCH) * 100:.1f}%\n\n"

        f"🔁 Reset Estimation\n"
        f"• {format_time(s['reset_time'])}\n\n"

        f"🏆 Current Reward Tier\n"
        f"• {s['tier']}"
    )


async def animate_message(chat, message_id, texts, forum=False, delay=0.2):
    if not texts:
        return

    for t in texts[1:]:
        await asyncio.sleep(delay)
        try:
            await bot.edit_message_text(
                chat_id=int(chat),
                message_id=int(message_id),
                text=t,
            )
        except:
            pass


async def update_pin_message(chat, meta, global_state, time_left_text, forum=False):
    pin_id = meta.get("pin_msg_id")
    if not pin_id:
        return

    new_text = f"⏳ Time to next epoch: {time_left_text}"

    try:
        await bot.edit_message_text(
            chat_id=int(chat),
            message_id=int(pin_id),
            text=new_text,
        )
        return
    except Exception as e:
        print("PIN EDIT ERROR:", e)

    try:
        await bot.unpin_chat_message(chat_id=int(chat))
    except:
        pass

    try:
        kw = {"reply_markup": ReplyKeyboardRemove()}
        if forum:
            kw["message_thread_id"] = TARGET_THREAD_ID

        msg = await bot.send_message(int(chat), new_text, **kw)
        await bot.pin_chat_message(
            chat_id=int(chat),
            message_id=msg.message_id,
            disable_notification=True,
        )
        meta["pin_msg_id"] = msg.message_id
    except:
        pass


async def send_dashboard(chat, meta, global_state, current_block, forum=False):
    text = await build_dashboard(global_state, current_block)

    if meta.get("msg_id"):
        try:
            await bot.delete_message(chat_id=int(chat), message_id=int(meta["msg_id"]))
        except:
            pass

    msg = await send_text(chat, text, forum=forum)
    meta["msg_id"] = msg.message_id

    s = calculate_epoch_stats(global_state, current_block)
    await update_pin_message(chat, meta, global_state, format_duration(s["remaining"]), forum=forum)


async def handle(update: Update):
    if not update.effective_user or not update.effective_chat:
        return

    user_id = str(update.effective_user.id)
    chat = str(update.effective_chat.id)
    forum = bool(getattr(update.effective_chat, "is_forum", False))

    store, sha = await load_data_async()
    global_state = get_global_state(store)
    chat_meta = get_chat_meta(store, chat)

    if not update.message:
        return

    text = (update.message.text or "").strip()
    low = text.lower()

    if low in ["/start", "🔄 refresh"]:
        if chat_meta.get("pin_msg_id"):
            try:
                await bot.unpin_chat_message(chat_id=int(chat))
            except:
                pass
            chat_meta["pin_msg_id"] = None

        current_block = await get_current_block_height()
        if current_block is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        sync_epoch_state(global_state, current_block)

        if low == "/start" and not chat_meta.get("seen_start"):
            await send_text(chat, "👋 Welcome to Epoch Helper Bot!", forum=forum)
            chat_meta["seen_start"] = True

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        await animate_message(
            chat,
            loading_msg.message_id,
            ["📡 Connecting to blockchain...", "🔄 Initializing epoch state...", "✅ Sync complete..."],
            forum=forum,
            delay=0.2,
        )
        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        await send_dashboard(chat, chat_meta, global_state, current_block, forum=forum)

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)
        return

    if low in ["/status", "📊 status"]:
        block_task = asyncio.create_task(get_current_block_height())

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        await animate_message(
            chat,
            loading_msg.message_id,
            ["📡 Connecting to blockchain...", "🔄 Syncing live epoch data...", "📊 Building dashboard..."],
            forum=forum,
            delay=0.2,
        )

        current_block = await block_task
        if current_block is None:
            try:
                await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
            except:
                pass
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        sync_epoch_state(global_state, current_block)

        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        await send_dashboard(chat, chat_meta, global_state, current_block, forum=forum)

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)
        return

    if low in ["/blocks", "🔺 block height"]:
        block_task = asyncio.create_task(get_current_block_height())

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        await animate_message(
            chat,
            loading_msg.message_id,
            ["📡 Connecting to blockchain...", "🔍 Fetching data...", "📖 Reading live block height..."],
            forum=forum,
            delay=0.2,
        )

        b = await block_task
        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        if b is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
        else:
            await send_text(chat, f"📦 Block height is {b:,}", forum=forum)
        return

    if low in ["/help", "ℹ️ help"]:
        help_text = (
            "🧭 Bot Commands\n\n"
            "📊 /status - Update The Dashboard\n"
            "📦 /blocks - Show Current Block Height\n"
            "📈 /analysis - Show Reports\n"
            "ℹ️ /help - Show This Help"
        )
        await send_text(chat, help_text, forum=forum)
        return

    if low == "/pin":
        current_block = await get_current_block_height()
        if current_block is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        sync_epoch_state(global_state, current_block)
        s = calculate_epoch_stats(global_state, current_block)

        msg = await send_text(chat, f"⏳ Time to next epoch: {format_duration(s['remaining'])}", forum=forum)

        try:
            await bot.pin_chat_message(
                chat_id=int(chat),
                message_id=msg.message_id,
                disable_notification=True,
            )
        except:
            pass

        chat_meta["pin_msg_id"] = msg.message_id

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)
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

        global_state["start_block"] = start_block
        global_state["epoch_start_ts"] = int(now_ist.timestamp())
        record_manual_set(global_state, entered_block, current_block, start_block, reset_block, now_ist)

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)

        await send_text(chat, f"✅ Epoch start block set to: {entered_block:,}", forum=forum)
        return

    if low in ["/analysis", "📈 analysis"]:
        load_task = asyncio.create_task(load_data_async())

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        await animate_message(
            chat,
            loading_msg.message_id,
            ["📡 Connecting to blockchain...", "📚 Collecting epoch history...", "📊 Building analysis report..."],
            forum=forum,
            delay=0.2,
        )

        store, sha = await load_task
        global_state = get_global_state(store)
        chat_meta = get_chat_meta(store, chat)

        current_block = await get_current_block_height()
        if current_block is None:
            try:
                await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
            except:
                pass
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
            return

        sync_epoch_state(global_state, current_block)

        hist = global_state.get("history", [])
        async def app(scope, receive, send):
    if scope["type"] == "http":
        body = b""
        more = True

        while more:
            message = await receive()
            body += message.get("body", b"")
            more = message.get("more_body", False)

        try:
            data = json.loads(body.decode())
            update = Update.de_json(data, bot)
            await handle(update)
        except Exception as e:
            print(e)

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                [b"content-type", b"text/plain"]
            ]
        })

        await send({
            "type": "http.response.body",
            "body": b"ok"
        })
        
