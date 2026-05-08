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
HISTORY_START_EPOCH = 205
HISTORY_START_BLOCK = 53_448_000  # Epoch 205 start block

AVG_BLOCK_TIME = 0.35  # fallback only — not stored

TIER_1_END = BLOCKS_PER_EPOCH // 3
TIER_2_END = (BLOCKS_PER_EPOCH * 2) // 3

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]

GRAPHQL_URL_PRIMARY = "https://mainnet.ackinacki.org/graphql"
GRAPHQL_URL_FALLBACK = "https://mainnet-cf.ackinacki.org/graphql"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

DEFAULT_ENDPOINTS = "mainnet.ackinacki.org,mainnet-cf.ackinacki.org"
DEFAULT_SAMPLE_BLOCKS = 120

# ============================================================
# GitHub storage helpers
# ============================================================
# The GitHub JSON now has this shape:
#
#   {
#     "history": [ ... epoch records ... ],
#     "chat_pins": {
#       "<chat_id>": {
#         "pin_msg_id":       <int>,   # pinned countdown message id
#         "dashboard_msg_id": <int>    # dashboard message id
#       }
#     }
#   }
#
# Both message IDs are written to GitHub so they survive server restarts.
# /start always creates fresh messages and overwrites the stored IDs.
# /status always tries to EDIT those two messages; if the edit fails
# (message deleted), it falls back to send+pin and stores the new IDs.
# ============================================================

def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _sanitize_store(store):
    """Ensure the store has the correct top-level shape."""
    if not isinstance(store, dict):
        store = {}

    # --- history ---
    hist = store.get("history", [])
    if not isinstance(hist, list):
        hist = []

    cleaned = []
    seen = set()
    for item in hist:
        if not isinstance(item, dict):
            continue
        epoch_no = normalize_uint(item.get("epoch_no"))
        if epoch_no < HISTORY_START_EPOCH:
            continue
        if epoch_no in seen:
            continue
        seen.add(epoch_no)
        cleaned.append(item)

    cleaned.sort(key=lambda x: normalize_uint(x.get("epoch_no")))
    store["history"] = cleaned

    # --- chat_pins ---
    if not isinstance(store.get("chat_pins"), dict):
        store["chat_pins"] = {}

    return store


def load_data():
    try:
        req = Request(GITHUB_API)
        for k, v in gh_headers().items():
            req.add_header(k, v)
        res = urlopen(req).read()
        data = json.loads(res)
        content = base64.b64decode(data["content"]).decode()
        store = json.loads(content) if content.strip() else {}
        return _sanitize_store(store), data["sha"]
    except Exception:
        return {"history": [], "chat_pins": {}}, None


def save_data(store, sha):
    store = _sanitize_store(store)
    body = {
        "message": "update",
        "content": base64.b64encode(json.dumps(store, indent=2).encode()).decode(),
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


# ---- per-chat pin helpers ----

def get_chat_pins(store, chat):
    """Return the pin dict for this chat (mutates store in place)."""
    pins = store.setdefault("chat_pins", {})
    if not isinstance(pins.get(chat), dict):
        pins[chat] = {"pin_msg_id": None, "dashboard_msg_id": None}
    return pins[chat]


def set_chat_pins(store, chat, pin_msg_id=None, dashboard_msg_id=None):
    pins = get_chat_pins(store, chat)
    if pin_msg_id is not None:
        pins["pin_msg_id"] = pin_msg_id
    if dashboard_msg_id is not None:
        pins["dashboard_msg_id"] = dashboard_msg_id

# ============================================================
# Telegram helpers
# ============================================================

async def send_text(chat_id, text, forum=False):
    kw = {"reply_markup": ReplyKeyboardRemove()}
    if forum:
        kw["message_thread_id"] = TARGET_THREAD_ID
    return await bot.send_message(int(chat_id), text, **kw)


async def send_chunked(chat_id, text, forum=False):
    if len(text) <= 3900:
        return [await send_text(chat_id, text, forum=forum)]

    chunks = []
    current = ""

    for paragraph in text.split("\n\n"):
        piece = paragraph.strip()
        if not piece:
            continue
        piece += "\n\n"

        if len(current) + len(piece) > 3900 and current:
            chunks.append(current.rstrip())
            current = piece
        else:
            current += piece

    if current.strip():
        chunks.append(current.rstrip())

    msgs = []
    for chunk in chunks:
        msgs.append(await send_text(chat_id, chunk, forum=forum))
    return msgs


def owner_only(user_id):
    return str(user_id) in OWNER_LIST

# ============================================================
# Configuration helpers
# ============================================================

def env_int(key, fallback):
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return fallback
    try:
        return int(raw)
    except Exception:
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
        except Exception:
            return 0
    return 0

# ============================================================
# GraphQL / blockchain helpers
# ============================================================

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
    }


async def fetch_block_timestamp(block_height):
    query = f"""
    query {{
        blockchain {{
            blocks(seq_no: {{
                start: {block_height},
                end: {block_height + 1}
            }}) {{
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
    try:
        result = await graphql_fetch(query)
        edges = (
            result.get("json", {})
            .get("data", {})
            .get("blockchain", {})
            .get("blocks", {})
            .get("edges", [])
        )
        best = None
        best_dist = None
        for edge in edges:
            node = edge.get("node", {})
            sn = normalize_uint(node.get("seq_no"))
            ts = normalize_uint(node.get("gen_utime"))
            if sn > 0 and ts > 0:
                dist = abs(sn - block_height)
                if best_dist is None or dist < best_dist:
                    best_dist = dist
                    best = ts
        return best
    except Exception as e:
        print(f"fetch_block_timestamp({block_height}) error: {e}")
        return None

# ============================================================
# Epoch arithmetic
# ============================================================

def epoch_start_block(epoch_no):
    return HISTORY_START_BLOCK + (epoch_no - HISTORY_START_EPOCH) * BLOCKS_PER_EPOCH


def epoch_reset_block(epoch_no):
    return epoch_start_block(epoch_no) + BLOCKS_PER_EPOCH


def epoch_no_from_block(block_height):
    if block_height < HISTORY_START_BLOCK:
        return HISTORY_START_EPOCH
    return HISTORY_START_EPOCH + ((block_height - HISTORY_START_BLOCK) // BLOCKS_PER_EPOCH)


def current_epoch_start_and_reset(current_block):
    epoch_no = epoch_no_from_block(current_block)
    start_block = epoch_start_block(epoch_no)
    reset_block = start_block + BLOCKS_PER_EPOCH
    return epoch_no, start_block, reset_block

# ============================================================
# Formatting helpers
# ============================================================

def format_duration(seconds):
    seconds = max(0, int(round(seconds / 60.0) * 60))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def format_blockchain_time(unix_ts):
    dt_utc = datetime.fromtimestamp(unix_ts, UTC)
    dt_ist = dt_utc.astimezone(IST)
    return (
        f"{dt_ist.strftime('%d %b %Y')} | "
        f"{dt_ist.strftime('%I:%M %p')} | "
        f"UTC: {dt_utc.strftime('%H:%M')}"
    )


def get_current_reward_tier(in_epoch):
    if in_epoch < TIER_1_END:
        return "Tier 1 - High Reward (<6k taps)"
    if in_epoch < TIER_2_END:
        return "Tier 2 - Medium Reward (>6k taps)"
    return "Tier 3 - Low Reward( > 12k taps)"

# ============================================================
# Dashboard text builders
# ============================================================

def build_dashboard_text(snapshot):
    current_block = snapshot["currentHeight"]
    current_ts = snapshot.get("currentTimestamp") or int(datetime.now(UTC).timestamp())
    block_sec = snapshot.get("sampleBlockSec") or AVG_BLOCK_TIME

    epoch_no, start_block, reset_block = current_epoch_start_and_reset(current_block)
    blocks_done = max(0, current_block - start_block)
    blocks_left = max(0, reset_block - current_block)
    pct = (blocks_done / BLOCKS_PER_EPOCH) * 100 if BLOCKS_PER_EPOCH else 0.0

    elapsed_sec = blocks_done * block_sec
    remaining_sec = blocks_left * block_sec
    reset_dt = datetime.fromtimestamp(current_ts, UTC) + timedelta(seconds=remaining_sec)
    reset_ist = reset_dt.astimezone(IST)

    return (
        f"⏳ Timer Since Epoch Reset: {format_duration(elapsed_sec)}\n"
        f"⏱️ Time left to reset: {format_duration(remaining_sec)}\n\n"
        f"📊 Block Progress\n"
        f"• Current Block Height: {current_block:,}\n"
        f"• Epoch {epoch_no} Reset at: {reset_block:,}\n"
        f"• Blocks Produced This Epoch: {blocks_done:,}\n"
        f"• Blocks Left to Reset: {blocks_left:,}\n"
        f"• Progress: {pct:.1f}%\n\n"
        f"🔁 Estimated Reset\n"
        f"• {reset_ist.strftime('%d %b %I:%M %p')} IST [UTC: {reset_dt.strftime('%H:%M')}]\n\n"
        f"🏆 Current Reward Tier\n"
        f"• {get_current_reward_tier(blocks_done)}"
    )


def build_pin_text(snapshot):
    current_block = snapshot["currentHeight"]
    current_ts = snapshot.get("currentTimestamp") or int(datetime.now(UTC).timestamp())
    block_sec = snapshot.get("sampleBlockSec") or AVG_BLOCK_TIME

    _, start_block, reset_block = current_epoch_start_and_reset(current_block)
    blocks_left = max(0, reset_block - current_block)
    remaining_sec = blocks_left * block_sec
    reset_dt = datetime.fromtimestamp(current_ts, UTC) + timedelta(seconds=remaining_sec)
    reset_ist = reset_dt.astimezone(IST)

    return (
        f"⏳ Time to next epoch reset: {format_duration(remaining_sec)}\n"
        f"📌 Est. reset: {reset_ist.strftime('%d %b %I:%M %p')} IST"
    )

# ============================================================
# Two-message dashboard: send fresh or edit existing
# ============================================================

async def send_fresh_dashboard(chat, forum, snapshot, store, sha):
    """
    Send two brand-new messages (pin countdown + dashboard),
    pin the first one, and persist both IDs to GitHub.
    Called by /start or as fallback when edits fail.
    """
    pin_text = build_pin_text(snapshot)
    dashboard_text = build_dashboard_text(snapshot)

    # Send pin message first, then pin it
    pin_msg = await send_text(chat, pin_text, forum=forum)
    try:
        await bot.pin_chat_message(
            chat_id=int(chat),
            message_id=pin_msg.message_id,
            disable_notification=True,
        )
    except Exception as e:
        print(f"pin_chat_message error: {e}")

    # Send dashboard message
    dashboard_msg = await send_text(chat, dashboard_text, forum=forum)

    # Persist both IDs
    set_chat_pins(store, chat,
                  pin_msg_id=pin_msg.message_id,
                  dashboard_msg_id=dashboard_msg.message_id)
    await save_data_async(store, sha)

    return pin_msg.message_id, dashboard_msg.message_id


def _edit_failed_hard(exc: Exception) -> bool:
    """
    Return True only when the edit failed because the message no longer
    exists (deleted).  Telegram returns error 400 with 'message to edit
    not found' in that case.

    'Message is not modified' is NOT a hard failure — the text is just
    identical to the current one, which is fine.  We treat it as success
    so we never fall back to sending a new message.
    """
    msg = str(exc).lower()
    if "message is not modified" in msg:
        return False          # harmless — text unchanged, message still there
    if "message to edit not found" in msg:
        return True           # message was deleted
    if "chat not found" in msg:
        return True
    # For any other unexpected error treat as soft — do NOT spam the chat
    return False


async def update_dashboard(chat, forum, snapshot, store, sha):
    """
    Edit the two pinned/dashboard messages in place.

    Rules:
    - NEVER sends a new message, NEVER pins anything.
    - Only falls back to send_fresh_dashboard when a message was actually
      deleted (hard failure).  'Message not modified' is silently ignored.
    - If no IDs are stored yet (first run after deploy), tell the user to
      send /start instead of spamming the group.
    """
    pins = get_chat_pins(store, chat)
    pin_msg_id = pins.get("pin_msg_id")
    dashboard_msg_id = pins.get("dashboard_msg_id")

    # No IDs stored — bot has never done /start in this chat.
    # Do NOT create new messages; just silently return.
    # (The loading animation message was already deleted by loading_flow.)
    if not pin_msg_id or not dashboard_msg_id:
        await send_text(
            chat,
            "ℹ️ No dashboard found. Send /start once to set it up.",
            forum=forum,
        )
        return

    pin_text = build_pin_text(snapshot)
    dashboard_text = build_dashboard_text(snapshot)

    pin_hard_fail = False
    dash_hard_fail = False

    # --- edit pin message ---
    try:
        await bot.edit_message_text(
            chat_id=int(chat),
            message_id=int(pin_msg_id),
            text=pin_text,
        )
    except Exception as e:
        print(f"edit pin ({pin_msg_id}): {e}")
        pin_hard_fail = _edit_failed_hard(e)

    # --- edit dashboard message ---
    try:
        await bot.edit_message_text(
            chat_id=int(chat),
            message_id=int(dashboard_msg_id),
            text=dashboard_text,
        )
    except Exception as e:
        print(f"edit dashboard ({dashboard_msg_id}): {e}")
        dash_hard_fail = _edit_failed_hard(e)

    # Only recreate if a message was actually deleted
    if pin_hard_fail or dash_hard_fail:
        await send_fresh_dashboard(chat, forum, snapshot, store, sha)

# ============================================================
# Analysis history builders
# ============================================================

def find_history_record(store, epoch_no):
    for item in store.get("history", []):
        if normalize_uint(item.get("epoch_no")) == epoch_no:
            return item
    return None


def build_analysis_record(epoch_no, start_ts, reset_ts):
    if not start_ts or not reset_ts or reset_ts <= start_ts:
        return None

    return {
        "kind": "auto_reset",
        "epoch_no": epoch_no,
        "start_block": epoch_start_block(epoch_no),
        "reset_block": epoch_reset_block(epoch_no),
        "start_timestamp": start_ts,
        "reset_timestamp": reset_ts,
        "start_fmt": format_blockchain_time(start_ts),
        "reset_fmt": format_blockchain_time(reset_ts),
        "epoch_duration": format_duration(reset_ts - start_ts),
    }


async def build_epoch_record(epoch_no):
    if epoch_no < HISTORY_START_EPOCH:
        return None

    start_block = epoch_start_block(epoch_no)
    reset_block = epoch_reset_block(epoch_no)

    start_ts, reset_ts = await asyncio.gather(
        fetch_block_timestamp(start_block),
        fetch_block_timestamp(reset_block),
    )

    return build_analysis_record(epoch_no, start_ts, reset_ts)


async def ensure_history_upto_current(store, current_block):
    if "history" not in store or not isinstance(store["history"], list):
        store["history"] = []

    existing = {
        normalize_uint(x.get("epoch_no"))
        for x in store["history"]
        if isinstance(x, dict)
    }

    completed_count = max(0, (current_block - HISTORY_START_BLOCK) // BLOCKS_PER_EPOCH)
    last_completed_epoch = HISTORY_START_EPOCH + completed_count - 1

    if last_completed_epoch < HISTORY_START_EPOCH:
        return False

    changed = False
    for epoch_no in range(HISTORY_START_EPOCH, last_completed_epoch + 1):
        if epoch_no in existing:
            continue
        rec = await build_epoch_record(epoch_no)
        if rec:
            store["history"].append(rec)
            changed = True

    store["history"].sort(key=lambda x: normalize_uint(x.get("epoch_no")))
    return changed


def build_analysis_report(store):
    hist = store.get("history", [])
    if not hist:
        return None

    out = "📊 Daily Epoch History\n\n"
    for h in hist:
        epoch_no = h.get("epoch_no", "?")
        start_block = h.get("start_block", 0)
        reset_block = h.get("reset_block", 0)
        start_fmt = h.get("start_fmt", "pending")
        reset_fmt = h.get("reset_fmt", "pending")
        duration = h.get("epoch_duration", "pending")

        out += f"📅 Epoch {epoch_no} | Auto Reset\n"
        out += f"• Start Block: {start_block:,}\n"
        out += f"• Start Time: {start_fmt}\n"
        out += f"• Reset Block: {reset_block:,}\n"
        out += f"• Reset Time: {reset_fmt}\n"
        out += f"• Epoch Duration: {duration}\n\n"

    return out.rstrip()


def build_epoch_report(record):
    if not record:
        return None

    epoch_no = record.get("epoch_no", "?")
    start_block = record.get("start_block", 0)
    reset_block = record.get("reset_block", 0)
    start_fmt = record.get("start_fmt", "pending")
    reset_fmt = record.get("reset_fmt", "pending")
    duration = record.get("epoch_duration", "pending")

    return (
        f"📅 Epoch {epoch_no} | Auto Reset\n"
        f"• Start Block: {start_block:,}\n"
        f"• Start Time: {start_fmt}\n"
        f"• Reset Block: {reset_block:,}\n"
        f"• Reset Time: {reset_fmt}\n"
        f"• Epoch Duration: {duration}"
    )

# ============================================================
# Loading animation helper
# ============================================================

async def loading_flow(chat, forum, stages, awaitable, delay=0.5):
    loading_msg = await send_text(chat, stages[0], forum=forum)
    task = asyncio.create_task(awaitable)

    try:
        for stage in stages[1:]:
            await asyncio.sleep(delay)
            try:
                await bot.edit_message_text(
                    chat_id=int(chat),
                    message_id=loading_msg.message_id,
                    text=stage,
                )
            except Exception:
                pass

        result = await task
        return result
    finally:
        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except Exception:
            pass

# ============================================================
# Main handler
# ============================================================

async def handle(update: Update):
    if not update.effective_user or not update.effective_chat:
        return

    user_id = str(update.effective_user.id)
    chat = str(update.effective_chat.id)
    forum = bool(getattr(update.effective_chat, "is_forum", False))

    if not update.message:
        return

    text = (update.message.text or "").strip()
    low = text.lower()

    # ── /start ────────────────────────────────────────────────────────────────
    # Always creates two fresh messages (pin + dashboard) and stores their IDs.
    # Users should run /start again if they delete those messages.
    if low in ["/start", "🔄 refresh"]:
        snapshot = await loading_flow(
            chat,
            forum,
            ["📡 Connecting to blockchain...", "🔄 Initializing...", "✅ Ready!"],
            get_live_block_snapshot(),
            delay=0.4,
        )

        store, sha = await load_data_async()
        await send_fresh_dashboard(chat, forum, snapshot, store, sha)
        return

    # ── /status ───────────────────────────────────────────────────────────────
    # Edits the two existing messages. Falls back to fresh if they're gone.
    if low in ["/status", "📊 status"]:
        snapshot = await loading_flow(
            chat,
            forum,
            ["📡 Connecting to blockchain...", "🔍 Fetching live block data...", "🔄 Updating dashboard..."],
            get_live_block_snapshot(),
            delay=0.45,
        )

        store, sha = await load_data_async()
        await update_dashboard(chat, forum, snapshot, store, sha)
        return

    # ── /analysis ─────────────────────────────────────────────────────────────
    if low in ["/analysis", "📈 analysis"]:
        if not owner_only(user_id):
            return

        async def analysis_job():
            store, sha = await load_data_async()
            snapshot = await get_live_block_snapshot()
            changed = await ensure_history_upto_current(store, snapshot["currentHeight"])
            if changed:
                await save_data_async(store, sha)
            return store, snapshot

        store_snapshot = await loading_flow(
            chat,
            forum,
            ["📡 Connecting to blockchain...", "📚 Collecting epoch history...", "📊 Building analysis report..."],
            analysis_job(),
            delay=0.45,
        )

        store, snapshot = store_snapshot
        report = build_analysis_report(store)
        if not report:
            await send_text(chat, "📊 No epoch records yet.", forum=forum)
        else:
            await send_chunked(chat, report, forum=forum)
        return

    # ── /epoch <no> ───────────────────────────────────────────────────────────
    if low.startswith("/epoch"):
        if not owner_only(user_id):
            return

        parts = text.split()
        if len(parts) != 2:
            await send_text(chat, "❌ Usage: /epoch 205", forum=forum)
            return

        try:
            epoch_no = int(parts[1])
        except Exception:
            await send_text(chat, "❌ Invalid epoch number.", forum=forum)
            return

        if epoch_no < HISTORY_START_EPOCH:
            await send_text(chat, "❌ Analysis is available from Epoch 205 onward.", forum=forum)
            return

        async def epoch_job():
            store, sha = await load_data_async()
            record = find_history_record(store, epoch_no)

            if record is None:
                record = await build_epoch_record(epoch_no)
                if record:
                    store["history"].append(record)
                    store["history"].sort(key=lambda x: normalize_uint(x.get("epoch_no")))
                    await save_data_async(store, sha)

            return record

        record = await loading_flow(
            chat,
            forum,
            [f"🔎 Loading Epoch {epoch_no}...", "📡 Fetching exact block timestamps...", "📖 Building report..."],
            epoch_job(),
            delay=0.45,
        )

        if not record:
            await send_text(chat, f"⚠️ Epoch {epoch_no} exact report is not available yet.", forum=forum)
            return

        await send_text(chat, build_epoch_report(record), forum=forum)
        return

    # ── /help ─────────────────────────────────────────────────────────────────
    if low in ["/help", "ℹ️ help"]:
        help_text = (
            "🧭 Bot Commands\n\n"
            "▶️ /start     — Create pinned countdown + dashboard (run again if deleted)\n"
            "📊 /status   — Update pinned countdown + dashboard in place\n"
            "📈 /analysis — Epoch history from Epoch 205 onward\n"
            "🔎 /epoch 205 — Exact report for one epoch\n"
            "ℹ️ /help     — Show this help"
        )
        await send_text(chat, help_text, forum=forum)
        return

    # ── default ───────────────────────────────────────────────────────────────
    await send_text(chat, "👇 Use /start, /status, /analysis, /epoch 205, or /help", forum=forum)


# ============================================================
# ASGI entry point
# ============================================================

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
