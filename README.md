# Telegram Staff Activity Bot

This bot monitors staff activity 24/7 with a daily shared limit of 60 minutes per staff member.

## Features

- Tracks staff by Telegram user ID, so it works in private chat or group chat.
- Daily total activity allowance: 60 minutes per non-admin staff member.
- Each staff member can only `⏱️ Time In` once per day.
- The only activities are `☕ Break`, `🚬 Smoke`, and `🚻 CR`.
- Activities continue running until staff press `🔙 Back`.
- Only one activity can be active at a time. Staff must press `🔙 Back` first before selecting a new activity.
- `⏱️ Time In` is required before any activity can start.
- `📅 Rest Day` is not an activity. It marks the staff member as off for tomorrow and also ends the current shift.
- `🔙 Back` ends the active activity and sends that activity summary plus the daily summary.
- `🏁 Time Out` ends the active activity and means the staff member is still scheduled to work the next day.
- The bot sends a reminder every 30 seconds only after staff exceed the 60-minute daily limit and still have not pressed `🔙 Back`.
- If staff go beyond 60 minutes total for the day, the summary highlights the exceeded time.
- The bot generates an HTML report every day at `1:00 AM` for the previous day, saves it on the server, and sends it only to admin accounts. The report includes `Break`, `Smoke`, `CR`, `Total Used`, and a `Remarks` column for `Rest Day` and exceeded-time notes.
- Admin-only tools:
  - `📥 Collect Data` or `/collect` for an immediate manual HTML report
  - `📑 Cutoff Report` or `/cutoff [start-date] [end-date]` for an alphabetized cutoff summary
- Admins are auto-detected and are not monitored as staff.
- Optional automatic alerts to a supervisor chat.

## Cutoff Report

- The `📑 Cutoff Report` button uses the current month-to-date by default.
- The `/cutoff YYYY-MM-DD YYYY-MM-DD` command can be used for a custom date range.
- Staff names are grouped alphabetically.
- Each line shows:
  - `Days Worked`
  - `Rest Days`
  - `Late` minutes
- Late minutes are calculated from `SHIFT_START_TIME`.

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
REPORTS_DIR=reports
SHIFT_START_TIME=09:00
ADMIN_IDS=123456789,987654321
SUPERVISOR_CHAT_ID=-1001234567890
```

## Commands

- `/start`
- `/status`
- `/report`
- `/active`
- `/collect`
- `/cutoff YYYY-MM-DD YYYY-MM-DD`
- `/timein`
- `/timeout`

## Notes

- `ADMIN_IDS` is required if you want the daily HTML file and cutoff reports sent to admins automatically.
- In groups, Telegram group admins are also treated as admins automatically for command access.
- `SUPERVISOR_CHAT_ID` is optional. If set, the bot sends alerts for time in, time out, activity start, and activity end.
- `REPORTS_DIR` is optional. It controls where HTML reports are saved on the server.
- `SHIFT_START_TIME` is optional. It is used to calculate late minutes in cutoff reports. Default is `09:00`.
- The bot stores data locally in `staff_activity.db`.
- Cutoff reports are accurate for shift records created after this feature was added.
