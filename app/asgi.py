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

# ---------------------------------------------------------------------------
# EPOCH_RESET_BLOCK is the canonical "start of the current epoch" anchor.
# It is ONLY used to derive epoch numbers and identify which block starts
# which epoch.  Block-height arithmetic takes precedence over any
# time-based estimate.
# ---------------------------------------------------------------------------
EPOCH_RESET_BLOCK = 52_662_000          # epoch 202 start block
EPOCH_202_START_BLOCK = EPOCH_RESET_BLOCK

AVG_BLOCK_TIME = 0.35                   # fallback only — never stored

TIER_1_END = BLOCKS_PER_EPOCH // 3
TIER_2_END = (BLOCKS_PER_EPOCH * 2) // 3

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]

GRAPHQL_URL_PRIMARY = "https://mainnet.ackinacki.org/graphql"
GRAPHQL_URL_FALLBACK = "https://mainnet-cf.ackinacki.org/graphql"

GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

GLOBAL_KEY = "global_epoch_state"
CHAT_META_KEY = "chat_meta"

DEFAULT_ENDPOINTS = "mainnet.ackinacki.org,mainnet-cf.ackinacki.org"
DEFAULT_SAMPLE_BLOCKS = 120

# ============================================================
#  GitHub storage helpers (unchanged)
# ============================================================

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

# ============================================================
#  Telegram helpers (unchanged)
# ============================================================

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

# ============================================================
#  GraphQL / blockchain helpers
# ============================================================

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
    Fetch a recent window of blocks from the blockchain.

    Returns
    -------
    dict with keys:
        sourceUrl        – which endpoint responded
        currentHeight    – highest seq_no seen
        currentTimestamp – gen_utime of that block (Unix seconds, UTC)
        sampleBlockSec   – moving-average seconds-per-block (may be None)
        sampleBlocks     – number of blocks used for the average
        observedAt       – ISO-8601 of currentTimestamp
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

    # Dynamic moving-average block time from actual timestamps
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
        "currentTimestamp": last["gen_utime"],   # Unix seconds, UTC
        "sampleBlockSec": sample_block_sec,
        "sampleBlocks": len(parsed),
        "observedAt": observed_at,
    }


async def fetch_block_timestamp(block_height):
    """
    Fetch the gen_utime of a *specific* block by seq_no.

    Returns the Unix-second timestamp (int) or None on failure.
    The query fetches a tiny window around the target block and picks the
    closest match, because the GraphQL API does not support exact seq_no
    lookup in all deployments.
    """
    query = f"""
    query {{
        blockchain {{
            blocks(
                seq_no: {{
                    start: {block_height},
                    end: {block_height + 1}
                }}
            ) {{
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
#  Epoch-number arithmetic
# ============================================================

def get_epoch_no_from_start(start_block):
    """
    Derive epoch number purely from block height.
    Epoch 202 starts at EPOCH_202_START_BLOCK.
    """
    if start_block <= EPOCH_202_START_BLOCK:
        return 202
    return 202 + ((start_block - EPOCH_202_START_BLOCK) // BLOCKS_PER_EPOCH)


def epoch_start_block(epoch_no):
    """Return the start block of epoch_no."""
    return EPOCH_202_START_BLOCK + (epoch_no - 202) * BLOCKS_PER_EPOCH


def epoch_reset_block(epoch_no):
    """Return the reset block (= start of next epoch) of epoch_no."""
    return epoch_start_block(epoch_no) + BLOCKS_PER_EPOCH

# ============================================================
#  State management helpers
# ============================================================

def ensure_global_defaults(state):
    if "start_block" not in state:
        state["start_block"] = EPOCH_RESET_BLOCK
    if "history" not in state or not isinstance(state["history"], list):
        state["history"] = []
    if "last_block_sec" not in state:
        state["last_block_sec"] = AVG_BLOCK_TIME
    if "epoch_anchors" not in state:
        state["epoch_anchors"] = {}
    # Remove stale fields from old format
    state.pop("msg_id", None)
    state.pop("pin_msg_id", None)
    state.pop("seen_start", None)
    state.pop("epoch_start_ts", None)   # replaced by anchor timestamps


def ensure_chat_defaults(meta):
    if "msg_id" not in meta:
        meta["msg_id"] = None
    if "pin_msg_id" not in meta:
        meta["pin_msg_id"] = None
    if "seen_start" not in meta:
        meta["seen_start"] = False


def choose_global_candidate(store):
    best = None
    best_score = (-1, -1)

    for k, v in store.items():
        if k in (GLOBAL_KEY, CHAT_META_KEY):
            continue
        if isinstance(v, dict) and ("start_block" in v or "history" in v):
            sb = int(v.get("start_block", 0) or 0)
            hl = len(v.get("history", [])) if isinstance(v.get("history"), list) else 0
            score = (sb, hl)
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

# ============================================================
#  Epoch anchor tracking  (exact blockchain timestamps only)
# ============================================================

def record_anchor(state, epoch_no, start_block, start_timestamp):
    """
    Store the exact blockchain gen_utime for the start of an epoch.
    Only recorded from real block timestamps — never from estimates.
    """
    epoch_anchors = state.setdefault("epoch_anchors", {})
    key = str(epoch_no)
    if key not in epoch_anchors and start_timestamp and start_timestamp > 0:
        epoch_anchors[key] = {
            "epoch_no": epoch_no,
            "start_block": start_block,
            "start_timestamp": start_timestamp,
        }


def get_anchor_ts(state, epoch_no):
    """Return the recorded start timestamp of epoch_no, or None."""
    return (
        state.get("epoch_anchors", {})
        .get(str(epoch_no), {})
        .get("start_timestamp")
    )

# ============================================================
#  Formatting helpers
# ============================================================

def format_duration(seconds):
    seconds = max(0, int(round(seconds / 60.0) * 60))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def format_blockchain_time(unix_ts):
    """
    Format a Unix timestamp (UTC) as:
        DD Mon YYYY | HH:MM AM/PM | UTC: HH:MM
    in IST.
    """
    dt_utc = datetime.fromtimestamp(unix_ts, UTC)
    dt_ist = dt_utc.astimezone(IST)
    return (
        f"{dt_ist.strftime('%d %b %Y')} | "
        f"{dt_ist.strftime('%I:%M %p')} | "
        f"UTC: {dt_utc.strftime('%H:%M')}"
    )


def format_time(dt):
    """Legacy helper used by the pin/dashboard — keeps existing output style."""
    return f"{dt.strftime('%d %b %I:%M %p')} IST [UTC: {dt.astimezone(UTC).strftime('%H:%M')}]"


def get_current_reward_tier(in_epoch):
    if in_epoch < TIER_1_END:
        return "Tier 1 - High Reward (<6k taps)"
    if in_epoch < TIER_2_END:
        return "Tier 2 - Medium Reward (>6k taps)"
    return "Tier 3 - Low Reward( > 12k taps)"

# ============================================================
#  Core epoch-state sync
# ============================================================

def _effective_block_sec(state, snapshot_sec=None):
    """
    Pick the best available block time (seconds/block).
    Priority: snapshot moving-average > stored last_block_sec > constant fallback.
    """
    if snapshot_sec and snapshot_sec > 0:
        return snapshot_sec
    stored = state.get("last_block_sec")
    if stored and stored > 0:
        return stored
    return AVG_BLOCK_TIME


async def sync_epoch_state(state, current_block, current_timestamp=None, block_sec=None):
    """
    Advance the epoch state forward as many complete epochs as needed.

    For each completed epoch:
    - Attempts to fetch the *exact* blockchain timestamp of the reset block.
    - Falls back to the live current_timestamp only when the reset block IS
      the current block (i.e. right at the boundary).
    - Never stores estimated times in history.

    Awaitable because fetching exact timestamps requires network calls.
    """
    sec = _effective_block_sec(state, block_sec)

    while True:
        start = int(state["start_block"])
        reset = start + BLOCKS_PER_EPOCH

        if current_block < reset:
            break  # still inside the current epoch

        epoch_no = get_epoch_no_from_start(start)

        # ── Exact start timestamp ──────────────────────────────────
        start_ts = get_anchor_ts(state, epoch_no)
        if not start_ts:
            # Try to fetch it on-chain; may be None for very old blocks
            start_ts = await fetch_block_timestamp(start)
            if start_ts:
                record_anchor(state, epoch_no, start, start_ts)

        # ── Exact reset timestamp ──────────────────────────────────
        if current_block == reset and current_timestamp:
            reset_ts = current_timestamp
        else:
            reset_ts = await fetch_block_timestamp(reset)

        # ── Epoch duration (only when both exact timestamps exist) ─
        if start_ts and reset_ts and reset_ts > start_ts:
            epoch_duration = format_duration(reset_ts - start_ts)
            start_fmt = format_blockchain_time(start_ts)
            reset_fmt = format_blockchain_time(reset_ts)
        elif start_ts:
            # Reset timestamp unavailable — mark as pending
            epoch_duration = "pending"
            start_fmt = format_blockchain_time(start_ts)
            reset_fmt = "pending"
        else:
            epoch_duration = "pending"
            start_fmt = "pending"
            reset_fmt = "pending"

        state["history"].append({
            "kind": "auto_reset",
            "epoch_no": epoch_no,
            "start_block": start,
            "reset_block": reset,
            # Exact blockchain-sourced timestamps (stored as Unix int for reuse)
            "start_timestamp": start_ts,
            "reset_timestamp": reset_ts,
            # Pre-formatted display strings (IST + UTC)
            "start_fmt": start_fmt,
            "reset_fmt": reset_fmt,
            "epoch_duration": epoch_duration,
        })

        state["start_block"] = reset

        # Record anchor for the next epoch using the reset timestamp
        next_epoch_no = get_epoch_no_from_start(reset)
        if reset_ts:
            record_anchor(state, next_epoch_no, reset, reset_ts)

        # Update moving-average block time
        if sec and sec > 0:
            state["last_block_sec"] = sec


def calculate_epoch_stats(state, current_block, block_sec=None):
    """
    Compute live epoch progress using block height + dynamic block rate.

    The estimated reset time is derived ONLY from the moving-average
    block time — it is never stored in history.
    """
    start = int(state["start_block"])
    sec = _effective_block_sec(state, block_sec)

    in_epoch = max(0, current_block - start)
    next_reset = start + BLOCKS_PER_EPOCH
    left = max(0, next_reset - current_block)

    elapsed_sec = in_epoch * sec
    remaining_sec = left * sec

    epoch_no = get_epoch_no_from_start(start)

    # Use exact blockchain anchor for start time when available
    start_ts = get_anchor_ts(state, epoch_no)
    if start_ts:
        epoch_start_dt = datetime.fromtimestamp(start_ts, IST)
    else:
        # Rough estimate for display only (not stored)
        epoch_start_dt = datetime.now(IST) - timedelta(seconds=elapsed_sec)

    reset_dt = datetime.now(IST) + timedelta(seconds=remaining_sec)

    return {
        "epoch_no": epoch_no,
        "current": current_block,
        "in_epoch": in_epoch,
        "next": next_reset,
        "left": left,
        "elapsed_sec": elapsed_sec,
        "remaining_sec": remaining_sec,
        "reset_time": reset_dt,       # estimated — used for display only
        "epoch_start_dt": epoch_start_dt,
        "tier": get_current_reward_tier(in_epoch),
        "pct": (in_epoch / BLOCKS_PER_EPOCH) * 100,
    }

# ============================================================
#  Dashboard / message builders
# ============================================================

async def build_dashboard(global_state, current_block, block_sec=None):
    s = calculate_epoch_stats(global_state, current_block, block_sec=block_sec)

    return (
        f"⏳ Timer Since Epoch Reset: {format_duration(s['elapsed_sec'])}\n"
        f"⏱️ Time left to reset: {format_duration(s['remaining_sec'])}\n\n"

        f"📊 Block Progress\n"
        f"• Current Block Height: {s['current']:,}\n"
        f"• Epoch {s['epoch_no']} Reset at: {s['next']:,}\n"
        f"• Blocks Produced This Epoch: {s['in_epoch']:,}\n"
        f"• Blocks Left to Reset: {s['left']:,}\n"
        f"• Progress: {s['pct']:.1f}%\n\n"

        f"🔁 Estimated Reset\n"
        f"• {format_time(s['reset_time'])}\n\n"

        f"🏆 Current Reward Tier\n"
        f"• {s['tier']}"
    )


def build_analysis_report(global_state, block_sec=None):
    """
    Build the /analysis text.

    Only shows exact blockchain-derived timestamps.
    If a timestamp is missing, it shows 'pending' rather than an estimate.
    """
    hist = global_state.get("history", [])
    if not hist:
        return None

    out = "📊 Epoch History\n\n"
    for h in hist[-30:]:
        kind = h.get("kind", "auto_reset")
        epoch_no = h.get("epoch_no", "?")
        start_block = h.get("start_block", 0)
        reset_block = h.get("reset_block", 0)

        # Prefer pre-formatted strings stored during sync; re-format from
        # stored raw timestamps if the string fields are absent (migration).
        start_ts = h.get("start_timestamp")
        reset_ts = h.get("reset_timestamp")

        start_fmt = h.get("start_fmt") or (
            format_blockchain_time(start_ts) if start_ts else "pending"
        )
        reset_fmt = h.get("reset_fmt") or (
            format_blockchain_time(reset_ts) if reset_ts else "pending"
        )
        duration = h.get("epoch_duration", "pending")

        kind_label = "Auto Reset" if kind == "auto_reset" else "Manual Set"

        out += f"📅 Epoch {epoch_no} | {kind_label}\n"
        out += f"• Start Block: {start_block:,}\n"
        out += f"• Start Time: {start_fmt}\n"
        out += f"• Reset Block: {reset_block:,}\n"
        out += f"• Reset Time: {reset_fmt}\n"
        out += f"• Epoch Duration: {duration}\n\n"

    return out

# ============================================================
#  Animation / pin helpers (unchanged logic)
# ============================================================

async def animate_message(chat, message_id, texts, forum=False, delay=0.5, keep_final=True, wait_task=None):
    if not texts:
        return

    for idx, t in enumerate(texts):
        try:
            await bot.edit_message_text(
                chat_id=int(chat),
                message_id=int(message_id),
                text=t,
            )
        except:
            pass

        if idx < len(texts) - 1:
            await asyncio.sleep(delay)

    if keep_final and wait_task is not None:
        while not wait_task.done():
            await asyncio.sleep(delay)


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


async def send_dashboard(chat, meta, global_state, current_block, block_sec=None, forum=False):
    text = await build_dashboard(global_state, current_block, block_sec=block_sec)

    if meta.get("msg_id"):
        try:
            await bot.delete_message(chat_id=int(chat), message_id=int(meta["msg_id"]))
        except:
            pass

    msg = await send_text(chat, text, forum=forum)
    meta["msg_id"] = msg.message_id

    s = calculate_epoch_stats(global_state, current_block, block_sec=block_sec)
    await update_pin_message(chat, meta, global_state, format_duration(s["remaining_sec"]), forum=forum)

# ============================================================
#  /setblock helper
# ============================================================

async def record_manual_set(state, entered_block, current_block, start_block, reset_block, block_sec=None):
    """
    Record a manual block-set event in history using blockchain timestamps.
    """
    epoch_no = get_epoch_no_from_start(start_block)

    start_ts = await fetch_block_timestamp(start_block)
    if start_ts:
        record_anchor(state, epoch_no, start_block, start_ts)
        start_fmt = format_blockchain_time(start_ts)
    else:
        start_fmt = "pending"

    state["history"].append({
        "kind": "manual_set",
        "epoch_no": epoch_no,
        "start_block": start_block,
        "reset_block": reset_block,
        "start_timestamp": start_ts,
        "reset_timestamp": None,
        "start_fmt": start_fmt,
        "reset_fmt": "pending",
        "epoch_duration": "pending",
    })

# ============================================================
#  Live broadcast tracking (for /live command)
# ============================================================

_live_tasks: dict[str, asyncio.Task] = {}


async def _live_loop(chat, forum):
    """Broadcast live block height every 5 minutes."""
    try:
        while True:
            try:
                snapshot = await get_live_block_snapshot()
                height = snapshot["currentHeight"]
                ts = snapshot.get("currentTimestamp")
                sec = snapshot.get("sampleBlockSec") or AVG_BLOCK_TIME

                # Quick epoch progress for context
                store, _ = await load_data_async()
                gs = get_global_state(store)
                s = calculate_epoch_stats(gs, height, block_sec=sec)

                line = (
                    f"📡 Live Update\n"
                    f"• Block: {height:,}\n"
                    f"• Epoch {s['epoch_no']} | {s['pct']:.1f}% done\n"
                    f"• Blocks Left: {s['left']:,}\n"
                    f"• Est. Reset: {format_duration(s['remaining_sec'])}"
                )
                await send_text(chat, line, forum=forum)
            except Exception as e:
                print(f"_live_loop error: {e}")

            await asyncio.sleep(300)  # 5 minutes
    except asyncio.CancelledError:
        pass

# ============================================================
#  Main handler
# ============================================================

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

    # ── /start ────────────────────────────────────────────────
    if low in ["/start", "🔄 refresh"]:
        if chat_meta.get("pin_msg_id"):
            try:
                await bot.unpin_chat_message(chat_id=int(chat))
            except:
                pass
            chat_meta["pin_msg_id"] = None

        snapshot = await get_live_block_snapshot()
        current_block = snapshot["currentHeight"]
        current_timestamp = snapshot.get("currentTimestamp")
        block_sec = snapshot.get("sampleBlockSec") or _effective_block_sec(global_state)
        global_state["last_block_sec"] = block_sec

        await sync_epoch_state(global_state, current_block, current_timestamp, block_sec=block_sec)

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

        await send_dashboard(chat, chat_meta, global_state, current_block, block_sec=block_sec, forum=forum)

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)
        return

    # ── /status ───────────────────────────────────────────────
    if low in ["/status", "📊 status"]:
        block_task = asyncio.create_task(get_live_block_snapshot())

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        loading_anim = asyncio.create_task(
            animate_message(
                chat,
                loading_msg.message_id,
                ["📡 Connecting to blockchain...", "🔍 Fetching live block data...", "🔄 Updating dashboard..."],
                forum=forum,
                delay=0.5,
                keep_final=True,
                wait_task=block_task,
            )
        )

        snapshot = await block_task
        await loading_anim

        current_block = snapshot["currentHeight"]
        current_timestamp = snapshot.get("currentTimestamp")
        block_sec = snapshot.get("sampleBlockSec") or _effective_block_sec(global_state)
        global_state["last_block_sec"] = block_sec

        await sync_epoch_state(global_state, current_block, current_timestamp, block_sec=block_sec)

        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        await send_dashboard(chat, chat_meta, global_state, current_block, block_sec=block_sec, forum=forum)

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)
        return

    # ── /blocks ───────────────────────────────────────────────
    if low in ["/blocks", "🔺 block height"]:
        block_task = asyncio.create_task(get_live_block_snapshot())

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        loading_anim = asyncio.create_task(
            animate_message(
                chat,
                loading_msg.message_id,
                ["📡 Connecting to blockchain...", "🔍 Fetching data...", "📖 Reading live block height..."],
                forum=forum,
                delay=0.5,
                keep_final=True,
                wait_task=block_task,
            )
        )

        snapshot = await block_task
        await loading_anim
        b = snapshot["currentHeight"]

        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        if b is None:
            await send_text(chat, "⚠️ Unable to fetch current block height.", forum=forum)
        else:
            await send_text(chat, f"📦 Block height is {b:,}", forum=forum)
        return

    # ── /help ─────────────────────────────────────────────────
    if low in ["/help", "ℹ️ help"]:
        help_text = (
            "🧭 Bot Commands\n\n"
            "📊 /status  — Live epoch progress & estimated reset time\n"
            "📦 /blocks  — Show current block height\n"
            "📈 /analysis — Epoch history with exact blockchain timestamps\n"
            "📡 /live    — Broadcast live block every 5 minutes\n"
            "🛑 /stoplive — Stop live broadcast\n"
            "📌 /pin     — Pin countdown message\n"
            "🔧 /setblock <block> — Manually set the epoch reset block\n"
            "ℹ️ /help    — Show this help"
        )
        await send_text(chat, help_text, forum=forum)
        return

    # ── /pin ──────────────────────────────────────────────────
    if low == "/pin":
        snapshot = await get_live_block_snapshot()
        current_block = snapshot["currentHeight"]
        current_timestamp = snapshot.get("currentTimestamp")
        block_sec = snapshot.get("sampleBlockSec") or _effective_block_sec(global_state)
        global_state["last_block_sec"] = block_sec

        await sync_epoch_state(global_state, current_block, current_timestamp, block_sec=block_sec)
        s = calculate_epoch_stats(global_state, current_block, block_sec=block_sec)

        msg = await send_text(chat, f"⏳ Time to next epoch: {format_duration(s['remaining_sec'])}", forum=forum)

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

    # ── /setblock ─────────────────────────────────────────────
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
        current_timestamp = snapshot.get("currentTimestamp")
        block_sec = snapshot.get("sampleBlockSec") or _effective_block_sec(global_state)
        global_state["last_block_sec"] = block_sec

        # Interpret entered_block as either a reset block or a start block
        if entered_block > current_block:
            start_block = entered_block - BLOCKS_PER_EPOCH
            reset_block = entered_block
        else:
            start_block = entered_block
            reset_block = entered_block + BLOCKS_PER_EPOCH

        global_state["start_block"] = start_block

        await record_manual_set(global_state, entered_block, current_block, start_block, reset_block, block_sec=block_sec)

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)

        await send_text(chat, f"✅ Epoch reset block set. Start: {start_block:,} | Reset: {reset_block:,}", forum=forum)
        return

    # ── /analysis ─────────────────────────────────────────────
    if low in ["/analysis", "📈 analysis"]:
        load_task = asyncio.create_task(load_data_async())

        loading_msg = await send_text(chat, "📡 Connecting to blockchain...", forum=forum)
        loading_anim = asyncio.create_task(
            animate_message(
                chat,
                loading_msg.message_id,
                ["📡 Connecting to blockchain...", "📚 Collecting epoch history...", "📊 Building analysis report..."],
                forum=forum,
                delay=0.5,
                keep_final=True,
                wait_task=load_task,
            )
        )

        store, sha = await load_task
        await loading_anim
        global_state = get_global_state(store)
        chat_meta = get_chat_meta(store, chat)

        snapshot = await get_live_block_snapshot()
        current_block = snapshot["currentHeight"]
        current_timestamp = snapshot.get("currentTimestamp")
        block_sec = snapshot.get("sampleBlockSec") or _effective_block_sec(global_state)
        global_state["last_block_sec"] = block_sec

        await sync_epoch_state(global_state, current_block, current_timestamp, block_sec=block_sec)

        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass

        report = build_analysis_report(global_state, block_sec=block_sec)
        if not report:
            await send_text(chat, "📊 No epoch records yet.", forum=forum)
        else:
            await send_text(chat, report, forum=forum)

        store[GLOBAL_KEY] = global_state
        store[CHAT_META_KEY][chat] = chat_meta
        await save_data_async(store, sha)
        return

    # ── /live ─────────────────────────────────────────────────
    if low == "/live":
        if chat in _live_tasks and not _live_tasks[chat].done():
            await send_text(chat, "📡 Live updates already running. Use /stoplive to stop.", forum=forum)
            return

        task = asyncio.create_task(_live_loop(chat, forum))
        _live_tasks[chat] = task
        await send_text(chat, "📡 Live block updates started — every 5 minutes.\nUse /stoplive to stop.", forum=forum)
        return

    # ── /stoplive ─────────────────────────────────────────────
    if low == "/stoplive":
        task = _live_tasks.get(chat)
        if task and not task.done():
            task.cancel()
            await send_text(chat, "🛑 Live updates stopped.", forum=forum)
        else:
            await send_text(chat, "ℹ️ No live updates are running.", forum=forum)
        return

# ============================================================
#  ASGI entry point (unchanged)
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
