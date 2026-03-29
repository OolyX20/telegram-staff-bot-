# Telegram Staff Activity Bot

This bot monitors staff activity 24/7 with a daily shared limit of 60 minutes per staff member.

## Features

- Tracks staff by Telegram user ID, so it works in private chat or group chat.
- Daily total activity allowance: 60 minutes per non-admin staff member.
- Activities continue running until staff press `🔙 Back`.
- `⏱️ Time In` is required before any activity can start.
- `🔙 Back` ends the active activity and sends that activity summary plus the daily summary.
- `🏁 Time Out` ends the active activity and sends the summary report.
- The bot sends a reminder every 30 seconds if an activity is still running.
- If staff go beyond 60 minutes total for the day, the summary highlights the exceeded time.
- Admins are auto-detected and are not monitored as staff.
- Admin-only commands:
  - `/report` for all non-admin staff
  - `/active` for currently active staff
- Optional automatic alerts to a supervisor chat.

## Setup

1. Install Python 3.11+.
2. Create and activate a virtual environment.
3. Install dependencies:

```powershell
pip install -r requirements.txt
```

4. Update `.env` with your real values.
5. Run the bot:

```powershell
python bot.py
```

## Environment

```env
TELEGRAM_BOT_TOKEN=your-bot-token
TIMEZONE=Asia/Manila
DATABASE_PATH=staff_activity.db
DAILY_LIMIT_MINUTES=60
AUTO_CLOSE_CHECK_SECONDS=30
ADMIN_IDS=123456789,987654321
SUPERVISOR_CHAT_ID=-1001234567890
```

## Commands

- `/start`
- `/status`
- `/report`
- `/active`
- `/timein`
- `/timeout`

## Notes

- `ADMIN_IDS` is optional. In groups, Telegram group admins are also treated as admins automatically.
- `SUPERVISOR_CHAT_ID` is optional. If set, the bot sends alerts for time in, time out, activity start, and activity end.
- The bot stores data locally in `staff_activity.db`.
