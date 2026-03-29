# Telegram Staff Activity Bot

This bot monitors staff activity 24/7 with a daily shared limit of 60 minutes per staff member.

## Role Model

- In the group:
  - Telegram `owner` is auto-detected as `owner`
  - Telegram `admin` is auto-detected as `admin`
  - normal group members are auto-detected as `staff`
- Staff can only use staff activity functions.
- Only `owner` and `admin` accounts can use report tools.

## Features

- Each staff member can only `⏱️ Time In` once per day.
- The main dashboard buttons are `⏱️ Time In`, `🏁 Time Out`, `☕ Break`, `🚻 CR`, `📅 Rest Day`, `🔙 Back`, and `🛠 Admin Panel`.
- `📅 Rest Day` is not an activity. It marks the staff member as off for tomorrow and also ends the current shift.
- `🏁 Time Out` ends the active activity and means the staff member is still scheduled to work the next day.
- Staff receive a button-by-button tutorial when they use `/start`.
- The bot generates an HTML report every day at `1:00 AM` for the previous day and sends it only to owner/admin accounts.
- Admin-only reports:
  - `📥 Collect Data` or `/collect`
  - `📑 Cutoff Report` or `/cutoff YYYY-MM-DD YYYY-MM-DD`, with full per-staff chronological records for the selected period plus days worked, rest days, and absences

## Interface Separation

- Staff only see the Staff Dashboard.
- Admins and owners use a separate Admin Panel.
- The `🛠 Admin Panel` button opens `📊 Status`, `📥 Collect Data`, and `📑 Cutoff Report`.

## Admin Commands

- `/report`
- `/active`
- `/collect`
- `/cutoff YYYY-MM-DD YYYY-MM-DD`

## Staff Commands

- `/start`
- `/status`
- `/timein`
- `/timeout`

## Environment

```env
TELEGRAM_BOT_TOKEN=your-bot-token
TIMEZONE=Asia/Manila
DATABASE_PATH=staff_activity.db
DAILY_LIMIT_MINUTES=60
AUTO_CLOSE_CHECK_SECONDS=30
REPORTS_DIR=reports
SHIFT_START_TIME=09:00
SUPERVISOR_CHAT_ID=-1001234567890
```

## Notes

- `SHIFT_START_TIME` is used for late-minute calculation in cutoff reports.
- Cutoff reports are accurate for shift records created after the cutoff-report feature was added.
- Daily and manual HTML reports are delivered only to accounts currently detected as Telegram group owner/admin.
