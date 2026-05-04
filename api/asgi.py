import base64, json, os
from datetime import datetime, timedelta, timezone
from urllib.request import Request, urlopen
from telegram import Bot, Update, ReplyKeyboardMarkup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_FILE = "data.json"

bot = Bot(token=BOT_TOKEN)

BLOCKS_PER_EPOCH = 262000

# ---------------- GITHUB ----------------
API = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"

def gh_headers():
    return {"Authorization": f"Bearer {GITHUB_TOKEN}"}

def load():
    try:
        req = Request(API)
        for k,v in gh_headers().items():
            req.add_header(k,v)
        res = json.loads(urlopen(req).read())
        return json.loads(base64.b64decode(res["content"]).decode()), res["sha"]
    except:
        return {}, None

def save(data, sha):
    body = {
        "message":"update",
        "content": base64.b64encode(json.dumps(data).encode()).decode()
    }
    if sha:
        body["sha"]=sha

    req = Request(API, data=json.dumps(body).encode(), method="PUT")
    for k,v in gh_headers().items():
        req.add_header(k,v)
    req.add_header("Content-Type","application/json")
    urlopen(req)

# ---------------- BLOCK ----------------
def get_block():
    url = "https://mainnet.ackinacki.org/graphql"

    payload = json.dumps({
        "query": "{ blockchain { blocks(last:1){ nodes{ seq_no }}}}"
    }).encode()

    req = Request(url, data=payload,
                  headers={"Content-Type":"application/json"},
                  method="POST")

    res = json.loads(urlopen(req).read())
    return res["data"]["blockchain"]["blocks"]["nodes"][0]["seq_no"]

# ---------------- CALC ----------------
def calc(start_block):
    current = get_block()

    passed = current - start_block
    cycle = passed % BLOCKS_PER_EPOCH
    remaining = BLOCKS_PER_EPOCH - cycle

    percent = (cycle / BLOCKS_PER_EPOCH) * 100

    return current, cycle, remaining, percent

# ---------------- TIME ----------------
def estimate_time(remaining):
    BLOCK_TIME = 0.34
    seconds = int(remaining * BLOCK_TIME)
    return datetime.utcnow() + timedelta(seconds=seconds)

def format_times(dt):
    utc = dt.replace(tzinfo=timezone.utc)
    ist = utc.astimezone(timezone(timedelta(hours=5, minutes=30)))
    cest = utc.astimezone(timezone(timedelta(hours=2)))
    return utc, ist, cest

# ---------------- MENU ----------------
def menu():
    return ReplyKeyboardMarkup(
        [["/status","/live"],["/setblock","/reset"]],
        resize_keyboard=True
    )

# ---------------- HANDLER ----------------
async def handle(update: Update):
    if not update.message:
        return

    chat = str(update.effective_chat.id)
    user = str(update.effective_user.id)
    key = f"{chat}:{user}"

    store, sha = load()
    state = store.get(key, {})

    # 🔥 FIXED COMMAND PARSING
    text = (update.message.text or "").strip()
    low = text.lower()

    print("Incoming:", text)

    # ---------------- SET BLOCK ----------------
    if low.startswith("/setblock"):
        try:
            parts = text.split()
            block = int(parts[1])

            state["start_block"] = block
            store[key] = state
            save(store, sha)

            await bot.send_message(int(chat), f"✅ Reset block set: {block:,}")

        except:
            await bot.send_message(int(chat), "❌ Use: /setblock 52662000")

    # ---------------- STATUS ----------------
    elif low.split()[0] == "/status":
        if "start_block" not in state:
            await bot.send_message(int(chat), "❌ Set block first using /setblock")
            return

        current, cycle, remaining, percent = calc(state["start_block"])

        reset_time = estimate_time(remaining)
        utc, ist, cest = format_times(reset_time)

        msg = (
            f"📊 Live Chain Status\n\n"
            f"🔗 Current Block: {current:,}\n\n"

            f"📈 Progress\n"
            f"• Done: {cycle:,} / 262,000\n"
            f"• Remaining: {remaining:,}\n"
            f"• Progress: {percent:.2f}%\n\n"

            f"⏳ Reset Time\n"
            f"• UTC : {utc.strftime('%d %b %H:%M')}\n"
            f"• IST : {ist.strftime('%d %b %I:%M %p')}\n"
            f"• CEST: {cest.strftime('%d %b %H:%M')}"
        )

        await bot.send_message(int(chat), msg)

    # ---------------- LIVE ----------------
    elif low.split()[0] == "/live":
        if "start_block" not in state:
            await bot.send_message(int(chat), "❌ Set block first")
            return

        current, cycle, remaining, percent = calc(state["start_block"])

        await bot.send_message(
            int(chat),
            f"🔴 LIVE\n"
            f"Block: {current:,}\n"
            f"Remaining: {remaining:,}\n"
            f"{percent:.2f}% done"
        )

    # ---------------- RESET ----------------
    elif low.split()[0] == "/reset":
        if key in store:
            del store[key]
            save(store, sha)

        await bot.send_message(int(chat), "🗑️ Reset done")

    else:
        await bot.send_message(int(chat), "👇 Use menu", reply_markup=menu())

# ---------------- ENTRY ----------------
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
            print("ERROR:", e)

        await send({"type":"http.response.start","status":200})
        await send({"type":"http.response.body","body":b"ok"})
