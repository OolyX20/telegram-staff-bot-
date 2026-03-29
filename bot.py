import logging
import os
import sqlite3
from html import escape
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Set
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import ReplyKeyboardMarkup, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


load_dotenv()

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
LOGGER = logging.getLogger(__name__)

UTC = timezone.utc
LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Manila"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "staff_activity.db")
DAILY_LIMIT_MINUTES = int(os.getenv("DAILY_LIMIT_MINUTES", "60"))
AUTO_CLOSE_CHECK_SECONDS = int(os.getenv("AUTO_CLOSE_CHECK_SECONDS", "30"))
SUPERVISOR_CHAT_ID = os.getenv("SUPERVISOR_CHAT_ID", "").strip()
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "reports"))
SHIFT_START_TIME = os.getenv("SHIFT_START_TIME", "09:00")
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_STAFF = "staff"

TIME_IN_LABEL = "\u23f1\ufe0f Time In"
TIME_OUT_LABEL = "\U0001f3c1 Time Out"
BACK_LABEL = "\U0001f519 Back"
STATUS_LABEL = "\U0001f4ca Status"
COLLECT_DATA_LABEL = "\U0001f4e5 Collect Data"
CUTOFF_REPORT_LABEL = "\U0001f4d1 Cutoff Report"
ADMIN_PANEL_LABEL = "\U0001f6e0 Admin Panel"
STAFF_DASHBOARD_LABEL = "\U0001f465 Staff Dashboard"
NAVIGATION_LABEL = "\U0001f9ed Navigation"
BREAK_LABEL = "\u2615 Break"
CR_SMOKE_LABEL = "\U0001f6bb/\U0001f6ac CR/Smoke"
REST_DAY_LABEL = "\U0001f4c5 Rest Day"


@dataclass(frozen=True)
class Activity:
    key: str
    label: str


ACTIVITIES: Dict[str, Activity] = {
    "break": Activity("break", BREAK_LABEL),
    "cr_smoke": Activity("cr_smoke", CR_SMOKE_LABEL),
}

LABEL_TO_ACTION = {
    TIME_IN_LABEL: "time_in",
    TIME_OUT_LABEL: "time_out",
    BACK_LABEL: "back",
    STATUS_LABEL: "status",
    COLLECT_DATA_LABEL: "collect_data",
    CUTOFF_REPORT_LABEL: "cutoff_report",
    NAVIGATION_LABEL: "staff_dashboard",
    ADMIN_PANEL_LABEL: "admin_panel",
    STAFF_DASHBOARD_LABEL: "staff_dashboard",
    REST_DAY_LABEL: "rest_day",
}
LABEL_TO_ACTION.update({activity.label: activity.key for activity in ACTIVITIES.values()})

STAFF_KEYBOARD = ReplyKeyboardMarkup(
    [
        [TIME_IN_LABEL, TIME_OUT_LABEL],
        [BREAK_LABEL, CR_SMOKE_LABEL],
        [REST_DAY_LABEL],
        [BACK_LABEL, STATUS_LABEL],
    ],
    resize_keyboard=True,
)

ADMIN_PANEL_KEYBOARD = ReplyKeyboardMarkup(
    [
        [STATUS_LABEL, COLLECT_DATA_LABEL],
        [CUTOFF_REPORT_LABEL],
        [NAVIGATION_LABEL],
    ],
    resize_keyboard=True,
)

OWNER_PANEL_KEYBOARD = ReplyKeyboardMarkup(
    [
        [STATUS_LABEL, COLLECT_DATA_LABEL],
        [CUTOFF_REPORT_LABEL],
        [NAVIGATION_LABEL],
    ],
    resize_keyboard=True,
)

ADMIN_STAFF_KEYBOARD = ReplyKeyboardMarkup(
    [
        [TIME_IN_LABEL, TIME_OUT_LABEL],
        [BREAK_LABEL, CR_SMOKE_LABEL],
        [REST_DAY_LABEL],
        [BACK_LABEL, STATUS_LABEL],
        [ADMIN_PANEL_LABEL],
    ],
    resize_keyboard=True,
)


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


def format_minutes(total_seconds: float) -> int:
    return max(0, int(round(total_seconds / 60)))


def format_duration(total_seconds: float) -> str:
    minutes = max(0, int(total_seconds // 60))
    seconds = max(0, int(total_seconds % 60))
    if seconds == 0:
        return f"{minutes} mins"
    return f"{minutes} mins {seconds} secs"


def format_local(timestamp: datetime) -> str:
    return timestamp.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %I:%M:%S %p")


def format_local_date(timestamp: datetime) -> str:
    return timestamp.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")


def next_local_date_string(reference: datetime) -> str:
    return (reference.astimezone(LOCAL_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")


def local_date_string(reference: datetime) -> str:
    return reference.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")


def canonical_activity_key(activity_key: str) -> str:
    if activity_key in {"smoke", "cr"}:
        return "cr_smoke"
    return activity_key


def activity_for_key(activity_key: str) -> Activity:
    return ACTIVITIES[canonical_activity_key(activity_key)]


def month_start(reference: datetime) -> datetime:
    local_reference = reference.astimezone(LOCAL_TZ)
    return local_reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def parse_shift_start_time() -> tuple[int, int]:
    hour_text, minute_text = SHIFT_START_TIME.split(":", 1)
    return int(hour_text), int(minute_text)


def calculate_late_minutes(timestamp: datetime) -> int:
    local_timestamp = timestamp.astimezone(LOCAL_TZ)
    start_hour, start_minute = parse_shift_start_time()
    scheduled = local_timestamp.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )
    late_seconds = max(0.0, (local_timestamp - scheduled).total_seconds())
    return int(late_seconds // 60)


def warning_text(remaining_seconds: float) -> Optional[str]:
    remaining_minutes = format_minutes(remaining_seconds)
    if remaining_seconds < 0:
        return None
    if remaining_minutes <= 0:
        return "WARNING: No remaining activity time left for today."
    if remaining_minutes <= 10:
        return f"WARNING: Only {remaining_minutes} minutes remaining for today."
    return None


def display_name(row: sqlite3.Row) -> str:
    if row["full_name"]:
        return row["full_name"]
    if row["username"]:
        return f"@{row['username']}"
    return f"User {row['user_id']}"


def username_label(row: sqlite3.Row) -> str:
    if row["username"]:
        return f"@{row['username']}"
    return display_name(row)


def normalize_username(value: str) -> str:
    return value.strip().lstrip("@").lower()


def balance_label(remaining_seconds: float) -> str:
    if remaining_seconds >= 0:
        return f"Remaining {format_minutes(remaining_seconds)} mins"
    return f"EXCEEDED {format_minutes(abs(remaining_seconds))} mins"


def role_of(staff: sqlite3.Row) -> str:
    role = staff["role"] if "role" in staff.keys() else None
    if role in {ROLE_OWNER, ROLE_ADMIN, ROLE_STAFF}:
        return role
    return ROLE_ADMIN if staff["is_admin"] else ROLE_STAFF


def has_admin_access(staff: sqlite3.Row) -> bool:
    return role_of(staff) in {ROLE_OWNER, ROLE_ADMIN}


def is_owner(staff: sqlite3.Row) -> bool:
    return role_of(staff) == ROLE_OWNER


async def telegram_admin_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    chat = update.effective_chat
    user_id = update.effective_user.id
    if chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return None

    try:
        member = await context.bot.get_chat_member(chat.id, user_id)
    except Exception:
        LOGGER.exception("Failed to get chat member for role detection")
        return None

    if member.status == ChatMemberStatus.OWNER:
        return ROLE_OWNER
    if member.status == ChatMemberStatus.ADMINISTRATOR:
        return ROLE_ADMIN
    if member.status in {ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED}:
        return ROLE_STAFF
    return None


def keyboard_for_role(staff: sqlite3.Row, panel: str = "staff") -> ReplyKeyboardMarkup:
    role = role_of(staff)
    if role == ROLE_STAFF:
        return STAFF_KEYBOARD
    if panel == "admin":
        return OWNER_PANEL_KEYBOARD if role == ROLE_OWNER else ADMIN_PANEL_KEYBOARD
    return ADMIN_STAFF_KEYBOARD


class ActivityRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._initialize()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS staff (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    role TEXT NOT NULL DEFAULT 'staff',
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    is_timed_in INTEGER NOT NULL DEFAULT 0,
                    shift_start_at TEXT,
                    last_time_out_at TEXT,
                    last_chat_id INTEGER,
                    rest_day_date TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS activity_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    activity_key TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    closed_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES staff(user_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS shift_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    work_date TEXT NOT NULL,
                    time_in_at TEXT NOT NULL,
                    time_out_at TEXT,
                    next_day_status TEXT NOT NULL DEFAULT 'Scheduled',
                    rest_day_effective_date TEXT,
                    late_minutes INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES staff(user_id)
                )
                """
            )
            self._migrate_legacy_schema(conn)
            columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(staff)").fetchall()
            }
            if "rest_day_date" not in columns:
                conn.execute("ALTER TABLE staff ADD COLUMN rest_day_date TEXT")
            if "role" not in columns:
                conn.execute("ALTER TABLE staff ADD COLUMN role TEXT NOT NULL DEFAULT 'staff'")
                conn.execute(
                    """
                    UPDATE staff
                    SET role = CASE
                        WHEN is_admin = 1 THEN ?
                        ELSE ?
                    END
                    """,
                    (ROLE_ADMIN, ROLE_STAFF),
                )

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(staff)").fetchall()
        }
        if "chat_id" in columns and "user_id" not in columns:
            conn.execute("ALTER TABLE staff RENAME TO staff_legacy")
            conn.execute(
                """
                CREATE TABLE staff (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT,
                    role TEXT NOT NULL DEFAULT 'staff',
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    is_timed_in INTEGER NOT NULL DEFAULT 0,
                    shift_start_at TEXT,
                    last_time_out_at TEXT,
                    last_chat_id INTEGER,
                    rest_day_date TEXT
                )
                """
            )
            conn.execute(
                """
                INSERT INTO staff (user_id, username, full_name, role, is_timed_in, shift_start_at, last_time_out_at, last_chat_id)
                SELECT chat_id, username, full_name,
                       '{staff_role}',
                       is_timed_in, shift_start_at, last_time_out_at, chat_id
                FROM staff_legacy
                """.format(
                    staff_role=ROLE_STAFF,
                )
            )
            conn.execute("DROP TABLE staff_legacy")

        session_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(activity_sessions)").fetchall()
        }
        if "user_id" not in session_columns:
            conn.execute("ALTER TABLE activity_sessions RENAME TO activity_sessions_legacy")
            conn.execute(
                """
                CREATE TABLE activity_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    activity_key TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    closed_reason TEXT,
                    FOREIGN KEY (user_id) REFERENCES staff(user_id)
                )
                """
            )
            conn.execute(
                """
                INSERT INTO activity_sessions (id, user_id, chat_id, activity_key, started_at, ended_at, closed_reason)
                SELECT id, chat_id, chat_id, activity_key, started_at, ended_at, closed_reason
                FROM activity_sessions_legacy
                """
            )
            conn.execute("DROP TABLE activity_sessions_legacy")

    def upsert_staff(self, user_id: int, username: str, full_name: str, last_chat_id: int) -> None:
        default_role = ROLE_STAFF
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO staff (user_id, username, full_name, role, is_admin, last_chat_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    role = staff.role,
                    is_admin = CASE
                        WHEN staff.role IN (?, ?) THEN 1
                        ELSE 0
                    END,
                    last_chat_id = excluded.last_chat_id
                """,
                (
                    user_id,
                    username,
                    full_name,
                    default_role,
                    int(default_role in {ROLE_OWNER, ROLE_ADMIN}),
                    last_chat_id,
                    ROLE_OWNER,
                    ROLE_ADMIN,
                ),
            )

    def set_role(self, user_id: int, role: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE staff
                SET role = ?, is_admin = ?
                WHERE user_id = ?
                """,
                (role, int(role in {ROLE_OWNER, ROLE_ADMIN}), user_id),
            )

    def get_users_by_roles(self, roles: tuple[str, ...]):
        placeholders = ",".join("?" for _ in roles)
        with self.connection() as conn:
            return conn.execute(
                f"SELECT * FROM staff WHERE role IN ({placeholders}) ORDER BY full_name, username, user_id",
                roles,
            ).fetchall()

    def get_staff(self, user_id: int) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM staff WHERE user_id = ?",
                (user_id,),
            ).fetchone()

    def get_staff_by_username(self, username: str) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM staff WHERE LOWER(username) = ?",
                (normalize_username(username),),
            ).fetchone()

    def get_all_staff(self):
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM staff ORDER BY full_name, username, user_id"
            ).fetchall()

    def set_time_in(self, user_id: int, chat_id: int, at: datetime) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE staff
                SET is_timed_in = 1, shift_start_at = ?, last_chat_id = ?
                WHERE user_id = ?
                """,
                (at.isoformat(), chat_id, user_id),
            )
            conn.execute(
                """
                INSERT INTO shift_records (user_id, chat_id, work_date, time_in_at, late_minutes)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    chat_id,
                    local_date_string(at),
                    at.isoformat(),
                    calculate_late_minutes(at),
                ),
            )

    def set_time_out(self, user_id: int, chat_id: int, at: datetime) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE staff
                SET is_timed_in = 0, shift_start_at = NULL, last_time_out_at = ?, last_chat_id = ?, rest_day_date = NULL
                WHERE user_id = ?
                """,
                (at.isoformat(), chat_id, user_id),
            )
            conn.execute(
                """
                UPDATE shift_records
                SET time_out_at = ?, next_day_status = 'Scheduled', rest_day_effective_date = NULL
                WHERE user_id = ? AND work_date = ? AND time_out_at IS NULL
                """,
                (at.isoformat(), user_id, local_date_string(at)),
            )

    def set_rest_day_and_time_out(self, user_id: int, chat_id: int, at: datetime, rest_day_date: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE staff
                SET is_timed_in = 0,
                    shift_start_at = NULL,
                    last_time_out_at = ?,
                    last_chat_id = ?,
                    rest_day_date = ?
                WHERE user_id = ?
                """,
                (at.isoformat(), chat_id, rest_day_date, user_id),
            )
            conn.execute(
                """
                UPDATE shift_records
                SET time_out_at = ?,
                    next_day_status = 'Rest Day',
                    rest_day_effective_date = ?
                WHERE user_id = ? AND work_date = ? AND time_out_at IS NULL
                """,
                (at.isoformat(), rest_day_date, user_id, local_date_string(at)),
            )

    def get_active_session(self, user_id: int) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT * FROM activity_sessions
                WHERE user_id = ? AND ended_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

    def get_all_active_sessions(self):
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT s.*, st.full_name, st.username
                FROM activity_sessions s
                JOIN staff st ON st.user_id = s.user_id
                WHERE s.ended_at IS NULL
                ORDER BY s.started_at ASC
                """
            ).fetchall()

    def start_activity(
        self,
        user_id: int,
        chat_id: int,
        activity_key: str,
        started_at: datetime,
    ) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO activity_sessions (user_id, chat_id, activity_key, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, chat_id, activity_key, started_at.isoformat()),
            )
            conn.execute(
                "UPDATE staff SET last_chat_id = ? WHERE user_id = ?",
                (chat_id, user_id),
            )
            return int(cursor.lastrowid)

    def end_activity(self, session_id: int, ended_at: datetime, reason: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE activity_sessions
                SET ended_at = ?, closed_reason = ?
                WHERE id = ? AND ended_at IS NULL
                """,
                (ended_at.isoformat(), reason, session_id),
            )

    def get_sessions_for_day(self, user_id: int, day_start: datetime, day_end: datetime):
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT * FROM activity_sessions
                WHERE user_id = ?
                  AND started_at < ?
                  AND COALESCE(ended_at, ?) > ?
                ORDER BY started_at ASC
                """,
                (
                    user_id,
                    day_end.isoformat(),
                    utc_now().isoformat(),
                    day_start.isoformat(),
                ),
            ).fetchall()

    def get_staff_for_day(self, day_start: datetime, day_end: datetime):
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT * FROM staff
                WHERE (shift_start_at IS NOT NULL AND shift_start_at >= ? AND shift_start_at < ?)
                   OR (last_time_out_at IS NOT NULL AND last_time_out_at >= ? AND last_time_out_at < ?)
                ORDER BY full_name, username, user_id
                """,
                (
                    day_start.isoformat(),
                    day_end.isoformat(),
                    day_start.isoformat(),
                    day_end.isoformat(),
                ),
            ).fetchall()

    def get_shift_records_for_range(self, start_date: str, end_date: str):
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT sr.*, st.full_name, st.username
                FROM shift_records sr
                JOIN staff st ON st.user_id = sr.user_id
                WHERE sr.work_date >= ? AND sr.work_date <= ?
                ORDER BY st.full_name, st.username, sr.work_date
                """,
                (start_date, end_date),
            ).fetchall()

    def get_staff_for_cutoff_range(self, start_date: str, end_date: str):
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT DISTINCT st.*
                FROM shift_records sr
                JOIN staff st ON st.user_id = sr.user_id
                WHERE (sr.work_date >= ? AND sr.work_date <= ?)
                   OR (sr.rest_day_effective_date IS NOT NULL AND sr.rest_day_effective_date >= ? AND sr.rest_day_effective_date <= ?)
                ORDER BY st.full_name, st.username, st.user_id
                """,
                (start_date, end_date, start_date, end_date),
            ).fetchall()


class ActivityService:
    def __init__(self, repository: ActivityRepository) -> None:
        self.repository = repository

    def register_user(self, update: Update) -> sqlite3.Row:
        user = update.effective_user
        self.repository.upsert_staff(
            user_id=user.id,
            username=user.username or "",
            full_name=" ".join(part for part in [user.first_name, user.last_name] if part),
            last_chat_id=update.effective_chat.id,
        )
        return self.repository.get_staff(user.id)

    def _day_bounds(self, reference: Optional[datetime] = None):
        current = (reference or utc_now()).astimezone(LOCAL_TZ)
        start_local = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        return start_local.astimezone(UTC), end_local.astimezone(UTC)

    def _session_seconds_within_day(
        self,
        session: sqlite3.Row,
        day_start: datetime,
        day_end: datetime,
        now: datetime,
    ) -> float:
        started_at = datetime.fromisoformat(session["started_at"])
        ended_at = parse_iso(session["ended_at"]) or now
        clamped_start = max(started_at, day_start)
        clamped_end = min(ended_at, day_end)
        seconds = (clamped_end - clamped_start).total_seconds()
        return max(0.0, seconds)

    def get_day_usage(self, user_id: int) -> Dict[str, float]:
        day_start, day_end = self._day_bounds()
        now = utc_now()
        usage = {key: 0.0 for key in ACTIVITIES}
        sessions = self.repository.get_sessions_for_day(user_id, day_start, day_end)
        for session in sessions:
            activity_key = canonical_activity_key(session["activity_key"])
            if activity_key not in usage:
                continue
            usage[activity_key] += self._session_seconds_within_day(
                session, day_start, day_end, now
            )
        return usage

    def total_used_seconds(self, user_id: int) -> float:
        return sum(self.get_day_usage(user_id).values())

    def remaining_seconds(self, user_id: int) -> float:
        return DAILY_LIMIT_MINUTES * 60 - self.total_used_seconds(user_id)

    def summary_lines(self, user_id: int) -> Iterable[str]:
        usage = self.get_day_usage(user_id)
        total_used = sum(usage.values())
        remaining = self.remaining_seconds(user_id)
        lines = ["\u23f1\ufe0f Activity Summary"]
        for activity in ACTIVITIES.values():
            lines.append(f"{activity.label:<12} = {format_minutes(usage[activity.key])} mins")
        lines.append("-------------------------")
        lines.append(f"Total Used   = {format_minutes(total_used)} mins")
        if remaining >= 0:
            lines.append(f"Remaining    = {format_minutes(remaining)} mins")
            warning = warning_text(remaining)
            if warning:
                lines.append(warning)
        else:
            lines.append(f"EXCEEDED BY  = {format_minutes(abs(remaining))} mins")
            lines.append("WARNING: Staff exceeded the 60-minute daily activity limit.")
        return lines

    def summary_text(self, user_id: int) -> str:
        return "\n".join(self.summary_lines(user_id))

    def day_summary(self, user_id: int, reference: datetime):
        day_start, day_end = self._day_bounds(reference)
        usage = {key: 0.0 for key in ACTIVITIES}
        sessions = self.repository.get_sessions_for_day(user_id, day_start, day_end)
        for session in sessions:
            activity_key = canonical_activity_key(session["activity_key"])
            if activity_key not in usage:
                continue
            usage[activity_key] += self._session_seconds_within_day(
                session, day_start, day_end, day_end
            )

        total_used = sum(usage.values())
        remaining = DAILY_LIMIT_MINUTES * 60 - total_used
        return {
            "day_start": day_start,
            "day_end": day_end,
            "usage": usage,
            "total_used": total_used,
            "remaining": remaining,
        }

    def has_timed_in_today(self, staff: sqlite3.Row) -> bool:
        shift_start = parse_iso(staff["shift_start_at"])
        last_time_out = parse_iso(staff["last_time_out_at"])
        reference = shift_start or last_time_out
        if not reference:
            return False

        day_start, day_end = self._day_bounds()
        return day_start <= reference < day_end

    def report_text(self) -> str:
        staff_rows = self.repository.get_all_staff()
        lines = ["\U0001f4cb Staff Report"]
        found_staff = False
        for staff in staff_rows:
            if staff["is_admin"]:
                continue
            found_staff = True
            active = self.repository.get_active_session(staff["user_id"])
            status = "Timed In" if staff["is_timed_in"] else "Timed Out"
            if active:
                status = f"Active: {activity_for_key(active['activity_key']).label}"
            balance = self.remaining_seconds(staff["user_id"])
            lines.append(
                f"{display_name(staff)} | {status} | Used {format_minutes(self.total_used_seconds(staff['user_id']))} mins | {balance_label(balance)}"
            )
        if not found_staff:
            lines.append("No non-admin staff records yet.")
        return "\n".join(lines)

    def active_staff_text(self) -> str:
        sessions = self.repository.get_all_active_sessions()
        lines = ["\U0001f50d Active Staff"]
        found_staff = False
        for session in sessions:
            staff = self.repository.get_staff(session["user_id"])
            if not staff or staff["is_admin"]:
                continue
            found_staff = True
            lines.append(
                f"{display_name(staff)} | {activity_for_key(session['activity_key']).label} | Started {format_local(datetime.fromisoformat(session['started_at']))}"
            )
        if not found_staff:
            lines.append("No staff are in an activity right now.")
        return "\n".join(lines)

    def build_daily_html_report(self, reference: datetime, filename_prefix: str = "staff-report") -> Path:
        day_start, day_end = self._day_bounds(reference)
        report_date = format_local_date(day_start)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"{filename_prefix}-{report_date}.html"

        rows = []
        for staff in self.repository.get_staff_for_day(day_start, day_end):
            if staff["is_admin"]:
                continue

            summary = self.day_summary(staff["user_id"], day_start)
            shift_start = parse_iso(staff["shift_start_at"])
            last_time_out = parse_iso(staff["last_time_out_at"])
            time_in_value = (
                format_local(shift_start)
                if shift_start and day_start <= shift_start < day_end
                else "N/A"
            )
            time_out_value = (
                format_local(last_time_out)
                if last_time_out and day_start <= last_time_out < day_end
                else "NOT TIMED OUT"
            )
            balance_value = (
                ""
                if summary["remaining"] >= 0
                else f"Exceeded by {format_minutes(abs(summary['remaining']))} mins"
            )
            tomorrow_date = next_local_date_string(day_start)
            remarks = []
            if staff["rest_day_date"] == tomorrow_date:
                remarks.append("Rest Day")
            if balance_value:
                remarks.append(balance_value)
            remarks_value = ", ".join(remarks) if remarks else "-"
            row_class = "exceeded" if summary["remaining"] < 0 else ""
            rows.append(
                f"""
                <tr class="{row_class}">
                    <td>{escape(display_name(staff))}</td>
                    <td>{escape(time_in_value)}</td>
                    <td>{escape(time_out_value)}</td>
                    <td>{format_minutes(summary['usage']['break'])} mins</td>
                    <td>{format_minutes(summary['usage']['cr_smoke'])} mins</td>
                    <td>{format_minutes(summary['total_used'])} mins</td>
                    <td>{escape(remarks_value)}</td>
                </tr>
                """
            )

        if not rows:
            rows.append(
                """
                <tr>
                    <td colspan="8">No staff activity found for this date.</td>
                </tr>
                """
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Staff Activity Report - {report_date}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 24px;
            color: #1f2937;
            background: #f8fafc;
        }}
        h1 {{
            margin-bottom: 8px;
        }}
        p {{
            margin-top: 0;
            color: #475569;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: #ffffff;
        }}
        th, td {{
            border: 1px solid #cbd5e1;
            padding: 10px;
            text-align: left;
        }}
        th {{
            background: #e2e8f0;
        }}
        tr.exceeded {{
            background: #fee2e2;
        }}
    </style>
</head>
<body>
    <h1>Staff Activity Report</h1>
    <p>Report date: {report_date}</p>
    <table>
        <thead>
            <tr>
                <th>Staff</th>
                <th>Time In</th>
                <th>Time Out</th>
                <th>Break</th>
                <th>CR/Smoke</th>
                <th>Total Used</th>
                <th>Remarks</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows)}
        </tbody>
    </table>
</body>
</html>
"""
        report_path.write_text(html, encoding="utf-8")
        os.chmod(report_path, 0o444)
        return report_path

    def build_cutoff_html_report(
        self,
        start_date: str,
        end_date: str,
        filename_prefix: str = "cutoff-report",
    ) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"{filename_prefix}-{start_date}-to-{end_date}.html"
        grouped: Dict[str, list[str]] = {}
        shift_rows = self.repository.get_shift_records_for_range(start_date, end_date)

        for staff in self.repository.get_staff_for_cutoff_range(start_date, end_date):
            if staff["is_admin"]:
                continue

            staff_shift_rows = [
                row
                for row in shift_rows
                if row["user_id"] == staff["user_id"]
            ]
            days_worked = len({row["work_date"] for row in staff_shift_rows})
            rest_days = len(
                {
                    row["rest_day_effective_date"]
                    for row in staff_shift_rows
                    if row["rest_day_effective_date"]
                    and start_date <= row["rest_day_effective_date"] <= end_date
                }
            )
            late_minutes = sum(int(row["late_minutes"] or 0) for row in staff_shift_rows)
            name = display_name(staff)
            letter = name[0].upper() if name and name[0].isalpha() else "#"
            grouped.setdefault(letter, []).append(
                f"{escape(name)}  Days Worked: {days_worked} / Rest Days: {rest_days} / Late: {late_minutes} minutes"
            )

        sections = []
        for letter in sorted(grouped):
            items = "".join(f"<li>{line}</li>" for line in grouped[letter])
            sections.append(
                f"""
                <section>
                    <h2>{letter}</h2>
                    <ul>{items}</ul>
                </section>
                """
            )

        if not sections:
            sections.append(
                """
                <section>
                    <p>No staff records found for this cutoff period.</p>
                </section>
                """
            )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cutoff Report - {start_date} to {end_date}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 24px;
            color: #1f2937;
            background: #f8fafc;
        }}
        h1 {{
            margin-bottom: 8px;
        }}
        h2 {{
            margin-top: 24px;
            border-bottom: 1px solid #cbd5e1;
            padding-bottom: 4px;
        }}
        ul {{
            list-style: none;
            padding-left: 0;
        }}
        li {{
            background: #ffffff;
            border: 1px solid #cbd5e1;
            padding: 12px;
            margin-bottom: 10px;
        }}
    </style>
</head>
<body>
    <h1>Cutoff Report</h1>
    <p>Cutoff period: {start_date} to {end_date}</p>
    {''.join(sections)}
</body>
</html>
"""
        report_path.write_text(html, encoding="utf-8")
        os.chmod(report_path, 0o444)
        return report_path


REPOSITORY = ActivityRepository(DATABASE_PATH)
SERVICE = ActivityService(REPOSITORY)


async def ensure_registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> sqlite3.Row:
    staff = SERVICE.register_user(update)
    detected_role = await telegram_admin_role(update, context)
    final_role = detected_role or role_of(staff)
    if role_of(staff) != final_role:
        REPOSITORY.set_role(staff["user_id"], final_role)
        staff = REPOSITORY.get_staff(staff["user_id"])
    return staff


def monitoring_block_message() -> str:
    return (
        "Monitoring is automatically applied to non-admin staff only.\n"
        "This account is detected as admin, so activity tracking is disabled."
    )


async def send_supervisor_alert(context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    if not SUPERVISOR_CHAT_ID:
        return
    try:
        await context.bot.send_message(chat_id=int(SUPERVISOR_CHAT_ID), text=text)
    except Exception:
        LOGGER.exception("Failed to send supervisor alert")


async def send_html_report_document(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    report_path: Path,
    caption: str,
) -> None:
    with report_path.open("rb") as report_file:
        await context.bot.send_document(
            chat_id=chat_id,
            document=report_file,
            filename=report_path.name,
            caption=caption,
        )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    role = role_of(staff)
    if has_admin_access(staff):
        lines = [
            "Admin panel is ready." if role == ROLE_ADMIN else "Owner panel is ready.",
            "",
            "Admin controls are separated from the staff dashboard.",
            "Button guide:",
            f"{STATUS_LABEL} - Show the current live admin summary.",
            f"{COLLECT_DATA_LABEL} - Generate and send the daily HTML report to your private chat.",
            f"{CUTOFF_REPORT_LABEL} - Generate the cutoff summary report for the selected period.",
            f"{NAVIGATION_LABEL} - Open the staff dashboard view.",
        ]
        await update.message.reply_text("\n".join(lines), reply_markup=keyboard_for_role(staff, "admin"))
    else:
        lines = [
            "Staff activity monitor is ready.",
            "",
            f"Daily total activity allowance: {DAILY_LIMIT_MINUTES} minutes",
            "Button guide:",
            f"{TIME_IN_LABEL} - Start your shift. You can only use this once per day.",
            f"{TIME_OUT_LABEL} - End your shift. This means you are still scheduled to work tomorrow.",
            f"{BREAK_LABEL} - Start your break activity.",
            f"{CR_SMOKE_LABEL} - Start your combined CR/Smoke activity.",
            f"{REST_DAY_LABEL} - Mark that your day off is tomorrow and end your shift.",
            f"{BACK_LABEL} - Stop the current activity and send your activity summary.",
            f"{STATUS_LABEL} - Show your current daily activity summary.",
            "",
            "Activities keep running until you press Back.",
            "Only one activity can be active at a time.",
        ]
        await update.message.reply_text("\n".join(lines), reply_markup=keyboard_for_role(staff))


async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if not has_admin_access(staff):
        await update.message.reply_text("Only admins can access the Admin Panel.", reply_markup=keyboard_for_role(staff))
        return
    await update.message.reply_text(
        "Admin controls are separate from the staff dashboard.\nChoose an admin action below.",
        reply_markup=keyboard_for_role(staff, "admin"),
    )


async def staff_dashboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if not has_admin_access(staff):
        await update.message.reply_text("You are already in the staff dashboard.", reply_markup=keyboard_for_role(staff))
        return
    await update.message.reply_text(
        "Staff dashboard opened.\nAdmin controls are hidden until you return to the Admin Panel.",
        reply_markup=keyboard_for_role(staff, "staff"),
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if has_admin_access(staff):
        text = f"{SERVICE.active_staff_text()}\n\n{SERVICE.report_text()}"
        await update.message.reply_text(text, reply_markup=keyboard_for_role(staff, "admin"))
        return

    active = REPOSITORY.get_active_session(staff["user_id"])
    text = SERVICE.summary_text(staff["user_id"])
    if active:
        activity = activity_for_key(active["activity_key"])
        started_at = datetime.fromisoformat(active["started_at"])
        running_seconds = (utc_now() - started_at).total_seconds()
        text = (
            f"{text}\n\nCurrent Activity: {activity.label}\n"
            f"Started: {format_local(started_at)}\n"
            f"Running Time: {format_duration(running_seconds)}"
        )
    await update.message.reply_text(text, reply_markup=keyboard_for_role(staff))


async def report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if not has_admin_access(staff):
        await update.message.reply_text("Only admins can use /report.", reply_markup=keyboard_for_role(staff))
        return
    await update.message.reply_text(SERVICE.report_text(), reply_markup=keyboard_for_role(staff, "admin"))


async def active_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if not has_admin_access(staff):
        await update.message.reply_text("Only admins can use /active.", reply_markup=keyboard_for_role(staff))
        return
    await update.message.reply_text(SERVICE.active_staff_text(), reply_markup=keyboard_for_role(staff, "admin"))


async def collect_data_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if not has_admin_access(staff):
        await update.message.reply_text("Only admins can use Collect Data.", reply_markup=keyboard_for_role(staff))
        return

    report_path = SERVICE.build_daily_html_report(utc_now(), filename_prefix="staff-report-manual")
    report_date = format_local_date(utc_now())
    try:
        await send_html_report_document(
            context,
            chat_id=staff["user_id"],
            report_path=report_path,
            caption=f"Manual staff HTML report for {report_date}",
        )
        await update.message.reply_text(
            "Collect Data completed. The HTML report was sent privately to your admin account.",
            reply_markup=keyboard_for_role(staff, "admin"),
        )
    except Exception:
        LOGGER.exception("Failed to send manual HTML report to admin %s", staff["user_id"])
        await update.message.reply_text(
            "Collect Data failed. Start a private chat with the bot first, then try again.",
            reply_markup=keyboard_for_role(staff, "admin"),
        )


async def cutoff_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if not has_admin_access(staff):
        await update.message.reply_text("Only admins can use Cutoff Report.", reply_markup=keyboard_for_role(staff))
        return

    args = getattr(context, "args", []) or []
    if len(args) == 2:
        start_date, end_date = args
    else:
        now = utc_now()
        start_date = format_local_date(month_start(now))
        end_date = format_local_date(now)

    report_path = SERVICE.build_cutoff_html_report(start_date, end_date)
    try:
        await send_html_report_document(
            context,
            chat_id=staff["user_id"],
            report_path=report_path,
            caption=f"Cutoff report for {start_date} to {end_date}",
        )
        await update.message.reply_text(
            f"Cutoff Report completed for {start_date} to {end_date}. The HTML file was sent privately to your admin account.",
            reply_markup=keyboard_for_role(staff, "admin"),
        )
    except Exception:
        LOGGER.exception("Failed to send cutoff report to admin %s", staff["user_id"])
        await update.message.reply_text(
            "Cutoff Report failed. Start a private chat with the bot first, then try again.",
            reply_markup=keyboard_for_role(staff, "admin"),
        )


async def rest_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if role_of(staff) != ROLE_STAFF:
        await update.message.reply_text(monitoring_block_message(), reply_markup=keyboard_for_role(staff, "staff"))
        return
    if not staff["is_timed_in"]:
        await update.message.reply_text(
            "You must Time In before selecting Rest Day.",
            reply_markup=keyboard_for_role(staff),
        )
        return

    now = utc_now()
    active = REPOSITORY.get_active_session(staff["user_id"])
    if active:
        REPOSITORY.end_activity(active["id"], now, "rest_day")

    rest_day_date = next_local_date_string(now)
    REPOSITORY.set_rest_day_and_time_out(
        staff["user_id"],
        update.effective_chat.id,
        now,
        rest_day_date,
    )
    summary = SERVICE.summary_text(staff["user_id"])
    await update.message.reply_text(
        f"{REST_DAY_LABEL} selected.\n"
        f"You are marked as Rest Day for {rest_day_date}.\n"
        f"{TIME_OUT_LABEL} recorded at {format_local(now)}.\n\n{summary}",
        reply_markup=keyboard_for_role(staff),
    )
    await send_supervisor_alert(
        context,
        f"{display_name(staff)} selected Rest Day for {rest_day_date} and timed out at {format_local(now)}.",
    )


async def time_in(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if role_of(staff) != ROLE_STAFF:
        await update.message.reply_text(monitoring_block_message(), reply_markup=keyboard_for_role(staff, "staff"))
        return
    if staff["is_timed_in"]:
        await update.message.reply_text("You are already timed in.", reply_markup=keyboard_for_role(staff))
        return
    if SERVICE.has_timed_in_today(staff):
        await update.message.reply_text(
            "You already used your one Time In for today.\nPlease wait until the next day before timing in again.",
            reply_markup=keyboard_for_role(staff),
        )
        return

    now = utc_now()
    REPOSITORY.set_time_in(staff["user_id"], update.effective_chat.id, now)
    await update.message.reply_text(
        f"{TIME_IN_LABEL} recorded at {format_local(now)}.",
        reply_markup=keyboard_for_role(staff),
    )
    await send_supervisor_alert(
        context,
        f"{display_name(staff)} timed in at {format_local(now)}.",
    )


async def time_out(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if role_of(staff) != ROLE_STAFF:
        await update.message.reply_text(monitoring_block_message(), reply_markup=keyboard_for_role(staff, "staff"))
        return
    if not staff["is_timed_in"]:
        await update.message.reply_text("You are not currently timed in.", reply_markup=keyboard_for_role(staff))
        return

    active = REPOSITORY.get_active_session(staff["user_id"])
    now = utc_now()
    if active:
        REPOSITORY.end_activity(active["id"], now, "time_out")

    REPOSITORY.set_time_out(staff["user_id"], update.effective_chat.id, now)
    summary = SERVICE.summary_text(staff["user_id"])
    await update.message.reply_text(
        f"{TIME_OUT_LABEL} recorded at {format_local(now)}.\n\n{summary}",
        reply_markup=keyboard_for_role(staff),
    )
    await send_supervisor_alert(
        context,
        f"{display_name(staff)} timed out at {format_local(now)}.\n\n{summary}",
    )


async def back_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    staff = await ensure_registered(update, context)
    if role_of(staff) != ROLE_STAFF:
        await update.message.reply_text(monitoring_block_message(), reply_markup=keyboard_for_role(staff, "staff"))
        return

    active = REPOSITORY.get_active_session(staff["user_id"])
    if not active:
        await update.message.reply_text("No active activity to stop.", reply_markup=keyboard_for_role(staff))
        return

    now = utc_now()
    REPOSITORY.end_activity(active["id"], now, "manual_back")
    activity = activity_for_key(active["activity_key"])
    duration_seconds = (now - datetime.fromisoformat(active["started_at"])).total_seconds()
    text = (
        f"{BACK_LABEL} {activity.label} ended.\n"
        f"Activity Summary: {activity.label}\n"
        f"Used this session: {format_duration(duration_seconds)}\n\n"
        f"{SERVICE.summary_text(staff['user_id'])}"
    )
    await update.message.reply_text(text, reply_markup=keyboard_for_role(staff))
    await send_supervisor_alert(
        context,
        f"{display_name(staff)} ended {activity.label} after {format_duration(duration_seconds)}.",
    )


async def start_activity(update: Update, context: ContextTypes.DEFAULT_TYPE, activity_key: str) -> None:
    staff = await ensure_registered(update, context)
    if role_of(staff) != ROLE_STAFF:
        await update.message.reply_text(monitoring_block_message(), reply_markup=keyboard_for_role(staff, "staff"))
        return
    if not staff["is_timed_in"]:
        await update.message.reply_text(
            "You must Time In before starting an activity.",
            reply_markup=keyboard_for_role(staff),
        )
        return

    active = REPOSITORY.get_active_session(staff["user_id"])
    if active:
        current = activity_for_key(active["activity_key"])
        await update.message.reply_text(
            f"{current.label} is still active.\nPress {BACK_LABEL} first before selecting a new activity.",
            reply_markup=keyboard_for_role(staff),
        )
        return

    activity = activity_for_key(activity_key)
    now = utc_now()
    REPOSITORY.start_activity(staff["user_id"], update.effective_chat.id, activity_key, now)
    remaining = SERVICE.remaining_seconds(staff["user_id"])
    warning = warning_text(remaining)
    warning_block = f"\n\n{warning}" if warning else ""
    await update.message.reply_text(
        f"{activity.label} started.\n"
        f"Started: {format_local(now)}\n"
        f"Status: Running until you press {BACK_LABEL}.{warning_block}",
        reply_markup=keyboard_for_role(staff),
    )
    await send_supervisor_alert(
        context,
        f"{display_name(staff)} started {activity.label} at {format_local(now)}.",
    )


async def time_in_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await time_in(update, context)


async def time_out_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await time_out(update, context)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (update.message.text or "").strip()
    action = LABEL_TO_ACTION.get(text)
    if not action:
        return

    if action == "time_in":
        await time_in(update, context)
        return
    if action == "time_out":
        await time_out(update, context)
        return
    if action == "back":
        await back_activity(update, context)
        return
    if action == "status":
        await status_command(update, context)
        return
    if action == "admin_panel":
        await admin_panel_command(update, context)
        return
    if action == "staff_dashboard":
        await staff_dashboard_command(update, context)
        return
    if action == "rest_day":
        await rest_day(update, context)
        return
    if action == "collect_data":
        await collect_data_command(update, context)
        return
    if action == "cutoff_report":
        await cutoff_report_command(update, context)
        return
    await start_activity(update, context, action)


async def remind_active_staff(context: ContextTypes.DEFAULT_TYPE) -> None:
    for session in REPOSITORY.get_all_active_sessions():
        staff = REPOSITORY.get_staff(session["user_id"])
        if not staff or role_of(staff) != ROLE_STAFF:
            continue

        remaining = SERVICE.remaining_seconds(session["user_id"])
        if remaining >= 0:
            continue

        started_at = datetime.fromisoformat(session["started_at"])
        running_seconds = (utc_now() - started_at).total_seconds()
        summary = SERVICE.summary_text(session["user_id"])
        staff_name = display_name(staff)
        text = (
            f"Reminder for {staff_name}: {activity_for_key(session['activity_key']).label} is still running after exceeding the daily 60-minute limit.\n"
            f"Running Time: {format_duration(running_seconds)}\n"
            f"Press {BACK_LABEL} when the activity is finished.\n\n"
            f"{summary}"
        )
        try:
            await context.bot.send_message(
                chat_id=session["chat_id"],
                text=text,
                reply_markup=STAFF_KEYBOARD,
            )
        except Exception:
            LOGGER.exception("Failed to send reminder to chat %s", session["chat_id"])


async def send_daily_html_report(context: ContextTypes.DEFAULT_TYPE) -> None:
    recipients = {row["user_id"] for row in REPOSITORY.get_users_by_roles((ROLE_OWNER, ROLE_ADMIN))}
    recipients = {user_id for user_id in recipients if user_id}
    if not recipients:
        LOGGER.warning("Skipping daily HTML report because no admin or owner recipients are registered yet.")
        return

    previous_day_reference = utc_now() - timedelta(days=1)
    report_path = SERVICE.build_daily_html_report(previous_day_reference)
    report_date = format_local_date(previous_day_reference)

    for admin_id in recipients:
        try:
            await send_html_report_document(
                context,
                chat_id=admin_id,
                report_path=report_path,
                caption=f"Daily staff HTML report for {report_date}",
            )
        except Exception:
            LOGGER.exception("Failed to send daily HTML report to admin %s", admin_id)


def build_application() -> Application:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required.")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("report", report_command))
    app.add_handler(CommandHandler("active", active_command))
    app.add_handler(CommandHandler("collect", collect_data_command))
    app.add_handler(CommandHandler("cutoff", cutoff_report_command))
    app.add_handler(CommandHandler("adminpanel", admin_panel_command))
    app.add_handler(CommandHandler("staffdashboard", staff_dashboard_command))
    app.add_handler(CommandHandler("timein", time_in_command))
    app.add_handler(CommandHandler("timeout", time_out_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.job_queue.run_repeating(remind_active_staff, interval=AUTO_CLOSE_CHECK_SECONDS, first=AUTO_CLOSE_CHECK_SECONDS)
    app.job_queue.run_daily(
        send_daily_html_report,
        time=time(hour=1, minute=0, second=0, tzinfo=LOCAL_TZ),
        name="daily-html-report",
    )
    return app


def main() -> None:
    app = build_application()
    LOGGER.info("Starting Telegram staff activity bot")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
