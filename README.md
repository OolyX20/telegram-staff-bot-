# Telegram Staff Activity Bot

This bot monitors staff activity 24/7 with a daily shared limit of 60 minutes per staff member.

## Security Model

- The bot now uses stored roles:
  - `owner`
  - `admin`
  - `staff`
  - `blocked`
- In the group:
  - Telegram `owner` is auto-detected as `owner`
  - Telegram `admin` is auto-detected as `admin`
  - normal group members are auto-detected as `staff`
- Only the `owner` can manage security and change roles.
- Admins can use reports, but cannot approve users or change access.
- Staff can only use staff activity functions.

## Features

- Each staff member can only `⏱️ Time In` once per day.
- The only activities are `☕ Break`, `🚬 Smoke`, and `🚻 CR`.
- `📅 Rest Day` is not an activity. It marks the staff member as off for tomorrow and also ends the current shift.
- `🏁 Time Out` ends the active activity and means the staff member is still scheduled to work the next day.
- Staff receive a button-by-button tutorial when they use `/start`.
- The bot generates an HTML report every day at `1:00 AM` for the previous day and sends it only to owner/admin accounts.
- Admin-only reports:
  - `📥 Collect Data` or `/collect`
  - `📑 Cutoff Report` or `/cutoff YYYY-MM-DD YYYY-MM-DD`

## Interface Separation

- Staff only see the Staff Dashboard.
- Admins and owners use a separate Admin Panel.
- The owner also gets a Security option for access management.

## Owner Commands

- `/security`
- `/setrole <@username> <staff|admin|blocked>`
- `/users`

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
OWNER_ID=123456789
ADMIN_IDS=987654321
SUPERVISOR_CHAT_ID=-1001234567890
```

## Notes

- `OWNER_ID` is required for owner-only security management.
- `ADMIN_IDS` is optional bootstrap data. The owner can later change roles with `/setrole`.
- Users should have a Telegram username if you want to manage their role with `/setrole`.
- `SHIFT_START_TIME` is used for late-minute calculation in cutoff reports.
- Cutoff reports are accurate for shift records created after the cutoff-report feature was added.
