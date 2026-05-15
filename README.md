# ⏱️ AckiNacki Mobile Verifiers Epoch Monitor Bot

> **A smart Telegram bot for tracking Acki Nacki Blockchain Mobile Verifier's epochs in real-time — live dashboard, exact block timestamps, explorer links, reward tier tracking, and persistent analytics.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API-blue.svg)](https://core.telegram.org/bots/api)
[![Vercel](https://img.shields.io/badge/Hosted%20on-Vercel-black.svg)](https://vercel.com)

---

## 🌟 Features

- ✅ **Real-time Dashboard** — Pinned message updates live without spam via inline Update button
- ✅ **Live Block Tracking** — Fetches current block height from Acki Nacki GraphQL API with fallback endpoint
- ✅ **Epoch Progress** — Tracks blocks produced, blocks remaining, and % completion per epoch
- ✅ **Estimated Reset Time** — Calculated live from real block rate in IST, UTC, and CEST
- ✅ **Reward Tier Tracking** — Shows current tier (1/2/3) with % progress within that tier only
- ✅ **Exact Block Timestamps** — Fetches real `gen_utime` from blockchain for epoch boundary blocks
- ✅ **Explorer Links** — Each boundary block links directly to `dev.acki.live/blocks/<hash>`
- ✅ **Epoch Reports** — Full report for any specific epoch number (`/epoch 209`)
- ✅ **Analysis History** — Last 3 completed epochs with exact times, duration and explorer links
- ✅ **Background Caching** — Proactively captures block timestamps on every user interaction (API only holds ~24h)
- ✅ **Cross-epoch Reuse** — Reset block of epoch N = Start block of epoch N+1, reused automatically
- ✅ **Stale Record Healing** — Pending reset times filled automatically when next epoch data becomes available
- ✅ **Duplicate `/start` Protection** — Deletes old pin and dashboard before creating fresh ones
- ✅ **Persistent Storage** — All data saved to GitHub JSON (no database needed)
- ✅ **Group + Forum Support** — Works in groups, supergroups, and forum threads
- ✅ **DM Restricted** — DM access for bot owner only; others get a friendly redirect message
- ✅ **`!` Command Support** — Accepts both `/command` and `!command` syntax

---

## 📋 Prerequisites

- Python 3.8 or higher
- Telegram Bot Token from [@BotFather](https://t.me/botfather)
- GitHub Personal Access Token (with `repo` scope)
- GitHub Repository for data storage
- Vercel account (or any ASGI-compatible hosting)

---

## 🚀 Quick Start

### Step 1: Clone the Repository
```bash
git clone https://github.com/yourusername/epoch-helper-bot.git
cd epoch-helper-bot
```

### Step 2: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 3: Set Environment Variables

Set these in Vercel Dashboard → Settings → Environment Variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Telegram Bot Token from @BotFather |
| `GITHUB_TOKEN` | ✅ | GitHub Personal Access Token (`repo` scope) |
| `GITHUB_REPO` | ✅ | GitHub repo for storage e.g. `username/repo` |
| `GITHUB_FILE` | ⚠️ | Data filename (default: `data.json`) |

### Step 4: Create GitHub Data File

In your GitHub repository, create `data.json`:
```json
{}
```

### Step 5: Deploy to Vercel

#### Option A: Vercel CLI
```bash
npm install -g vercel
vercel login
vercel
```

#### Option B: GitHub Integration
1. Connect your repo to [Vercel Dashboard](https://vercel.com)
2. Go to Settings → Environment Variables and add all variables above
3. Deploy — auto-redeploys on every push to main

### Step 6: Set Telegram Webhook

```
https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=https://{VERCEL_URL}.vercel.app/asgi.py
```

Verify it's set correctly:
```bash
curl https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo
```

---

## 📱 Bot Commands

All commands work with both `/` and `!` prefix (e.g. `/start` or `!start`).

| Command | Description |
|---------|-------------|
| `/start` | Send pinned countdown + live dashboard with Update button |
| `/status` | Refresh dashboard and update pinned message in-place |
| `/blocks` | Show live block height with Refresh button |
| `/epoch <n>` | Full report for a specific epoch e.g. `/epoch 209` |
| `/analysis` | Last 3 completed epochs with timestamps and explorer links |
| `/help` | Show all available commands |

---

## 📊 How It Works

### Blockchain & Epoch System

```
Network:            Acki Nacki Mainnet
GraphQL Primary:    https://mainnet.ackinacki.org/graphql
GraphQL Fallback:   https://mainnet-cf.ackinacki.org/graphql
Block Explorer:     https://dev.acki.live/blocks/<hash>
Blocks per Epoch:   262,000
Avg Block Time:     ~0.33s (fallback only — live rate used when available)
```

### Epoch Calculation

```python
epoch_no    = block_height // 262_000
start_block = epoch_no * 262_000
reset_block = (epoch_no + 1) * 262_000
```

### Reward Tiers

Each epoch of 262,000 blocks is split into 3 equal tiers:

| Tier | Block Range (within epoch) | Reward Level |
|------|---------------------------|--------------|
| **Tier 1** | 0 – 87,333 | High Reward |
| **Tier 2** | 87,334 – 174,666 | Medium Reward |
| **Tier 3** | 174,667 – 262,000 | Low Reward |

Tier progress % is calculated **within the current tier's range only**, not the full epoch.

---

## 🖥️ Display Examples

### Pinned Message
```
⏳ Time to next epoch reset: 14h 32m
📌 Est. reset: 15/05 08:48 PM IST
```

### Full Dashboard
```
Current Epoch: 210
⏳ Timer Since Epoch Reset: 3h 12m
⏱️ Time left to reset: 21h 45m

📊 Block Progress
• Current Block Height: 55,062,400
• Epoch 210 Started at: 55,020,000
• Epoch 210 Resets at:  55,282,000
• Blocks Produced This Epoch: 42,400
• Blocks Left to Reset: 219,600
• Progress: 16.2%

🔁 Estimated Reset
• IST:  16/05 01:30 AM
• UTC:  15/05 08:00 PM
• CEST: 15/05 10:00 PM

🏆 Reward Tier
• Tier 1 — High Reward (<6k taps)
• Tier Progress: 48.5%
```

### Epoch Report (`/epoch 209`)
```
📅 Epoch 209 | Auto Reset
• Start Block: 54,758,000 Block Info 🔗
• Start Time: 13/05/2026 | 12:21 AM | UTC:18:51
• Reset Block: 55,020,000 Block Info 🔗
• Reset Time: 14/05/2026 | 01:30 AM | UTC:20:00
• Epoch Duration: 25h 9m (90,540s exact)
```

### Analysis (`/analysis`)
```
📊 Last 3 Completed Epochs

📅 Epoch 208 | Auto Reset
• Start Block: 54,496,000 Block Info 🔗
• Start Time: 11/05/2026 | 11:20 PM | UTC:17:50
• Reset Block: 54,758,000 Block Info 🔗
• Reset Time: 13/05/2026 | 12:21 AM | UTC:18:51
• Epoch Duration: 25h 1m (90,060s)

📅 Epoch 209 | Auto Reset
• Start Block: 54,758,000 Block Info 🔗
• Start Time: 13/05/2026 | 12:21 AM | UTC:18:51
• Reset Block: 55,020,000 Block Info 🔗
• Reset Time: 14/05/2026 | 01:30 AM | UTC:20:00
• Epoch Duration: 25h 9m (90,540s)

📅 Epoch 210 | Auto Reset
• Start Block: 55,020,000 Block Info 🔗
• Start Time: 14/05/2026 | 01:30 AM | UTC:20:00
• Reset Block: 55,282,000
• Reset Time: pending
• Epoch Duration: pending
```

---

## 🕐 Timestamp Fetching Strategy

The Acki Nacki API only holds **~24 hours** of block history. The bot uses multiple strategies to never miss a timestamp:

### Fetch Strategies (tried in order)

1. **`blockByHeight(thread_id, height)`** → `block(hash)` — explorer method, ideal for recent blocks
2. **`seq_no range ±5` → `nodes { seq_no hash chain_order gen_utime }`** — exact match, decodes timestamp from `chain_order` if `gen_utime` is missing
3. **`seq_no range ±5` → `edges { node { ... } }`** — legacy schema fallback

### `chain_order` Timestamp Decoding

Per official Acki Nacki docs, `chain_order` encodes the Unix timestamp in its first field:
```
chain_order = <len><timestamp_hex><len><placeholder><len><thread_id><len><height>

Example: "7698320d0006700...061d4b1c0"
  "7"        → field is 8 hex chars
  "698320d0" → 0x698320d0 = 1770201296 (Unix timestamp)
```
This allows timestamp extraction even without `gen_utime`.

### Cross-Epoch Reuse

The reset block of epoch N is the **exact same block** as the start block of epoch N+1:

```
Epoch 209 reset block = 55,020,000
Epoch 210 start block = 55,020,000  ← same block, fetched once
```

When epoch N's reset timestamp is missing, the bot automatically reuses epoch N+1's cached start — no extra API call.

### Stale Record Healing

If epoch N was stored before epoch N+1 existed (reset showed `pending`), calling `/epoch N` again detects epoch N+1's start in the store, fills in the missing reset, recalculates the duration, and saves the updated record to GitHub automatically.

### Background Caching

Runs silently on every `/status`, Update button press, and `/start`:
- Captures the **current epoch's start block** timestamp immediately while it's within the 24h window
- Fills the **previous epoch's reset** using the current epoch's start (same block)
- Saves to GitHub only if new data was captured

---

## 💾 Data Storage Schema

All data stored in GitHub as JSON:

```json
{
  "chat_id": {
    "pin_msg_id": 12345,
    "dashboard_msg_id": 12346
  },
  "history": [
    {
      "kind": "auto_reset",
      "epoch_no": 209,
      "start_block": 54758000,
      "reset_block": 55020000,
      "start_timestamp": 1747093260,
      "reset_timestamp": 1747184200,
      "start_fmt": "13/05/2026 | 12:21 AM | UTC:18:51",
      "reset_fmt": "14/05/2026 | 01:30 AM | UTC:20:00",
      "exact_start_time": "2026-05-13 18:51:00 UTC",
      "exact_reset_time": "2026-05-14 20:00:00 UTC",
      "epoch_duration": "25h 9m",
      "epoch_duration_seconds": 90540,
      "start_hash": "1d24a55d896f02aa...",
      "reset_hash": "d0e65643af0f2f49...",
      "start_url": "https://dev.acki.live/blocks/1d24a55d...",
      "reset_url": "https://dev.acki.live/blocks/d0e65643..."
    }
  ]
}
```

---

## 🔧 Core Constants

```python
BLOCKS_PER_EPOCH     = 262_000
TIER_1_END           = 262_000 // 3          # 87,333
TIER_2_END           = (262_000 * 2) // 3    # 174,666
AVG_BLOCK_TIME       = 0.33                  # seconds, fallback only
GRAPHQL_URL_PRIMARY  = "https://mainnet.ackinacki.org/graphql"
GRAPHQL_URL_FALLBACK = "https://mainnet-cf.ackinacki.org/graphql"
EXPLORER_BASE        = "https://dev.acki.live/blocks"
IST                  = UTC+5:30
CEST                 = UTC+2:00
```

---

## 📦 Project Structure

```
epoch-helper-bot/
├── asgi.py           # Main bot application (ASGI)
├── requirements.txt  # Python dependencies
├── vercel.json       # Vercel deployment config
├── .gitignore        # Git ignore rules
└── README.md         # This file
```

---

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Language** | Python 3.8+ | Backend logic |
| **Bot Framework** | python-telegram-bot | Telegram API wrapper |
| **Server** | ASGI (Vercel) | Serverless hosting |
| **Storage** | GitHub REST API | Persistent data |
| **Blockchain** | Acki Nacki GraphQL | Live block data & timestamps |
| **Explorer** | dev.acki.live | Block detail links |
| **Timezone** | datetime / pytz | IST / UTC / CEST display |

---

## 🐛 Troubleshooting

### Dashboard not sending on `/start`
- Check `reward_tier()` strings don't contain raw `<` or `>` — these break `parse_mode="HTML"`
- Must be escaped as `&lt;` and `&gt;`

### Timestamps showing pending
- API only holds ~24h of block history
- Press Update or `/status` at least once per epoch (~25h) to cache timestamps while fresh
- Calling `/epoch N` again after epoch N+1 is cached will auto-fill the pending reset

### Block Info link not clickable
- Requires `parse_mode="HTML"` (already default in current code)
- Links use `<a href="...">Block Info 🔗</a>` HTML anchor format

### Bot not responding
1. Verify webhook: `curl https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo`
2. Check Vercel deployment logs
3. Verify all environment variables are set

### Data not persisting
1. Verify GitHub PAT has `repo` scope
2. Confirm `data.json` exists in the repo
3. Check `GITHUB_REPO` is `username/repo-name` format

### Webhook setup fails
- URL must end with `/asgi.py`
- Must be HTTPS, no trailing slash

---

## 🔒 Security

- ✅ All tokens stored in environment variables only
- ✅ DM access restricted to bot owner; others receive friendly group redirect
- ✅ Group access open to all members
- ✅ Never commit `.env` to repository

### Recommended `.gitignore`
```
.env
.env.local
*.pyc
__pycache__/
.vercel/
```

---

## 🚀 Deployment Options

### Option 1: Vercel (Recommended) ⭐
- Free tier available
- Auto-deploys on every push
- Serverless — scales automatically

### Option 2: Self-Hosted
```bash
python -m uvicorn asgi:app --host 0.0.0.0 --port 8000
```

---

## 📝 Telegram API Methods Used

```
sendMessage()
editMessageText()
pinChatMessage()
deleteMessage()
answerCallbackQuery()
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

## 🎉 Changelog

### v2.1.0 (May 2026)
- ✅ Fixed dashboard not sending — HTML `<` `>` in tier strings escaped as `&lt;` `&gt;`
- ✅ Stale record healing — pending reset times auto-filled when next epoch is cached
- ✅ Tier progress % calculated within current tier's range only (not full epoch)
- ✅ DM redirect message updated with friendly explanation

### v2.0.0 (May 2026)
- ✅ Full rewrite — blockchain-native (Acki Nacki GraphQL)
- ✅ Real block height tracking, no time-based estimation
- ✅ Exact timestamps from `gen_utime` and `chain_order` decoding
- ✅ Explorer links via `dev.acki.live/blocks/<hash>`
- ✅ Multi-strategy timestamp fetching with cross-epoch reuse
- ✅ Background epoch caching on every user interaction
- ✅ `!command` syntax support alongside `/command`
- ✅ IST + UTC + CEST timezone display
- ✅ `/epoch <n>` single epoch report with explorer links
- ✅ `/analysis` last 3 completed epochs
- ✅ Duplicate `/start` protection — deletes old messages first
- ✅ `parse_mode="HTML"` throughout with `<code>` block values

### v1.0.0 (April 2026)
- ✅ Initial release with time-based epoch tracking

---

**Last Updated**: May 2026
**Status**: Active & Maintained
**Python Version**: 3.8+
