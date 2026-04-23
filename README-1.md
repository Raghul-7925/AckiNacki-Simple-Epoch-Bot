# ⏱️ Epoch Helper Bot

> **A smart Telegram bot for tracking daily 24h 55m epochs with continuous cycling, persistent analytics, and real-time dashboard updates.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API-blue.svg)](https://core.telegram.org/bots/api)
[![Vercel](https://img.shields.io/badge/Hosted%20on-Vercel-black.svg)](https://vercel.com)

---

## 🌟 Features

- ✅ **Real-time Dashboard** - Pinned message that updates live without spam
- ✅ **24h 55m Reset Cycle** - Accurate daily resets with automatic continuation
- ✅ **Continuous Cycling** - Days flow seamlessly: Day 1 → Day 2 → Day 3 → ∞
- ✅ **Daily Reward Zones** - 80% zone (1-96 epochs) vs 20% zone (97-172 epochs)
- ✅ **Epoch Tracking** - 288 epochs per day × 330 seconds each
- ✅ **Tap Counter** - 12,000 daily tap limit with real-time progress
- ✅ **Analytics** - Historical table of all past days with exact start/reset times
- ✅ **Manual Time Set** - Set custom epoch start time via interactive menus
- ✅ **Phase Timings** - Part 1, Part 2, Part 3 with scheduled timestamps
- ✅ **Persistent Storage** - All data saved to GitHub (no database needed)
- ✅ **Group Support** - Works in private chats and groups with pinned messages

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

### Step 3: Create Environment File
```bash
cp .env.example .env
```

Edit `.env` with your credentials:
```env
BOT_TOKEN=123456789:ABCDefGHijKlmnoPQRstUVwxyz
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GITHUB_REPO=yourusername/your-repo-name
GITHUB_FILE=data.json
```

### Step 4: Create GitHub Data File

In your GitHub repository, create `data.json`:
```json
{}
```

### Step 5: Deploy to Vercel

#### Option A: Using Vercel CLI
```bash
npm install -g vercel
vercel login
vercel
# Follow prompts and set environment variables
```

#### Option B: GitHub Integration
1. Connect your repo to [Vercel Dashboard](https://vercel.com)
2. Go to Settings → Environment Variables
3. Add all environment variables from `.env`
4. Auto-deploys on every push

### Step 6: Set Telegram Webhook

Replace `BOT_TOKEN` and `VERCEL_URL`, then visit in your browser:

```
https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=https://{VERCEL_URL}.vercel.app/asgi.py
```

Or use curl:
```bash
curl -X POST "https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url=https://{VERCEL_URL}.vercel.app/asgi.py"
```

Verify the webhook is set correctly:
```bash
curl https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo
```

---

## 📱 Bot Commands & Buttons

### Main Menu
| Button | Function | Description |
|--------|----------|-------------|
| ▶️ **Start Epoch** | Begin tracking | Starts from current time, creates live dashboard |
| 📊 **Status** | Show dashboard | Updates pinned message with live stats |
| 🕒 **Set Time** | Manual start | Choose specific time to start epoch (IST) |
| 🔄 **Reset** | Clear data | Deletes all tracking data for this user |
| 📈 **Analysis** | View history | Shows table of all past days with times |

### Slash Commands
- `/start` - Equivalent to ▶️ Start Epoch button

---

## 📊 How It Works

### Epoch System Overview

```
Duration per Day:  24 hours 55 minutes (89,700 seconds)
Total Epochs:      288 per day
Seconds per Epoch: 330 seconds (5 minutes 30 seconds)
Daily Tap Limit:   12,000 taps
Taps per Epoch:    70 taps
```

### Reward Structure

| Part | Epochs | Reward | Taps |
|------|--------|--------|------|
| **Part 1** (High) | 1-96 | 80% | 6,720 |
| **Part 2** (Medium) | 97-172 | 20% | 3,360 |
| **Part 3** (Low) | 173-288 | Low | 1,920 |

### Continuous Cycle Example

```
Day 1:  12:00 PM (23 Apr) ─→ 11:55 AM (24 Apr) [24h 55m reset]
         │
         └─→ Day 2:  11:55 AM (24 Apr) ─→ 11:50 AM (25 Apr) [24h 55m reset]
             │
             └─→ Day 3:  11:50 AM (25 Apr) ─→ 11:45 AM (26 Apr) [24h 55m reset]
                 │
                 └─→ ... continues forever without stopping ...
```

---

## 💾 Data Storage & Schema

All data stored in GitHub as JSON format:

```json
{
  "chat_id:user_id": {
    "start_time": 1713878400,
    "msg_id": 12345,
    "days": [
      {
        "day_num": 1,
        "start_date": "23 Apr 2026",
        "start_time": "12:00 PM",
        "reset_date": "24 Apr 2026",
        "reset_time": "11:55 AM"
      },
      {
        "day_num": 2,
        "start_date": "24 Apr 2026",
        "start_time": "11:55 AM",
        "reset_date": "25 Apr 2026",
        "reset_time": "11:50 AM"
      }
    ]
  }
}
```

---

## 🔧 Configuration

### Environment Variables

| Variable | Required | Type | Example | Description |
|----------|----------|------|---------|-------------|
| `BOT_TOKEN` | ✅ | String | `123456:ABC...` | Telegram Bot Token |
| `GITHUB_TOKEN` | ✅ | String | `ghp_xxx...` | GitHub Personal Access Token |
| `GITHUB_REPO` | ✅ | String | `username/repo` | GitHub repo for storage |
| `GITHUB_FILE` | ⚠️ | String | `data.json` | Filename (default: data.json) |

### Core Constants (in `asgi.py`)

```python
EPOCH_SECONDS = 330                    # Seconds per epoch
TOTAL_EPOCHS = 288                     # Epochs per day
DAILY_RESET_SECONDS = 89700            # 24h 55m in seconds
DAILY_TAP_LIMIT = 12000                # Daily tap limit
TAPS_PER_EPOCH = 70                    # Taps per epoch
IST = timezone(timedelta(hours=5, minutes=30))  # Timezone
```

---

## 📈 Analytics Dashboard

Click **📈 Analysis** button to view complete history:

```
📈 Analysis - Daily Cycle History

Day | Start Date       | Start Time    | Reset Date       | Reset Time
─────────────────────────────────────────────────────────────────────
  1 | 23 Apr 2026      | 12:00 PM      | 24 Apr 2026      | 11:55 AM
  2 | 24 Apr 2026      | 11:55 AM      | 25 Apr 2026      | 11:50 AM
  3 | 25 Apr 2026      | 11:50 AM      | 26 Apr 2026      | 11:45 AM
  4 | 26 Apr 2026      | 11:45 AM      | 27 Apr 2026      | 11:40 AM
```

- Automatically tracks every day
- Persists across bot restarts
- Accessible via GitHub data file

---

## 🎯 Live Dashboard Display

Example of real-time dashboard:

```
📊 Live Dashboard (Day 3)

⏱️ 14h 32m
🔢 Epoch: 156/288
📍 Part 2 (Medium reward)

🪙 Daily Reward Plan
• Tap limit: 12,000 taps/day
• Usable epochs today: 156/172
• 80% reward zone: 1–96 epochs
• 20% reward zone: 97–172 epochs
• 80% zone used: 96/96
• 20% zone used: 60/76
• 80% zone left: 0/96
• 20% zone left: 16/76

📊 Taps Summary
• Taps done: 10,920
• Taps left: 1,080

🧭 Phase Timings (Day 3)
• Part 1: 25 Apr 11:50 AM IST
• Part 2: 25 Apr 07:38 PM IST
• Part 3: 26 Apr 03:26 AM IST

⏳ Left: 9h 28m
🔁 Reset: 26 Apr 11:45 AM IST
```

---

## 🐛 Troubleshooting

### Bot not responding to commands

**Solution:**
1. Verify webhook is correctly set:
   ```bash
   curl https://api.telegram.org/botBOT_TOKEN/getWebhookInfo
   ```
2. Check Vercel deployment status in dashboard
3. Review logs: Vercel → Deployments → Logs
4. Verify environment variables are set

### Webhook setup fails

**Solution:**
- Ensure URL ends with `/asgi.py`
- Remove any trailing slashes
- Wait 5 minutes and retry
- Check URL is HTTPS (not HTTP)

### Data not persisting

**Solution:**
1. Verify GitHub PAT has `repo` scope:
   - Settings → Developer Settings → Personal Access Tokens
   - Scopes should include: ✅ `repo` (full)

2. Confirm `data.json` exists in repository
3. Check `GITHUB_REPO` format: `username/repo-name`
4. Verify GitHub API rate limits aren't exceeded

### Times showing incorrectly

**Solution:**
- Bot uses IST (UTC+5:30) timezone
- To change timezone, modify this line:
  ```python
  IST = timezone(timedelta(hours=YOUR_OFFSET))
  ```

### Dashboard not updating

**Solution:**
- Message is pinned (intentional design)
- Message updates in-place to prevent spam
- In groups: verify bot has admin rights
- Clear browser cache if viewing via API

---

## 🔒 Security Best Practices

- ✅ Store all tokens in environment variables
- ✅ Never commit `.env` file to repository
- ✅ Use `.gitignore` to exclude sensitive files
- ✅ Regenerate GitHub PAT periodically
- ✅ Limit PAT scope to minimum required (`repo` only)
- ✅ Use HTTPS for all API calls
- ✅ Keep dependencies updated

### Recommended `.gitignore`
```
.env
.env.local
*.pyc
__pycache__/
.vercel/
node_modules/
```

---

## 📦 Project Structure

```
epoch-helper-bot/
├── asgi.py                 # Main bot application (ASGI)
├── requirements.txt        # Python dependencies
├── vercel.json            # Vercel deployment config
├── .env.example           # Environment variables template
├── .gitignore             # Git ignore rules
├── README.md              # This file
└── .github/
    └── workflows/         # GitHub Actions (optional)
```

---

## 🛠️ Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Language** | Python 3.8+ | Backend logic |
| **Bot Framework** | python-telegram-bot | Telegram API wrapper |
| **Server** | ASGI (Vercel) | Serverless hosting |
| **Storage** | GitHub REST API | Data persistence |
| **Timezone** | pytz / datetime | IST timezone handling |

---

## ⚡ Performance Metrics

| Metric | Value |
|--------|-------|
| **Response Time** | < 2 seconds per command |
| **Memory Usage** | ~50MB per instance |
| **Cold Start** | 1-2 seconds (Vercel) |
| **Data per User** | ~1KB per day |
| **API Calls per Interaction** | 2 (read + write) |
| **Concurrent Users** | Unlimited (serverless) |

---

## 📝 API Reference

### GitHub API Endpoints Used
```
GET  /repos/{owner}/{repo}/contents/{path}
PUT  /repos/{owner}/{repo}/contents/{path}
```

### Telegram Bot Methods Used
```
sendMessage()
editMessageText()
pinChatMessage()
unpinChatMessage()
getChat()
deleteMessage()
answerCallbackQuery()
```

---

## 🚀 Deployment Options

### Option 1: Vercel (Recommended) ⭐
- Easiest setup
- Free tier available
- Auto-deploys on push
- See [Quick Start](#-quick-start)

### Option 2: Heroku
```bash
heroku create your-app-name
git push heroku main
heroku config:set BOT_TOKEN=... GITHUB_TOKEN=... GITHUB_REPO=...
```

### Option 3: Self-Hosted
```bash
python -m uvicorn asgi:app --host 0.0.0.0 --port 8000
```

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

```
MIT License

Copyright (c) 2026 Epoch Helper Bot

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. **Fork the Repository**
   ```bash
   git clone https://github.com/yourusername/epoch-helper-bot.git
   ```

2. **Create a Feature Branch**
   ```bash
   git checkout -b feature/amazing-feature
   ```

3. **Make Your Changes**
   - Follow Python PEP 8 style guide
   - Add comments for complex logic
   - Test thoroughly

4. **Commit Changes**
   ```bash
   git commit -m "Add amazing feature"
   ```

5. **Push to Branch**
   ```bash
   git push origin feature/amazing-feature
   ```

6. **Open a Pull Request**
   - Describe changes clearly
   - Reference any related issues
   - Request review

---

## 📞 Support & Contact

- **Issues**: [Open GitHub Issue](https://github.com/yourusername/epoch-helper-bot/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/epoch-helper-bot/discussions)
- **Telegram**: Direct message bot owner
- **Email**: your.email@example.com

---

## 🎉 Changelog

### v1.0.0 (2026-04-23)
- ✅ Initial release
- ✅ Real-time pinned dashboard
- ✅ 24h 55m daily reset cycle
- ✅ Continuous cycling support
- ✅ Daily analytics and history
- ✅ GitHub-based data storage
- ✅ Manual time setting
- ✅ Group chat support

---

## 🌟 Credits

Created for efficient epoch tracking with persistent analytics.

**Built with:**
- ❤️ Python
- 🤖 Telegram Bot API
- 📊 GitHub
- ☁️ Vercel

---

## 📊 Star History

If you find this project useful, please give it a ⭐!

---

**Last Updated**: April 2026  
**Status**: Active & Maintained  
**Python Version**: 3.8+
