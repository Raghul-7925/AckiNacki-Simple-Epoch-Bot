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

# Known epoch resets with their exact block numbers
EPOCH_ANCHORS = {
    204: 53_448_000,  # Epoch 204 reset block
    205: 53_710_000,  # Epoch 205 reset block
    # Add more as needed
}

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]

GRAPHQL_URL_PRIMARY = "https://mainnet.ackinacki.org/graphql"
GRAPHQL_URL_FALLBACK = "https://mainnet-cf.ackinacki.org/graphql"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

GLOBAL_KEY = "global_epoch_state"
CHAT_META_KEY = "chat_meta"

DEFAULT_ENDPOINTS = "mainnet.ackinacki.org,mainnet-cf.ackinacki.org"
DEFAULT_SAMPLE_BLOCKS = 120


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


def env_int(key, fallback):
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return fallback
    try:
        return int(raw)
    except:
        return fallback


def normalize_endpoint(endpoint):
    trimmed = str(endpoint or "").strip()
    if not trimmed:
        return None
    without_slash = trimmed.rstrip("/")
    return without_slash if without_slash.startswith("http") else f"https://{without_slash}"


def build_graphql_urls():
    raw = os.environ.get("ENDPOINTS", DEFAULT_ENDPOINTS)
    urls = []
    seen = set()

    for endpoint in raw.split(","):
        base = normalize_endpoint(endpoint)
        if not base:
            continue
        url = f"{base}/graphql"
        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls or [GRAPHQL_URL_PRIMARY, GRAPHQL_URL_FALLBACK]


def normalize_uint(value):
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except:
            return 0
    return 0


async def graphql_fetch(query, retries_per_endpoint=2):
    urls = build_graphql_urls()
    last_err = None

    for url in urls:
        for i in range(retries_per_endpoint):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        url,
                        json={"query": query},
                        timeout=timeout,
                    ) as resp:
                        if not resp.ok:
                            raise RuntimeError(f"HTTP {resp.status} @ {url}")
                        return {"url": url, "json": await resp.json()}
            except Exception as e:
                last_err = e
                if i < retries_per_endpoint - 1:
                    await asyncio.sleep(1)

    raise last_err if last_err else RuntimeError("GraphQL failed on all endpoints")


async def get_live_block_snapshot():
    """
    Fetch live block data with timestamps using smart sampling.
    Returns block height, observed timestamp, and calculated block rate.
    """
    sample_blocks = max(3, env_int("BLOCK_SAMPLE_BLOCKS", DEFAULT_SAMPLE_BLOCKS))
    query = f"""
    query {{
        blockchain {{
            blocks(last: {sample_blocks}) {{
                edges {{
                    node {{
                        seq_no
                        gen_utime
                    }}
                }}
            }}
        }}
    }}
    """

    result = await graphql_fetch(query)
    edges = (
        result.get("json", {})
        .get("data", {})
        .get("blockchain", {})
        .get("blocks", {})
        .get("edges", [])
    )

    parsed = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node", {})
        if not isinstance(node, dict):
            continue
        
        seq_no = normalize_uint(node.get("seq_no"))
        gen_utime = normalize_uint(node.get("gen_utime"))
        
        if seq_no > 0:
            parsed.append({"seq_no": seq_no, "gen_utime": gen_utime})

    parsed.sort(key=lambda x: x["seq_no"])

    if not parsed:
        raise RuntimeError("No block height available from blockchain.blocks")

    first = parsed[0]
    last = parsed[-1]

    # Calculate observed block rate from sample
    sample_block_sec = None
    if (
        len(parsed) >= 2
        and first["seq_no"] > 0
        and last["seq_no"] > first["seq_no"]
        and last["gen_utime"] >= first["gen_utime"]
    ):
        delta_seq = last["seq_no"] - first["seq_no"]
        delta_sec = last["gen_utime"] - first["gen_utime"]
        if delta_seq > 0 and delta_sec >= 0:
            sample_block_sec = delta_sec / delta_seq

    observed_at = (
        datetime.fromtimestamp(last["gen_utime"], UTC).isoformat()
        if last["gen_utime"] > 0
        else datetime.now(UTC).isoformat()
    )

    return {
        "sourceUrl": result["url"],
        "currentHeight": last["seq_no"],
        "currentTimestamp": last["gen_utime"],
        "sampleBlockSec": sample_block_sec,
        "sampleBlocks": len(parsed),
        "observedAt": observed_at,
        "firstBlock": first["seq_no"],
        "firstTimestamp": first["gen_utime"],
        "lastBlock": last["seq_no"],
        "lastTimestamp": last["gen_utime"],
    }


async def get_current_block_height():
    snapshot = await get_live_block_snapshot()
    return snapshot["currentHeight"]


def ensure_global_defaults(state):
    """Initialize global state with epoch anchor tracking."""
    if "start_block" not in state:
        state["start_block"] = EPOCH_RESET_BLOCK
    if "epoch_start_ts" not in state:
        state["epoch_start_ts"] = None
    if "last_block_sec" not in state:
        state["last_block_sec"] = AVG_BLOCK_TIME
    if "history" not in state:
        state["history"] = []
    if "last_epoch_index" not in state:
        state["last_epoch_index"] = None
    if "epoch_anchors" not in state:
        state["epoch_anchors"] = {}
    if "anchor_source" not in state:
        state["anchor_source"] = None


def get_global_state(store):
    state = store.get(GLOBAL_KEY, {})
    ensure_global_defaults(state)
    return state


def get_chat_meta(store, chat_id):
    meta_map = store.setdefault(CHAT_META_KEY, {})
    chat_str = str(chat_id)
    if chat_str not in meta_map:
        meta_map[chat_str] = {"tier": 1, "last_update": None}
    return meta_map[chat_str]


def update_epoch_anchor_if_needed(state, current_epoch_index, epoch_start_block, observed_timestamp):
    """
    Smart epoch anchor tracking - updates only when epoch changes.
    Stores the exact timestamp when a new epoch begins.
    """
    last_epoch_index = state.get("last_epoch_index")
    epoch_anchors = state.get("epoch_anchors", {})
    
    epoch_key = str(current_epoch_index)
    
    # If this is a new epoch we haven't tracked yet
    if last_epoch_index != current_epoch_index:
        if epoch_key not in epoch_anchors:
            # Store the anchor for this epoch
            epoch_anchors[epoch_key] = {
                "epoch_index": current_epoch_index,
                "start_block": epoch_start_block,
                "start_timestamp": observed_timestamp,
                "recorded_at": datetime.now(UTC).isoformat(),
                "source": "auto_detected"
            }
            state["epoch_anchors"] = epoch_anchors
            state["anchor_source"] = "auto_epoch_change"
        
        state["last_epoch_index"] = current_epoch_index
        state["epoch_start_ts"] = observed_timestamp
        
        return True  # Epoch changed
    
    return False  # Same epoch


def get_epoch_status_with_timestamp(state, current_block, current_timestamp, sample_block_sec=None):
    """
    Calculate epoch status using timestamp-based calculations.
    Uses epoch anchors for accurate time estimation.
    """
    epoch_span = BLOCKS_PER_EPOCH
    
    current_epoch_index = current_block // epoch_span
    epoch_start_block = current_epoch_index * epoch_span
    epoch_end_block = epoch_start_block + epoch_span
    
    elapsed_blocks = max(0, current_block - epoch_start_block)
    remaining_blocks = max(0, epoch_end_block - current_block)
    progress_pct = min(100, (elapsed_blocks / max(1, epoch_span)) * 100)
    
    # Update anchor if epoch changed
    epoch_changed = update_epoch_anchor_if_needed(state, current_epoch_index, epoch_start_block, current_timestamp)
    
    # Get anchor data for this epoch
    epoch_key = str(current_epoch_index)
    epoch_anchors = state.get("epoch_anchors", {})
    anchor = epoch_anchors.get(epoch_key)
    
    # Calculate block rate using different methods
    estimated_block_sec = None
    estimate_source = "unavailable"
    
    if anchor and current_timestamp > anchor["start_timestamp"] and elapsed_blocks > 0:
        # Best method: Use epoch anchor for average since epoch start
        elapsed_seconds = current_timestamp - anchor["start_timestamp"]
        estimated_block_sec = elapsed_seconds / elapsed_blocks
        estimate_source = "epoch_anchor_average"
    elif sample_block_sec and sample_block_sec > 0:
        # Fallback: Use recent sample
        estimated_block_sec = sample_block_sec
        estimate_source = "graphql_sample"
    else:
        # Last resort: Use stored average
        estimated_block_sec = state.get("last_block_sec", AVG_BLOCK_TIME)
        estimate_source = "stored_average"
    
    # Calculate remaining time
    remaining_seconds = remaining_blocks * estimated_block_sec if estimated_block_sec else None
    
    return {
        "epoch_span_blocks": epoch_span,
        "current_epoch_index": current_epoch_index,
        "epoch_start_block": epoch_start_block,
        "epoch_end_block": epoch_end_block,
        "elapsed_blocks": elapsed_blocks,
        "remaining_blocks": remaining_blocks,
        "progress_pct": progress_pct,
        "epoch_start_timestamp": anchor["start_timestamp"] if anchor else None,
        "epoch_changed": epoch_changed,
        "anchor_source": state.get("anchor_source"),
        "sample_block_sec": sample_block_sec,
        "estimated_block_sec": estimated_block_sec,
        "estimate_source": estimate_source,
        "remaining_seconds": remaining_seconds,
    }


def sync_epoch_state(state, current_block, current_timestamp=None, block_sec=None):
    """Sync epoch state and detect auto-resets with timestamp tracking."""
    if current_timestamp is None:
        current_timestamp = int(datetime.now(UTC).timestamp())
    
    epoch_status = get_epoch_status_with_timestamp(state, current_block, current_timestamp, block_sec)
    
    start_block = state["start_block"]
    expected_next = start_block + BLOCKS_PER_EPOCH
    
    # Detect epoch reset
    if current_block >= expected_next:
        new_start = (current_block // BLOCKS_PER_EPOCH) * BLOCKS_PER_EPOCH
        
        # Get the exact timestamp for the reset block
        reset_timestamp = epoch_status.get("epoch_start_timestamp", current_timestamp)
        
        record_auto_reset(
            state, 
            current_block, 
            new_start, 
            expected_next, 
            reset_timestamp,
            block_sec=epoch_status.get("estimated_block_sec", block_sec)
        )
        
        state["start_block"] = new_start
        state["epoch_start_ts"] = reset_timestamp


def record_auto_reset(state, current_block, new_start, reset_block, reset_timestamp, block_sec=None):
    """Record auto-reset with precise timestamp information."""
    if block_sec is None:
        block_sec = state.get("last_block_sec", AVG_BLOCK_TIME)
    
    epoch_no = new_start // BLOCKS_PER_EPOCH
    
    # Calculate epoch duration using timestamps
    epoch_key = str(epoch_no - 1)  # Previous epoch
    epoch_anchors = state.get("epoch_anchors", {})
    prev_anchor = epoch_anchors.get(epoch_key)
    
    if prev_anchor and reset_timestamp:
        # Calculate actual epoch duration from timestamps
        epoch_duration_sec = reset_timestamp - prev_anchor["start_timestamp"]
        epoch_duration = format_duration_seconds(epoch_duration_sec)
    else:
        # Fallback to block-based calculation
        epoch_duration = epoch_duration_text(block_sec)
    
    reset_dt_utc = datetime.fromtimestamp(reset_timestamp, UTC)
    reset_dt_ist = reset_dt_utc.astimezone(IST)
    
    entry = {
        "kind": "auto_reset",
        "epoch_no": epoch_no,
        "date": reset_dt_ist.strftime("%Y-%m-%d"),
        "current_block": current_block,
        "epoch_start_block": new_start,
        "reset_block": reset_block,
        "reset_timestamp": reset_timestamp,
        "epoch_start_utc": reset_dt_utc.strftime("%H:%M:%S"),
        "epoch_start_ist": reset_dt_ist.strftime("%H:%M:%S"),
        "reset_utc": reset_dt_utc.strftime("%H:%M:%S"),
        "reset_ist": reset_dt_ist.strftime("%H:%M:%S"),
        "epoch_duration": epoch_duration,
        "block_rate_sec": round(block_sec, 4) if block_sec else None,
    }
    
    state.setdefault("history", []).append(entry)


def record_manual_set(state, entered_block, current_block, start_block, reset_block, set_time, block_sec=None):
    """Record manual epoch set with timestamp."""
    if block_sec is None:
        block_sec = state.get("last_block_sec", AVG_BLOCK_TIME)
    
    epoch_no = start_block // BLOCKS_PER_EPOCH
    set_time_utc = set_time.astimezone(UTC)
    
    entry = {
        "kind": "manual_set",
        "epoch_no": epoch_no,
        "date": set_time.strftime("%Y-%m-%d"),
        "entered_block": entered_block,
        "current_block": current_block,
        "epoch_start_block": start_block,
        "reset_block": reset_block,
        "set_timestamp": int(set_time_utc.timestamp()),
        "epoch_start_utc": set_time_utc.strftime("%H:%M:%S"),
        "epoch_start_ist": set_time.strftime("%H:%M:%S"),
        "reset_utc": set_time_utc.strftime("%H:%M:%S"),
        "reset_ist": set_time.strftime("%H:%M:%S"),
        "epoch_duration": epoch_duration_text(block_sec),
        "block_rate_sec": round(block_sec, 4) if block_sec else None,
    }
    
    state.setdefault("history", []).append(entry)


def calculate_epoch_stats(state, current_block, block_sec=None):
    """Calculate epoch statistics using smart block rate."""
    if block_sec is None:
        block_sec = state.get("last_block_sec", AVG_BLOCK_TIME)
    
    start_block = state["start_block"]
    elapsed = current_block - start_block
    remaining = BLOCKS_PER_EPOCH - elapsed
    progress = (elapsed / BLOCKS_PER_EPOCH) * 100
    
    remaining_sec = remaining * block_sec
    
    if elapsed < TIER_1_END:
        tier = 1
        tier_elapsed = elapsed
        tier_total = TIER_1_END
    elif elapsed < TIER_2_END:
        tier = 2
        tier_elapsed = elapsed - TIER_1_END
        tier_total = TIER_2_END - TIER_1_END
    else:
        tier = 3
        tier_elapsed = elapsed - TIER_2_END
        tier_total = BLOCKS_PER_EPOCH - TIER_2_END
    
    tier_progress = (tier_elapsed / tier_total) * 100
    
    return {
        "start_block": start_block,
        "elapsed": elapsed,
        "remaining": remaining_sec,
        "progress": progress,
        "tier": tier,
        "tier_progress": tier_progress,
        "block_sec": block_sec,
    }


def format_duration_seconds(seconds):
    """Format duration from seconds."""
    if seconds is None or seconds < 0:
        return "n/a"
    
    total_sec = int(seconds)
    d = total_sec // 86400
    h = (total_sec % 86400) // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def format_duration(seconds):
    """Format remaining time duration."""
    return format_duration_seconds(seconds)


def epoch_duration_text(block_sec=None):
    """Calculate expected epoch duration."""
    if block_sec is None:
        block_sec = AVG_BLOCK_TIME
    total_sec = BLOCKS_PER_EPOCH * block_sec
    return format_duration_seconds(total_sec)


def build_progress_bar(percent, width=10):
    """Build visual progress bar."""
    safe_pct = max(0, min(100, percent))
    filled = int((safe_pct / 100) * width)
    return f"🔋 {'🟩' * filled}{'⬜' * (width - filled)}"


async def animate_message(chat_id, msg_id, frames, forum=False, delay=0.3):
    """Animate loading messages."""
    for frame in frames:
        try:
            kw = {}
            if forum:
                kw["message_thread_id"] = TARGET_THREAD_ID
            await bot.edit_message_text(
                chat_id=int(chat_id),
                message_id=msg_id,
                text=frame,
                **kw,
            )
            await asyncio.sleep(delay)
        except:
            pass


async def send_dashboard(chat_id, chat_meta, state, current_block, block_sec=None, forum=False):
    """Send comprehensive dashboard with timestamp-based calculations."""
    if block_sec is None:
        block_sec = state.get("last_block_sec", AVG_BLOCK_TIME)
    
    s = calculate_epoch_stats(state, current_block, block_sec=block_sec)
    
    epoch_no = state["start_block"] // BLOCKS_PER_EPOCH
    
    # Get epoch anchor info
    epoch_key = str(epoch_no)
    epoch_anchors = state.get("epoch_anchors", {})
    anchor = epoch_anchors.get(epoch_key)
    
    # Format anchor info
    if anchor:
        anchor_time = datetime.fromtimestamp(anchor["start_timestamp"], IST)
        anchor_info = f"📅 Epoch {epoch_no} started at: {anchor_time.strftime('%Y-%m-%d %H:%M:%S')} IST\n"
        anchor_info += f"   Start Block: {anchor['start_block']:,} (Block #{anchor['start_block']})\n\n"
    else:
        anchor_info = f"📅 Epoch {epoch_no} (Anchor not yet recorded)\n\n"
    
    dash = (
        f"🌐 Epoch Tracker Dashboard\n\n"
        f"{anchor_info}"
        f"📊 Current Status\n"
        f"• Block Height: {current_block:,}\n"
        f"• Block Rate: {block_sec:.4f}s/block\n"
        f"• Epoch Progress: {s['progress']:.1f}%\n"
        f"{build_progress_bar(s['progress'])}\n\n"
        f"⏱️ Timing\n"
        f"• Elapsed: {s['elapsed']:,} blocks\n"
        f"• Remaining: {s['remaining'] / block_sec:,.0f} blocks\n"
        f"• Time to Reset: {format_duration(s['remaining'])}\n\n"
        f"🎯 Tier {s['tier']} Status\n"
        f"• Tier Progress: {s['tier_progress']:.1f}%\n"
        f"{build_progress_bar(s['tier_progress'])}\n\n"
        f"📈 Epoch Info\n"
        f"• Start Block: {s['start_block']:,}\n"
        f"• Reset Block: {s['start_block'] + BLOCKS_PER_EPOCH:,}\n"
        f"• Expected Duration: {epoch_duration_text(block_sec)}\n"
    )
    
    await send_text(chat_id, dash, forum=forum)


async def handle(update: Update):
    """Main message handler with smart block tracking."""
    msg = update.message or update.edited_message
    if not msg or not msg.text:
        return

    text = msg.text.strip()
    low = text.lower()
    chat = str(msg.chat_id)
    user_id = str(msg.from_user.id)
    forum = msg.is_topic_message

    store, sha = await load_data_async()
    global_state = get_global_state(store)
    chat_meta = get_chat_meta(store, chat)

    if low in ["/start", "🔄 refresh", "/status", "📊 status"]:
        # Fetch live block data with timestamps
        block_task = asyncio.create_task(get_live_block_snapshot())

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        await animate_message(
            chat,
            loading_msg.message_id,
            ["📡 Connecting to blockchain...", "🔄 Syncing epoch data...", "✅ Processing timestamps..."],
            forum=forum,
            delay=0.2,
        )

        snapshot = await block_task
        current_block = snapshot["currentHeight"]
        current_timestamp = snapshot["currentTimestamp"]
        block_sec = snapshot.get("sampleBlockSec") or global_state.get("last_block_sec") or AVG_BLOCK_TIME
        
        # Update stored block rate
        global_state["last_block_sec"] = block_sec

        # Sync with timestamp tracking
        sync_epoch_state(global_state, current_block, current_timestamp, block_sec=block_sec)

        if low == "/start" and not chat_meta.get("seen_start"):
            await send_text(chat, "👋 Welcome to Smart Epoch Tracker!", forum=forum)
            chat_meta["seen_start"] = True

        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        await send_dashboard(chat, chat_meta, global_state, current_block, block_sec=block_sec, forum=forum)

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)
        return

    if low in ["/blocks", "🔺 block height"]:
        block_task = asyncio.create_task(get_live_block_snapshot())

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        await animate_message(
            chat,
            loading_msg.message_id,
            ["📡 Connecting to blockchain...", "🔍 Fetching data...", "📖 Reading block height..."],
            forum=forum,
            delay=0.2,
        )

        snapshot = await block_task
        b = snapshot["currentHeight"]
        ts = snapshot["currentTimestamp"]
        block_time = datetime.fromtimestamp(ts, IST)

        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        if b is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
        else:
            response = (
                f"📦 Current Block Info\n\n"
                f"• Block Height: {b:,}\n"
                f"• Timestamp: {block_time.strftime('%Y-%m-%d %H:%M:%S')} IST\n"
                f"• Block Rate: {snapshot.get('sampleBlockSec', 0):.4f}s/block"
            )
            await send_text(chat, response, forum=forum)
        return

    if low in ["/help", "ℹ️ help"]:
        help_text = (
            "🧭 Smart Epoch Tracker Commands\n\n"
            "📊 /status - Update Dashboard (with timestamps)\n"
            "📦 /blocks - Show Block Height & Timestamp\n"
            "📈 /analysis - Show Epoch History Reports\n"
            "ℹ️ /help - Show This Help\n\n"
            "✨ Features:\n"
            "• Smart block rate calculation\n"
            "• Timestamp-based epoch tracking\n"
            "• Accurate duration estimates\n"
            "• Auto-detection of epoch resets"
        )
        await send_text(chat, help_text, forum=forum)
        return

    if low == "/pin":
        snapshot = await get_live_block_snapshot()
        current_block = snapshot["currentHeight"]
        current_timestamp = snapshot["currentTimestamp"]
        block_sec = snapshot.get("sampleBlockSec") or global_state.get("last_block_sec") or AVG_BLOCK_TIME
        global_state["last_block_sec"] = block_sec

        sync_epoch_state(global_state, current_block, current_timestamp, block_sec=block_sec)
        s = calculate_epoch_stats(global_state, current_block, block_sec=block_sec)

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

        snapshot = await get_live_block_snapshot()
        current_block = snapshot["currentHeight"]
        current_timestamp = snapshot["currentTimestamp"]
        block_sec = snapshot.get("sampleBlockSec") or global_state.get("last_block_sec") or AVG_BLOCK_TIME
        global_state["last_block_sec"] = block_sec

        now_ist = datetime.now(IST)

        if entered_block > current_block:
            start_block = entered_block - BLOCKS_PER_EPOCH
            reset_block = entered_block
        else:
            start_block = entered_block
            reset_block = entered_block + BLOCKS_PER_EPOCH

        global_state["start_block"] = start_block
        global_state["epoch_start_ts"] = int(now_ist.timestamp())
        record_manual_set(global_state, entered_block, current_block, start_block, reset_block, now_ist, block_sec=block_sec)

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

        snapshot = await get_live_block_snapshot()
        current_block = snapshot["currentHeight"]
        current_timestamp = snapshot["currentTimestamp"]
        block_sec = snapshot.get("sampleBlockSec") or global_state.get("last_block_sec") or AVG_BLOCK_TIME
        global_state["last_block_sec"] = block_sec

        sync_epoch_state(global_state, current_block, current_timestamp, block_sec=block_sec)

        hist = global_state.get("history", [])
        if not hist:
            try:
                await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
            except:
                pass
            await send_text(chat, "📊 No epoch records yet.", forum=forum)
            return

        out = "📊 Epoch History Report\n"
        out += "━" * 40 + "\n\n"
        
        # Show epoch anchors
        epoch_anchors = global_state.get("epoch_anchors", {})
        if epoch_anchors:
            out += "🔗 Tracked Epoch Anchors:\n"
            for epoch_key in sorted(epoch_anchors.keys(), key=int):
                anchor = epoch_anchors[epoch_key]
                anchor_time = datetime.fromtimestamp(anchor["start_timestamp"], IST)
                out += (
                    f"  Epoch {anchor['epoch_index']}: Block {anchor['start_block']:,}\n"
                    f"  Started: {anchor_time.strftime('%Y-%m-%d %H:%M:%S')} IST\n\n"
                )
            out += "━" * 40 + "\n\n"
        
        for h in hist[-30:]:
            kind = h.get("kind", "manual_set")
            epoch_no = h.get("epoch_no", 202)
            
            if kind == "auto_reset":
                # For known epoch anchors, show exact timing
                if epoch_no in EPOCH_ANCHORS:
                    out += f"📅 Epoch {epoch_no} | Auto Reset ✓\n"
                    out += f"🔗 Reset at Block: {EPOCH_ANCHORS[epoch_no]:,}\n"
                else:
                    out += f"📅 Epoch {epoch_no} | Auto Reset\n"
                
                out += (
                    f"• Start Block: {h['epoch_start_block']:,}\n"
                    f"• Start Time: {h['date']} {h['epoch_start_ist']} IST\n"
                    f"• Reset Block: {h['reset_block']:,}\n"
                    f"• Reset Time: {h['date']} {h['reset_ist']} IST\n"
                    f"• Epoch Duration: {h.get('epoch_duration', 'n/a')}\n"
                )
                
                if h.get('block_rate_sec'):
                    out += f"• Block Rate: {h['block_rate_sec']:.4f}s/block\n"
                
                out += "\n"
            else:
                out += (
                    f"📅 Epoch {epoch_no} | Manual Set 🔧\n"
                    f"• Start Block: {h['epoch_start_block']:,}\n"
                    f"• Start Time: {h['date']} {h['epoch_start_ist']} IST\n"
                    f"• Reset Block: {h['reset_block']:,}\n"
                    f"• Reset Time: {h['date']} {h['reset_ist']} IST\n"
                    f"• Epoch Duration: {h.get('epoch_duration', 'n/a')}\n"
                )
                
                if h.get('block_rate_sec'):
                    out += f"• Block Rate: {h['block_rate_sec']:.4f}s/block\n"
                
                out += "\n"

        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)

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
