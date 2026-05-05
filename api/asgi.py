import base64
import json
import time
import os
import re
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

# ===== BLOCK-BASED EPOCH CONSTANTS =====
BLOCKS_PER_EPOCH = 262_000
TOTAL_EPOCHS_PER_DAY = 288
EPOCH_RESET_BLOCK = 52_662_000  # May 4, 2025
AVG_BLOCK_TIME = 0.35  # 0.3-0.4s average

# Reward tier blocks (3 equal parts)
TIER_1_END = BLOCKS_PER_EPOCH // 3  # 87,333 blocks
TIER_2_END = (BLOCKS_PER_EPOCH * 2) // 3  # 174,666 blocks

OWNER_LIST = [i.strip() for i in OWNER_IDS.split(",") if i.strip()]

# GraphQL API
GRAPHQL_URL = "https://mainnet.ackinacki.org/graphql"

# ================== GITHUB ==================
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


def message_kwargs(forum=False):
    if forum:
        return {"message_thread_id": TARGET_THREAD_ID}
    return {}


async def send_text(chat_id, text, forum=False, **kwargs):
    kw = {}
    kw.update(message_kwargs(forum))
    kw.update(kwargs)
    return await bot.send_message(int(chat_id), text, **kw)


# ================== GET BLOCK HEIGHT ==================
async def get_current_block_height():
    """Fetch current block height from GraphQL API"""
    query = """
    query GetBlocks($limit: Int!) {
        blockchain {
            blocks(last: $limit) {
                nodes {
                    seq_no
                    gen_utime
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
        async with aiohttp.ClientSession() as session:
            async with session.post(GRAPHQL_URL, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    blocks = data.get('data', {}).get('blockchain', {}).get('blocks', {}).get('nodes', [])
                    if blocks:
                        return blocks[0]['seq_no']
    except Exception as e:
        print(f"Error fetching block: {e}")
    
    return None


# ================== BLOCK-HEIGHT CALCULATIONS ==================
async def calculate_epoch_stats():
    """Calculate current epoch stats based on block height"""
    current_block = await get_current_block_height()
    
    if not current_block:
        return None
    
    # Calculate blocks since epoch reset
    blocks_since_reset = current_block - EPOCH_RESET_BLOCK
    blocks_in_current_epoch = blocks_since_reset % BLOCKS_PER_EPOCH
    
    # Calculate current epoch number
    epochs_passed = blocks_since_reset // BLOCKS_PER_EPOCH
    current_epoch = 202 + epochs_passed
    
    # Calculate next epoch reset block
    next_reset_block = EPOCH_RESET_BLOCK + ((epochs_passed + 1) * BLOCKS_PER_EPOCH)
    blocks_until_reset = next_reset_block - current_block
    
    # Calculate percentage complete
    progress_percent = (blocks_in_current_epoch / BLOCKS_PER_EPOCH) * 100
    
    # Estimate reset time based on block speed
    estimated_reset_seconds = blocks_until_reset * AVG_BLOCK_TIME
    reset_time = datetime.now(IST) + timedelta(seconds=estimated_reset_seconds)
    
    # Determine current tier
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
    
    # Calculate tier start times
    tier_1_start_block = EPOCH_RESET_BLOCK + (epochs_passed * BLOCKS_PER_EPOCH)
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


# ================== TIME FORMATTING ==================
def format_time_with_zones(dt_ist):
    """Convert IST datetime to UTC and CEST"""
    utc_dt = dt_ist.astimezone(UTC)
    cest_dt = dt_ist.astimezone(CEST)
    
    ist_str = dt_ist.strftime("%d %b %I:%M %p")
    utc_str = utc_dt.strftime("%I:%M %p")
    cest_str = cest_dt.strftime("%I:%M %p")
    
    return f"{ist_str} IST [UTC: {utc_str} | CEST: {cest_str}]"


def format_duration(seconds):
    """Format seconds to mm:ss or hh:mm:ss"""
    if seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours}h {minutes}m {secs}s"


# ================== BUILD DASHBOARD ==================
async def build_dashboard():
    """Build block-height based dashboard"""
    stats = await calculate_epoch_stats()
    
    if not stats:
        return "⚠️ Unable to fetch block data. Please try again."
    
    # Calculate timer since epoch reset
    elapsed_seconds = stats['blocks_in_current_epoch'] * AVG_BLOCK_TIME
    timer_text = format_duration(elapsed_seconds)
    
    # Build dashboard
    text = (
        f"⏳ Timer Since Epoch Reset: {timer_text}\n\n"
        
        f"📊 Block Progress\n"
        f"• Current Block Height: {stats['current_block']:,}\n"
        f"• Epoch {stats['current_epoch']} Reset at: {stats['next_reset_block']:,}\n"
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
    """Send dashboard to chat"""
    text = await build_dashboard()
    
    # Delete previous message if it exists
    if state.get("msg_id"):
        try:
            await bot.delete_message(chat_id=int(chat), message_id=int(state["msg_id"]))
        except:
            pass
    
    msg = await send_text(chat, text, forum=forum)
    state["msg_id"] = msg.message_id


# ================== HANDLER ==================
async def handle(update: Update):
    if not update.effective_user or not update.effective_chat:
        return

    user_id = str(update.effective_user.id)
    chat = str(update.effective_chat.id)
    forum = bool(getattr(update.effective_chat, "is_forum", False))
    thread_id = getattr(update.message, "message_thread_id", None) if update.message else None
    in_target_thread = thread_id == TARGET_THREAD_ID if thread_id else False
    
    key = f"{chat}:{user_id}"
    store, sha = load_data()
    state = store.get(key, {})

    if not update.message:
        return

    text = (update.message.text or "").strip()
    low = text.lower()

    # ========== PUBLIC /STATUS COMMAND ==========
    if low == "/status":
        # Show loading message
        loading_msg = await send_text(chat, "⏳ Updating... Dashboard", forum=forum)
        
        await asyncio.sleep(0.5)
        
        try:
            await bot.delete_message(chat_id=int(chat), message_id=loading_msg.message_id)
        except:
            pass
        
        # Send dashboard
        await send_dashboard(chat, state, forum=forum)
        store[key] = state
        save_data(store, sha)
        return

    # ========== OWNER-ONLY COMMANDS ==========
    if user_id not in OWNER_LIST:
        msg = await send_text(chat, "💡 Use <code>/status</code> to check the dashboard and see live updates!", forum=forum, parse_mode="HTML")
        
        async def delete_after_30s():
            await asyncio.sleep(30)
            try:
                await bot.delete_message(chat_id=int(chat), message_id=msg.message_id)
            except:
                pass
        
        asyncio.create_task(delete_after_30s())
        return

    if low == "/start":
        await send_text(chat, "👋 Welcome to Epoch Helper Bot!", forum=forum)
        return

    elif low == "/epoch":
        state = {"start_block": EPOCH_RESET_BLOCK, "msg_id": None}
        store[key] = state
        save_data(store, sha)
        await send_dashboard(chat, state, forum=forum)
        return


# ================== ASGI ==================
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
        
