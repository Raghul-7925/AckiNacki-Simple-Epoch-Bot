import base64
import json
import os
import asyncio
import aiohttp
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen

from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

BOT_TOKEN  = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO  = os.environ.get("GITHUB_REPO")
GITHUB_FILE  = os.environ.get("GITHUB_FILE", "data.json")

OWNER_IDS       = "1837260280"
TARGET_THREAD_ID = 3

bot = Bot(token=BOT_TOKEN)

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc

BLOCKS_PER_EPOCH    = 262_000
ANCHOR_EPOCH = 205                  # known reference epoch
ANCHOR_BLOCK = 53_448_000           # block where epoch 205 starts
MIN_EPOCH    = 1                    # epoch 1 starts at block 0
AVG_BLOCK_TIME = 0.35               # fallback only — never stored

TIER_1_END = BLOCKS_PER_EPOCH // 3
TIER_2_END = (BLOCKS_PER_EPOCH * 2) // 3

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]

# Bot user-IDs allowed to trigger /status (your auto-scheduler bot)
TRUSTED_BOT_IDS = {"8589208931"}

GRAPHQL_URL_PRIMARY  = "https://mainnet.ackinacki.org/graphql"
GRAPHQL_URL_FALLBACK = "https://mainnet-cf.ackinacki.org/graphql"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

DEFAULT_ENDPOINTS    = "mainnet.ackinacki.org,mainnet-cf.ackinacki.org"
DEFAULT_SAMPLE_BLOCKS = 120

# Callback-data constants
CB_UPDATE_DASHBOARD = "update_dashboard"
CB_REFRESH_BLOCKS   = "refresh_blocks"

# ============================================================
# GitHub storage
# ============================================================

def gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
    }


def _sanitize_store(store):
    if not isinstance(store, dict):
        store = {}

    hist = store.get("history", [])
    if not isinstance(hist, list):
        hist = []

    cleaned, seen = [], set()
    for item in hist:
        if not isinstance(item, dict):
            continue
        en = normalize_uint(item.get("epoch_no"))
        if en < MIN_EPOCH or en in seen:
            continue
        seen.add(en)
        cleaned.append(item)

    cleaned.sort(key=lambda x: normalize_uint(x.get("epoch_no")))
    store["history"] = cleaned

    if not isinstance(store.get("chat_pins"), dict):
        store["chat_pins"] = {}

    return store


def load_data():
    try:
        req = Request(GITHUB_API)
        for k, v in gh_headers().items():
            req.add_header(k, v)
        res  = urlopen(req).read()
        data = json.loads(res)
        content = base64.b64decode(data["content"]).decode()
        store   = json.loads(content) if content.strip() else {}
        return _sanitize_store(store), data["sha"]
    except Exception:
        return {"history": [], "chat_pins": {}}, None


def save_data(store, sha):
    store = _sanitize_store(store)
    body  = {
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


# per-chat pin helpers

def get_chat_pins(store, chat):
    pins = store.setdefault("chat_pins", {})
    if not isinstance(pins.get(chat), dict):
        pins[chat] = {"pin_msg_id": None, "dashboard_msg_id": None}
    return pins[chat]


def set_chat_pins(store, chat, *, pin_msg_id=None, dashboard_msg_id=None):
    pins = get_chat_pins(store, chat)
    if pin_msg_id       is not None: pins["pin_msg_id"]       = pin_msg_id
    if dashboard_msg_id is not None: pins["dashboard_msg_id"] = dashboard_msg_id

# ============================================================
# Telegram helpers
# ============================================================

def _update_button():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔃 Update", callback_data=CB_UPDATE_DASHBOARD)]]
    )

def _refresh_button():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Refresh", callback_data=CB_REFRESH_BLOCKS)]]
    )


async def send_text(chat_id, text, forum=False, reply_markup=None):
    kw = {}
    if reply_markup: kw["reply_markup"] = reply_markup
    if forum:        kw["message_thread_id"] = TARGET_THREAD_ID
    return await bot.send_message(int(chat_id), text, **kw)


async def send_chunked(chat_id, text, forum=False):
    if len(text) <= 3900:
        return [await send_text(chat_id, text, forum=forum)]

    chunks, current = [], ""
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

    return [await send_text(chat_id, chunk, forum=forum) for chunk in chunks]


def owner_only(user_id):
    return str(user_id) in OWNER_LIST

# ============================================================
# Configuration / GraphQL helpers
# ============================================================

def env_int(key, fallback):
    raw = os.environ.get(key)
    if raw is None or raw == "":
        return fallback
    try:    return int(raw)
    except: return fallback


def normalize_endpoint(ep):
    t = str(ep or "").strip().rstrip("/")
    if not t: return None
    return t if t.startswith("http") else f"https://{t}"


def build_graphql_urls():
    raw  = os.environ.get("ENDPOINTS", DEFAULT_ENDPOINTS)
    urls, seen = [], set()
    for ep in raw.split(","):
        base = normalize_endpoint(ep)
        if not base: continue
        url = f"{base}/graphql"
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls or [GRAPHQL_URL_PRIMARY, GRAPHQL_URL_FALLBACK]


def normalize_uint(value):
    if value is None: return 0
    if isinstance(value, int):   return value
    if isinstance(value, float): return int(value)
    if isinstance(value, str) and value.strip():
        try:    return int(value)
        except: return 0
    return 0


async def graphql_fetch(query, retries_per_endpoint=2):
    urls, last_err = build_graphql_urls(), None
    for url in urls:
        for i in range(retries_per_endpoint):
            try:
                timeout = aiohttp.ClientTimeout(total=15)
                async with aiohttp.ClientSession() as s:
                    async with s.post(url, json={"query": query}, timeout=timeout) as r:
                        if not r.ok:
                            raise RuntimeError(f"HTTP {r.status} @ {url}")
                        return {"url": url, "json": await r.json()}
            except Exception as e:
                last_err = e
                if i < retries_per_endpoint - 1:
                    await asyncio.sleep(1)
    raise last_err if last_err else RuntimeError("GraphQL failed on all endpoints")


async def get_live_block_snapshot():
    n = max(3, env_int("BLOCK_SAMPLE_BLOCKS", DEFAULT_SAMPLE_BLOCKS))
    query = f"""
    query {{
        blockchain {{
            blocks(last: {n}) {{
                edges {{ node {{ seq_no gen_utime }} }}
            }}
        }}
    }}
    """
    result = await graphql_fetch(query)
    edges  = (
        result.get("json", {}).get("data", {})
        .get("blockchain", {}).get("blocks", {}).get("edges", [])
    )

    parsed = []
    for edge in edges:
        node      = edge.get("node", {}) if isinstance(edge, dict) else {}
        seq_no    = normalize_uint(node.get("seq_no"))
        gen_utime = normalize_uint(node.get("gen_utime"))
        if seq_no > 0:
            parsed.append({"seq_no": seq_no, "gen_utime": gen_utime})

    parsed.sort(key=lambda x: x["seq_no"])
    if not parsed:
        raise RuntimeError("No block height available")

    first, last = parsed[0], parsed[-1]
    sample_block_sec = None
    if (len(parsed) >= 2
            and last["seq_no"]    > first["seq_no"]
            and last["gen_utime"] >= first["gen_utime"]):
        ds = last["seq_no"]    - first["seq_no"]
        dt = last["gen_utime"] - first["gen_utime"]
        if ds > 0 and dt >= 0:
            sample_block_sec = dt / ds

    return {
        "sourceUrl":        result["url"],
        "currentHeight":    last["seq_no"],
        "currentTimestamp": last["gen_utime"],
        "sampleBlockSec":   sample_block_sec,
        "sampleBlocks":     len(parsed),
    }


async def fetch_block_timestamp(block_height):
    """
    Try multiple GraphQL query strategies to get the gen_utime of a
    specific block.  Returns Unix-second timestamp or None.

    Strategy 1: seq_no range filter (precise, may not be supported)
    Strategy 2: workchain filter with a wider window, pick closest match
    Strategy 3: last N blocks anchored near the target (for recent blocks)
    """

    def _best_from_edges(edges, target):
        best, best_dist = None, None
        for edge in edges:
            node = edge.get("node", {}) if isinstance(edge, dict) else {}
            sn   = normalize_uint(node.get("seq_no"))
            ts   = normalize_uint(node.get("gen_utime"))
            if sn > 0 and ts > 0:
                d = abs(sn - target)
                if best_dist is None or d < best_dist:
                    best_dist, best = d, ts
        return best

    # ── Strategy 1: seq_no range ─────────────────────────────────────────
    q1 = f"""
    query {{
        blockchain {{
            blocks(seq_no: {{ start: {block_height}, end: {block_height + 1} }}) {{
                edges {{ node {{ seq_no gen_utime }} }}
            }}
        }}
    }}
    """
    try:
        r1    = await graphql_fetch(q1)
        edges = (r1.get("json", {}).get("data", {})
                   .get("blockchain", {}).get("blocks", {}).get("edges", []))
        ts = _best_from_edges(edges, block_height)
        if ts:
            return ts
    except Exception as e:
        print(f"fetch_block_timestamp S1({block_height}): {e}")

    # ── Strategy 2: wider seq_no window ──────────────────────────────────
    window = 100
    q2 = f"""
    query {{
        blockchain {{
            blocks(seq_no: {{ start: {block_height - window}, end: {block_height + window} }}) {{
                edges {{ node {{ seq_no gen_utime }} }}
            }}
        }}
    }}
    """
    try:
        r2    = await graphql_fetch(q2)
        edges = (r2.get("json", {}).get("data", {})
                   .get("blockchain", {}).get("blocks", {}).get("edges", []))
        ts = _best_from_edges(edges, block_height)
        if ts:
            return ts
    except Exception as e:
        print(f"fetch_block_timestamp S2({block_height}): {e}")

    # ── Strategy 3: workchain=-1 master blocks around target ─────────────
    q3 = f"""
    query {{
        blockchain {{
            blocks(
                filter: {{ workchain_id: {{ eq: -1 }} }}
                seq_no: {{ start: {block_height - 50}, end: {block_height + 50} }}
            ) {{
                edges {{ node {{ seq_no gen_utime }} }}
            }}
        }}
    }}
    """
    try:
        r3    = await graphql_fetch(q3)
        edges = (r3.get("json", {}).get("data", {})
                   .get("blockchain", {}).get("blocks", {}).get("edges", []))
        ts = _best_from_edges(edges, block_height)
        if ts:
            return ts
    except Exception as e:
        print(f"fetch_block_timestamp S3({block_height}): {e}")

    print(f"fetch_block_timestamp: all strategies failed for block {block_height}")
    return None

# ============================================================
# Epoch arithmetic
# ============================================================

def epoch_start_block(epoch_no):
    """Works for any epoch >= MIN_EPOCH, including those before the anchor."""
    return ANCHOR_BLOCK + (epoch_no - ANCHOR_EPOCH) * BLOCKS_PER_EPOCH

def epoch_reset_block(epoch_no):
    return epoch_start_block(epoch_no) + BLOCKS_PER_EPOCH

def epoch_no_from_block(block_height):
    """Derive epoch number from any block height."""
    offset = block_height - ANCHOR_BLOCK
    epoch_no = ANCHOR_EPOCH + (offset // BLOCKS_PER_EPOCH)
    return max(MIN_EPOCH, epoch_no)

def current_epoch_bounds(current_block):
    en    = epoch_no_from_block(current_block)
    start = epoch_start_block(en)
    reset = start + BLOCKS_PER_EPOCH
    return en, start, reset

# ============================================================
# Formatting
# ============================================================

def format_duration(seconds):
    seconds = max(0, int(round(seconds / 60.0) * 60))
    h, m    = seconds // 3600, (seconds % 3600) // 60
    return f"{h}h {m}m" if h else f"{m}m"


def format_blockchain_time(unix_ts):
    dt_utc = datetime.fromtimestamp(unix_ts, UTC)
    dt_ist = dt_utc.astimezone(IST)
    return (
        f"{dt_ist.strftime('%d %b %Y')} | "
        f"{dt_ist.strftime('%I:%M %p')} | "
        f"UTC: {dt_utc.strftime('%H:%M')}"
    )


def reward_tier(in_epoch):
    if in_epoch < TIER_1_END: return "Tier 1 — High Reward  (<6 k taps)"
    if in_epoch < TIER_2_END: return "Tier 2 — Medium Reward (>6 k taps)"
    return                           "Tier 3 — Low Reward   (>12 k taps)"

# ============================================================
# Text builders
# ============================================================

def build_dashboard_text(snapshot):
    cb      = snapshot["currentHeight"]
    cur_ts  = snapshot.get("currentTimestamp") or int(datetime.now(UTC).timestamp())
    blk_sec = snapshot.get("sampleBlockSec") or AVG_BLOCK_TIME

    en, start, reset = current_epoch_bounds(cb)
    done  = max(0, cb - start)
    left  = max(0, reset - cb)
    pct   = done / BLOCKS_PER_EPOCH * 100

    remaining_sec = left * blk_sec
    elapsed_sec   = done * blk_sec
    reset_dt      = datetime.fromtimestamp(cur_ts, UTC) + timedelta(seconds=remaining_sec)
    reset_ist     = reset_dt.astimezone(IST)

    return (
        f"⏳ Timer Since Epoch Reset: {format_duration(elapsed_sec)}\n"
        f"⏱️ Time left to reset: {format_duration(remaining_sec)}\n\n"
        f"📊 Block Progress\n"
        f"• Current Block Height: {cb:,}\n"
        f"• Epoch {en} Reset at: {reset:,}\n"
        f"• Blocks Produced This Epoch: {done:,}\n"
        f"• Blocks Left to Reset: {left:,}\n"
        f"• Progress: {pct:.1f}%\n\n"
        f"🔁 Estimated Reset\n"
        f"• {reset_ist.strftime('%d %b %I:%M %p')} IST  [UTC: {reset_dt.strftime('%H:%M')}]\n\n"
        f"🏆 Reward Tier\n"
        f"• {reward_tier(done)}"
    )


def build_pin_text(snapshot):
    cb      = snapshot["currentHeight"]
    cur_ts  = snapshot.get("currentTimestamp") or int(datetime.now(UTC).timestamp())
    blk_sec = snapshot.get("sampleBlockSec") or AVG_BLOCK_TIME

    _, start, reset = current_epoch_bounds(cb)
    left      = max(0, reset - cb)
    remaining = left * blk_sec
    reset_dt  = datetime.fromtimestamp(cur_ts, UTC) + timedelta(seconds=remaining)
    reset_ist = reset_dt.astimezone(IST)

    return (
        f"⏳ Time to next epoch reset: {format_duration(remaining)}\n"
        f"📌 Est. reset: {reset_ist.strftime('%d %b %I:%M %p')} IST"
    )


def build_blocks_text(snapshot):
    cb     = snapshot["currentHeight"]
    cur_ts = snapshot.get("currentTimestamp") or int(datetime.now(UTC).timestamp())
    dt_utc = datetime.fromtimestamp(cur_ts, UTC)
    dt_ist = dt_utc.astimezone(IST)
    return (
        f"📦 Live Block Height\n"
        f"• Block: {cb:,}\n"
        f"• Time: {dt_ist.strftime('%d %b %I:%M %p')} IST  [UTC: {dt_utc.strftime('%H:%M')}]"
    )

# ============================================================
# Dashboard lifecycle
# ============================================================

async def send_fresh_dashboard(chat, forum, snapshot, store, sha):
    """
    /start: always creates two brand-new messages.
      1. Pinned countdown (plain text, gets pinned)
      2. Dashboard with inline 'Update 🔃' button
    Both IDs saved to GitHub.
    """
    pin_msg  = await send_text(chat, build_pin_text(snapshot), forum=forum)
    try:
        await bot.pin_chat_message(
            chat_id=int(chat),
            message_id=pin_msg.message_id,
            disable_notification=True,
        )
    except Exception as e:
        print(f"pin_chat_message: {e}")

    dash_msg = await send_text(chat, build_dashboard_text(snapshot),
                               forum=forum, reply_markup=_update_button())

    set_chat_pins(store, chat,
                  pin_msg_id=pin_msg.message_id,
                  dashboard_msg_id=dash_msg.message_id)
    await save_data_async(store, sha)


async def _try_edit(chat_id, msg_id, text, reply_markup=None):
    """
    Returns 'ok' | 'deleted' | 'error'
    'message is not modified' → 'ok'  (never triggers a fallback)
    """
    try:
        kw = {"reply_markup": reply_markup} if reply_markup else {}
        await bot.edit_message_text(
            chat_id=int(chat_id),
            message_id=int(msg_id),
            text=text,
            **kw,
        )
        return "ok"
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return "ok"
        if "message to edit not found" in err or "chat not found" in err:
            return "deleted"
        print(f"edit({msg_id}): {e}")
        return "error"
    except Exception as e:
        print(f"edit({msg_id}): {e}")
        return "error"


async def do_dashboard_update(chat, forum, snapshot, store, sha):
    """
    Used by both the inline button and /status.
    Edits the two stored messages in place.
    If either was deleted → tells user to /start.  Never pins or sends new messages.
    """
    pins             = get_chat_pins(store, chat)
    pin_msg_id       = pins.get("pin_msg_id")
    dashboard_msg_id = pins.get("dashboard_msg_id")

    if not pin_msg_id or not dashboard_msg_id:
        await send_text(chat, "ℹ️ No dashboard found. Send /start to set it up.", forum=forum)
        return

    pin_res  = await _try_edit(chat, pin_msg_id, build_pin_text(snapshot))
    dash_res = await _try_edit(chat, dashboard_msg_id, build_dashboard_text(snapshot),
                               reply_markup=_update_button())

    if pin_res == "deleted" or dash_res == "deleted":
        await send_text(
            chat,
            "⚠️ Dashboard messages were deleted.\nSend /start to create a fresh one.",
            forum=forum,
        )

# ============================================================
# Command parser — strips @BotUsername suffix
# ============================================================

def parse_command(text: str) -> str:
    """
    '/start@epoch_helper_bot extra args'  →  '/start'
    '/status'                             →  '/status'
    """
    if not text:
        return ""
    first_token = text.strip().split()[0].lower()
    if "@" in first_token:
        first_token = first_token.split("@")[0]
    return first_token

# ============================================================
# Analysis / history helpers
# ============================================================

def find_history_record(store, epoch_no):
    for item in store.get("history", []):
        if normalize_uint(item.get("epoch_no")) == epoch_no:
            return item
    return None


def build_analysis_record(epoch_no, start_ts, reset_ts):
    """
    Build a history record.  Stores partial records when only one
    timestamp is available — never silently discards data.
    Returns None only when BOTH timestamps are missing.
    """
    if not start_ts and not reset_ts:
        return None

    start_fmt    = format_blockchain_time(start_ts) if start_ts else "pending"
    reset_fmt    = format_blockchain_time(reset_ts) if reset_ts else "pending"
    duration     = (
        format_duration(reset_ts - start_ts)
        if start_ts and reset_ts and reset_ts > start_ts
        else "pending"
    )

    return {
        "kind":            "auto_reset",
        "epoch_no":        epoch_no,
        "start_block":     epoch_start_block(epoch_no),
        "reset_block":     epoch_reset_block(epoch_no),
        "start_timestamp": start_ts,
        "reset_timestamp": reset_ts,
        "start_fmt":       start_fmt,
        "reset_fmt":       reset_fmt,
        "epoch_duration":  duration,
    }


async def build_epoch_record(epoch_no):
    if epoch_no < MIN_EPOCH:
        return None
    start_ts, reset_ts = await asyncio.gather(
        fetch_block_timestamp(epoch_start_block(epoch_no)),
        fetch_block_timestamp(epoch_reset_block(epoch_no)),
    )
    return build_analysis_record(epoch_no, start_ts, reset_ts)


async def ensure_history_upto_current(store, current_block):
    if not isinstance(store.get("history"), list):
        store["history"] = []

    existing  = {normalize_uint(x.get("epoch_no")) for x in store["history"] if isinstance(x, dict)}
    current_epoch = epoch_no_from_block(current_block)
    last_done     = current_epoch - 1   # epochs fully completed

    if last_done < MIN_EPOCH:
        return False

    changed = False
    for en in range(MIN_EPOCH, last_done + 1):
        if en in existing:
            continue
        rec = await build_epoch_record(en)
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
        out += (
            f"📅 Epoch {h.get('epoch_no','?')} | Auto Reset\n"
            f"• Start Block: {h.get('start_block',0):,}\n"
            f"• Start Time: {h.get('start_fmt','pending')}\n"
            f"• Reset Block: {h.get('reset_block',0):,}\n"
            f"• Reset Time: {h.get('reset_fmt','pending')}\n"
            f"• Epoch Duration: {h.get('epoch_duration','pending')}\n\n"
        )
    return out.rstrip()


def build_epoch_report(rec):
    if not rec:
        return None
    return (
        f"📅 Epoch {rec.get('epoch_no','?')} | Auto Reset\n"
        f"• Start Block: {rec.get('start_block',0):,}\n"
        f"• Start Time: {rec.get('start_fmt','pending')}\n"
        f"• Reset Block: {rec.get('reset_block',0):,}\n"
        f"• Reset Time: {rec.get('reset_fmt','pending')}\n"
        f"• Epoch Duration: {rec.get('epoch_duration','pending')}"
    )

# ============================================================
# Loading animation
# ============================================================

async def loading_flow(chat, forum, stages, awaitable, delay=0.45):
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
        return await task
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

    user_id   = str(update.effective_user.id)
    chat      = str(update.effective_chat.id)
    forum     = bool(getattr(update.effective_chat, "is_forum", False))
    is_bot_sender = getattr(update.effective_user, "is_bot", False)

    # Trusted scheduler bots: only allow /status, ignore everything else
    if is_bot_sender:
        if user_id not in TRUSTED_BOT_IDS:
            return  # ignore all other bots completely
        # Trusted bot — handle /status below, skip all other logic
        if update.message:
            cmd = parse_command((update.message.text or "").strip())
            if cmd == "/status":
                snapshot = await get_live_block_snapshot()
                store, sha = await load_data_async()
                await do_dashboard_update(chat, forum, snapshot, store, sha)
            return  # trusted bot only gets /status, nothing else
        return

    # Check if it's a private DM (not a group/supergroup/channel)
    chat_type     = update.effective_chat.type
    is_private_dm = (chat_type == "private")

    # In DM: only allow owner, redirect others to group
    if is_private_dm and user_id not in OWNER_LIST:
        try:
            await bot.send_message(
                int(chat),
                "👋 Hi! This bot is private in DM.\n\n"
                "Please join our group to use it:\n"
                "https://t.me/acki_nacki_popit"
            )
        except Exception:
            pass
        return

    # ── Inline button callbacks ──────────────────────────────────────────────
    if update.callback_query:
        cq   = update.callback_query
        data = cq.data or ""

        # 🔃 Update button on dashboard
        if data == CB_UPDATE_DASHBOARD:
            # Show animated popup notifications
            stages = [
                "📡 Connecting to blockchain…",
                "🔍 Fetching data…",
                "⚙️ Processing data…",
                "🔄 Updating dashboard…"
            ]
            
            # Start fetching in background
            async def fetch_and_load():
                return await get_live_block_snapshot(), await load_data_async()
            
            task = asyncio.create_task(fetch_and_load())
            
            # Animate through popup stages
            for stage in stages:
                try:
                    await cq.answer(stage, show_alert=False)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
            
            # Get the data
            snapshot, (store, sha) = await task
            
            # Update dashboard
            await do_dashboard_update(chat, forum, snapshot, store, sha)
            return

        # 🔄 Refresh button on /blocks message
        if data == CB_REFRESH_BLOCKS:
            # Show animated popup notifications
            stages = [
                "📡 Connecting to blockchain…",
                "🔍 Fetching block data…",
                "📊 Updating…"
            ]
            
            # Start fetching in background
            task = asyncio.create_task(get_live_block_snapshot())
            
            # Animate through popup stages
            for stage in stages:
                try:
                    await cq.answer(stage, show_alert=False)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
            
            # Get the data
            snapshot = await task
            
            # Update with final block data
            try:
                await bot.edit_message_text(
                    chat_id=int(chat),
                    message_id=cq.message.message_id,
                    text=build_blocks_text(snapshot),
                    reply_markup=_refresh_button(),
                )
            except BadRequest as e:
                if "message is not modified" not in str(e).lower():
                    print(f"refresh_blocks edit: {e}")
            return

        return  # unknown callback

    # ── Text / command messages ──────────────────────────────────────────────
    if not update.message:
        return

    raw_text = (update.message.text or "").strip()
    cmd      = parse_command(raw_text)  # '/start@BotName args' → '/start'

    # /start — always sends two fresh messages + pins the first
    if cmd == "/start":
        snapshot = await loading_flow(
            chat, forum,
            ["📡 Connecting to blockchain…", "🔄 Initialising…", "✅ Ready!"],
            get_live_block_snapshot(),
        )
        store, sha = await load_data_async()
        await send_fresh_dashboard(chat, forum, snapshot, store, sha)
        return

    # /status — edits the two stored messages, never sends new ones
    if cmd == "/status":
        snapshot = await loading_flow(
            chat, forum,
            ["📡 Connecting to blockchain…", "🔍 Fetching live data…", "🔄 Updating dashboard…"],
            get_live_block_snapshot(),
        )
        store, sha = await load_data_async()
        await do_dashboard_update(chat, forum, snapshot, store, sha)
        return

    # /blocks — live block height with 🔄 Refresh inline button
    if cmd == "/blocks":
        snapshot = await loading_flow(
            chat, forum,
            ["📡 Connecting to blockchain…", "🔍 Fetching block height…"],
            get_live_block_snapshot(),
        )
        await send_text(chat, build_blocks_text(snapshot),
                        forum=forum, reply_markup=_refresh_button())
        return

    # /analysis — epoch history (owner only)
    if cmd == "/analysis":
        if not owner_only(user_id):
            return

        async def analysis_job():
            s, sh = await load_data_async()
            snap  = await get_live_block_snapshot()
            if await ensure_history_upto_current(s, snap["currentHeight"]):
                await save_data_async(s, sh)
            return s, snap

        store_snap = await loading_flow(
            chat, forum,
            ["📡 Connecting to blockchain…", "📚 Collecting epoch history…", "📊 Building report…"],
            analysis_job(),
        )
        store, _ = store_snap
        report   = build_analysis_report(store)
        if not report:
            await send_text(chat, "📊 No epoch records yet.", forum=forum)
        else:
            await send_chunked(chat, report, forum=forum)
        return

    # /epoch <no> — single epoch exact report (owner only)
    if cmd == "/epoch":
        if not owner_only(user_id):
            return

        parts = raw_text.split()
        if len(parts) < 2:
            await send_text(chat, "❌ Usage: /epoch 205", forum=forum)
            return
        try:
            epoch_no = int(parts[1])
        except Exception:
            await send_text(chat, "❌ Invalid epoch number.", forum=forum)
            return
        if epoch_no < MIN_EPOCH:
            await send_text(chat, f"❌ Epoch number must be {MIN_EPOCH} or higher.", forum=forum)
            return

        async def epoch_job():
            s, sh = await load_data_async()
            rec   = find_history_record(s, epoch_no)
            if rec is None:
                rec = await build_epoch_record(epoch_no)
                if rec:
                    s["history"].append(rec)
                    s["history"].sort(key=lambda x: normalize_uint(x.get("epoch_no")))
                    await save_data_async(s, sh)
            return rec

        rec = await loading_flow(
            chat, forum,
            [f"🔎 Loading Epoch {epoch_no}…", "📡 Fetching block timestamps…", "📖 Building report…"],
            epoch_job(),
        )
        if not rec:
            await send_text(
                chat,
                f"⚠️ Could not fetch timestamps for Epoch {epoch_no} from the blockchain.\n"
                f"• Start Block: {epoch_start_block(epoch_no):,}\n"
                f"• Reset Block: {epoch_reset_block(epoch_no):,}\n"
                f"Timestamps unavailable — the node may not index this range.",
                forum=forum,
            )
            return
        await send_text(chat, build_epoch_report(rec), forum=forum)
        return

    # /help
    if cmd == "/help":
        await send_text(chat, (
            "🧭 Bot Commands\n\n"
            "▶️ /start      — Pinned countdown + dashboard with Update button\n"
            "📊 /status    — Edit dashboard & pin in place\n"
            "📦 /blocks    — Live block height with Refresh button\n"
            "📈 /analysis  — Full epoch history (all epochs)\n"
            "🔎 /epoch 205 — Exact report for a single epoch\n"
            "ℹ️ /help      — Show this help\n\n"
            "💡 All commands work with @BotUsername suffix in groups.\n"
            "   e.g. /start@epoch_helper_bot"
        ), forum=forum)
        return

# ============================================================
# ASGI entry point
# ============================================================

async def app(scope, receive, send):
    if scope["type"] != "http":
        return

    body, more = b"", True
    while more:
        m     = await receive()
        body += m.get("body", b"")
        more  = m.get("more_body", False)

    try:
        data   = json.loads(body.decode())
        update = Update.de_json(data, bot)
        await handle(update)
    except Exception as e:
        print(e)

    await send({"type": "http.response.start", "status": 200})
    await send({"type": "http.response.body",  "body": b"ok"})
