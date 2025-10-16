import sqlite3
import os
from aiogram import Bot
from typing import List, Optional, Tuple, Dict
from datetime import datetime, date, timedelta, timezone # <-- ДОЛЖНО БЫТЬ ТАК
from config import ADMIN_ID
from config import BOT_TOKEN
import asyncio

# ----------------- Путь к базе -----------------
DB_PATH = os.getenv("DB_PATH", "/data/bot.db") # Путь на Volume
INITIAL_DB_PATH = "initial_data/initial_bot.db" # Путь в репозитории

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

print("DB_PATH =", DB_PATH)
print("Exists:", os.path.exists(DB_PATH))
print("Writable:", os.access(DB_PATH, os.W_OK))

_conn = None
_initialized = False  # флаг, что таблицы созданы

# ----------------- Получение соединения -----------------
def get_conn():
    global _conn, _initialized
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    if not _initialized:
        init_db(_conn)
        _initialized = True
    return _conn

# ----------------- Initialize DB -----------------

# --- Manual Tasks (ручные задания) ---


def init_db(conn):
    cur = conn.cursor()

    # --- Tasks ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel TEXT NOT NULL,
        stars REAL NOT NULL,
        created_at TEXT DEFAULT (DATETIME('now')),
        max_completions INTEGER DEFAULT 0,
        current_completions INTEGER DEFAULT 0,
        type TEXT DEFAULT 'channel'
    )
    """)

        # Добавляем лимиты для ручных заданий (если колонок нет)
    try:
        cur.execute("ALTER TABLE manual_tasks ADD COLUMN max_uses INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN username_bonus_revoked INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_username_bonus_date TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE manual_tasks ADD COLUMN current_uses INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    # Проверяем и добавляем колонку max_completions (для старых баз)
    try:
        cur.execute("ALTER TABLE tasks ADD COLUMN max_completions INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Проверяем и добавляем колонку current_completions (для старых баз)
    try:
        cur.execute("ALTER TABLE tasks ADD COLUMN current_completions INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # Проверяем и добавляем колонку type (для старых баз)
    try:
        cur.execute("ALTER TABLE tasks ADD COLUMN type TEXT DEFAULT 'channel'")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_bio_bonus_date TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE users ADD COLUMN bio_bonus_revoked INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # --- Manual Tasks ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS manual_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        description TEXT,
        link TEXT,
        stars REAL NOT NULL,
        created_at TEXT DEFAULT (DATETIME('now'))
    )
    """)

    # Добавляем недостающие колонки (для старых баз)
    try:
        cur.execute("ALTER TABLE manual_tasks ADD COLUMN max_uses INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE manual_tasks ADD COLUMN current_uses INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass


    cur.execute("""
    CREATE TABLE IF NOT EXISTS manual_task_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        manual_task_id INTEGER NOT NULL,
        file_id TEXT NOT NULL,
        status TEXT DEFAULT 'pending', -- pending / approved / rejected / draft
        created_at TEXT DEFAULT (DATETIME('now'))
    )
    """)
    # --- Users ---
      # --- Users ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users ( 
        id INTEGER PRIMARY KEY,
        username TEXT,
        is_verified INTEGER DEFAULT 0,
        stars REAL DEFAULT 0,
        referrer_id INTEGER,
        created_at TEXT,
        last_bonus_date TEXT,
        tasks_done INTEGER DEFAULT 0,
        full_name TEXT,
        stars_total REAL DEFAULT 0
    )
    """)


    try:
        cur.execute("ALTER TABLE users ADD COLUMN referral_bonus_given INTEGER DEFAULT 0")
        conn.commit()
    except sqlite3.OperationalError as e:
        # Колонка уже существует, это нормально
        if "duplicate column name" not in str(e):
            raise
        
    # 🔹 Добавляем новые колонки, если их нет
    try:
        cur.execute("ALTER TABLE users ADD COLUMN last_click_time TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        cur.execute("ALTER TABLE users ADD COLUMN vip_level INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # --- Withdraw Requests ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS withdraw_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        stars REAL,
        status TEXT,
        created_at TEXT
    )
    """)

    # --- Stars Log ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stars_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        delta REAL,
        reason TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS coupons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT UNIQUE NOT NULL,
        stars INTEGER NOT NULL,
        max_uses INTEGER NOT NULL,
        used_count INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS coupon_uses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        coupon_id INTEGER NOT NULL,
        used_at TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, coupon_id)
    )
    """)

    # --- Task Submissions ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS task_submissions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_id INTEGER,
        proof_file_id TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )
    """)

    # --- User Tasks Done ---
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_tasks_done (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_id INTEGER,
        UNIQUE(user_id, task_id)
    )
    """)

    conn.commit()
    print("✅ init_db завершена, все таблицы созданы")

# ----------------- Users -----------------
def get_user(user_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def add_user(user_id: int, username: Optional[str], referrer_id: Optional[int], full_name: Optional[str] = None):
    conn = get_conn()
    cur = conn.cursor()
    created_at = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("""
    INSERT OR IGNORE INTO users (id, username, stars, stars_total, referrer_id, created_at, last_bonus_date, tasks_done, full_name, is_verified)
    VALUES (?, ?, 0, 0, ?, ?, NULL, 0, ?, ?)
    """, (user_id, username, referrer_id, created_at, full_name, 0)) 
    
    conn.commit()

def update_bonus_date(user_id: int, date_iso: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_bonus_date = ? WHERE id = ?", (date_iso, user_id))
    conn.commit()

def increment_tasks_done(user_id: int, delta: int = 1):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET tasks_done = COALESCE(tasks_done,0) + ? WHERE id = ?", (delta, user_id))
    conn.commit()

def update_stars(user_id: int, amount: float, reason: str = None, cur=None):
    close_conn = False
    if cur is None:
        conn = get_conn()
        cur = conn.cursor()
        close_conn = True

    cur.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (amount, user_id))
    if amount > 0:
        cur.execute("UPDATE users SET stars_total = stars_total + ? WHERE id = ?", (amount, user_id))
    if reason:
        created_at = datetime.utcnow().isoformat()
        cur.execute(
            "INSERT INTO stars_log (user_id, delta, reason, created_at) VALUES (?, ?, ?, ?)",
            (user_id, amount, reason, created_at)
        )

    if close_conn:
        conn.commit()

# ----------------- Statistics -----------------
def get_top_users_by_stars(today_only: bool = False, limit: int = 10) -> List[Tuple[str, float]]:
    conn = get_conn()
    cur = conn.cursor()
    if today_only:
        # ИСПРАВЛЕНИЕ 1: Вычисляем "сегодняшнюю" дату по московскому времени (UTC+3)
        today = (datetime.utcnow() + timedelta(hours=3)).date().isoformat()
        
        cur.execute("""
            SELECT u.full_name, u.username, SUM(l.delta) as stars_value
            FROM stars_log l
            JOIN users u ON u.id = l.user_id
            -- ИСПРАВЛЕНИЕ 2: Сдвигаем метки времени в базе данных на +3 часа
            -- (чтобы они соответствовали МСК) перед сравнением с датой MSK
            WHERE DATE(l.created_at, '+3 hours') = ? 
            GROUP BY l.user_id
            ORDER BY stars_value DESC
            LIMIT ?
        """, (today, limit))
    else:
        cur.execute("""
            SELECT u.full_name, u.username, SUM(l.delta) as stars_value
            FROM stars_log l
            JOIN users u ON u.id = l.user_id
            GROUP BY l.user_id
            ORDER BY stars_value DESC
            LIMIT ?
        """, (limit,))
        
    rows = cur.fetchall()
    result = []
    for r in rows:
        name = r["full_name"] if r["full_name"] else (f"@{r['username']}" if r["username"] else "Без имени")
        stars_value = float(r["stars_value"] or 0)
        result.append((name, stars_value))
    return result

def get_top_users_by_tasks(limit: int = 10) -> List[Tuple[str, int]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT u.full_name, u.username, u.tasks_done
        FROM users u
        ORDER BY u.tasks_done DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    result = []
    for r in rows:
        name = r["full_name"] if r["full_name"] else (f"@{r['username']}" if r["username"] else "Без имени")
        result.append((name, int(r["tasks_done"] or 0)))
    return result

# ----------------- Withdraw requests -----------------
def create_withdraw_request(user_id: int, stars: float) -> int:
    conn = get_conn()
    cur = conn.cursor()
    created_at = datetime.utcnow().isoformat()
    cur.execute("INSERT INTO withdraw_requests (user_id, stars, status, created_at) VALUES (?, ?, 'pending', ?)",
                (user_id, stars, created_at))
    conn.commit()
    return cur.lastrowid

def get_withdraw_requests(status: Optional[str] = None) -> list:
    conn = get_conn()
    cur = conn.cursor()
    if status:
        cur.execute("""
            SELECT wr.id, wr.user_id, u.username, wr.stars, wr.status, wr.created_at
            FROM withdraw_requests wr
            LEFT JOIN users u ON u.id = wr.user_id
            WHERE wr.status = ?
            ORDER BY wr.created_at ASC
        """, (status,))
    else:
        cur.execute("""
            SELECT wr.id, wr.user_id, u.username, wr.stars, wr.status, wr.created_at
            FROM withdraw_requests wr
            LEFT JOIN users u ON u.id = wr.user_id
            ORDER BY wr.created_at ASC
        """)
    rows = cur.fetchall()
    return [tuple(r) for r in rows]

def get_withdraw_request_by_id(request_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT wr.id, wr.user_id, u.username, wr.stars, wr.status, wr.created_at
        FROM withdraw_requests wr
        LEFT JOIN users u ON u.id = wr.user_id
        WHERE wr.id = ?
    """, (request_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def update_withdraw_request(request_id: int, status: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE withdraw_requests SET status = ? WHERE id = ?", (status, request_id))
    conn.commit()

# ----------------- Tasks -----------------
def get_all_tasks() -> List[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks ORDER BY id DESC")
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_task(task_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def add_task(channel: str, stars: float, max_completions: int = 0) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO tasks (channel, stars, max_completions, current_completions) VALUES (?, ?, ?, 0)",
        (channel, stars, max_completions)
    )
    conn.commit()
    return cur.lastrowid

def update_task_stars(task_id: int, stars: float):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET stars = ? WHERE id = ?", (stars, task_id))
    conn.commit()

def delete_task(task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    cur.execute("DELETE FROM user_tasks_done WHERE task_id = ?", (task_id,))
    conn.commit()

# ----------------- User Tasks Done -----------------
def mark_task_done(user_id: int, task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO user_tasks_done (user_id, task_id) VALUES (?, ?)", (user_id, task_id))
    conn.commit()

def has_user_done_task(user_id: int, task_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM user_tasks_done WHERE user_id = ? AND task_id = ?", (user_id, task_id))
    return cur.fetchone() is not None

async def notify_admins_limit_reached(task_id: int, channel: str):
    bot = Bot(token=BOT_TOKEN)
    for admin in ADMIN_ID:
        try:
            await bot.send_message(admin, f"⚠️ Лимит по заданию #{task_id} ({channel}) исчерпан!")
        except Exception as e:
            print(f"Ошибка уведомления админа {admin}: {e}")
    await bot.session.close()

def complete_task(user_id: int, task_id: int) -> str | bool:
    if has_user_done_task(user_id, task_id):
        return False
    task = get_task(task_id)
    if not task:
        return False

    max_c = task.get("max_completions") or 0
    curr_c = task.get("current_completions") or 0

    # если лимит уже исчерпан
    if max_c > 0 and curr_c >= max_c:
        return "limit_reached"

    stars = task['stars']
    update_stars(user_id, stars, reason=f"Выполнение задания #{task_id}")
    mark_task_done(user_id, task_id)
    increment_tasks_done(user_id)

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET current_completions = current_completions + 1 WHERE id = ?", (task_id,))
    conn.commit()

    # проверяем, достигнут ли лимит после выполнения
    if max_c > 0 and (curr_c + 1) >= max_c:
        asyncio.create_task(notify_admins_limit_reached(task_id, task['channel']))

    return True

def save_coupon(code: str, stars: int, max_uses: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO coupons (code, stars, max_uses) VALUES (?, ?, ?)",
        (code, stars, max_uses)
    )
    conn.commit()

def load_tasks() -> List[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks ORDER BY id DESC")
    return [dict(row) for row in cur.fetchall()]

def load_coupons() -> List[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM coupons ORDER BY id DESC")
    return [dict(row) for row in cur.fetchall()]

def get_referrals_count(user_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    row = cur.fetchone()
    return row[0] if row else 0

def delete_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM user_tasks_done WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM task_submissions WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM stars_log WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM withdraw_requests WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM coupon_uses WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()

def update_task_limit(task_id: int, max_completions: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET max_completions = ? WHERE id = ?", (max_completions, task_id))
    conn.commit()

def recreate_tasks_table():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS tasks")
    cur.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            stars REAL NOT NULL,
            created_at TEXT DEFAULT (DATETIME('now')),
            max_completions INTEGER DEFAULT 0,
            current_completions INTEGER DEFAULT 0,
            type TEXT DEFAULT 'channel'
        )
    """)
    conn.commit()
    print("✅ Таблица tasks пересоздана (старые данные удалены)")

# ----------------- Manual Tasks (ручные assignments) -----------------
def add_manual_task(title: str, description: str, link: str, stars: float) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO manual_tasks (title, description, link, stars) VALUES (?, ?, ?, ?)",
        (title, description, link, stars)
    )
    conn.commit()
    return cur.lastrowid

def get_manual_tasks() -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM manual_tasks
        WHERE (max_uses = 0 OR current_uses < max_uses)
        ORDER BY id DESC
    """)
    return [dict(r) for r in cur.fetchall()]


def get_manual_task(manual_task_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM manual_tasks WHERE id = ?", (manual_task_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def delete_manual_task(manual_task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM manual_tasks WHERE id = ?", (manual_task_id,))
    cur.execute("DELETE FROM manual_task_submissions WHERE manual_task_id = ?", (manual_task_id,))
    conn.commit()

# Submissions
def create_manual_submission(user_id: int, manual_task_id: int, file_id: str) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO manual_task_submissions (user_id, manual_task_id, file_id, status) VALUES (?, ?, ?, 'draft')",
        (user_id, manual_task_id, file_id)
    )
    conn.commit()
    return cur.lastrowid

def submit_manual_submission(submission_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE manual_task_submissions SET status = 'pending' WHERE id = ?", (submission_id,))
    conn.commit()

def get_manual_submissions(status: str | None = None) -> list:
    conn = get_conn()
    cur = conn.cursor()
    if status:
        cur.execute("""
            SELECT s.id, s.user_id, s.manual_task_id, s.file_id, s.status, s.created_at, u.username, m.title, m.stars
            FROM manual_task_submissions s
            LEFT JOIN users u ON u.id = s.user_id
            LEFT JOIN manual_tasks m ON m.id = s.manual_task_id
            WHERE s.status = ?
            ORDER BY s.created_at ASC
        """, (status,))
    else:
        cur.execute("""
            SELECT s.id, s.user_id, s.manual_task_id, s.file_id, s.status, s.created_at, u.username, m.title, m.stars
            FROM manual_task_submissions s
            LEFT JOIN users u ON u.id = s.user_id
            LEFT JOIN manual_tasks m ON m.id = s.manual_task_id
            ORDER BY s.created_at ASC
        """)
    rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_manual_submission_by_id(submission_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.user_id, s.manual_task_id, s.file_id, s.status, s.created_at, u.username, m.title, m.stars
        FROM manual_task_submissions s
        LEFT JOIN users u ON u.id = s.user_id
        LEFT JOIN manual_tasks m ON m.id = s.manual_task_id
        WHERE s.id = ?
    """, (submission_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def update_manual_submission_status(submission_id: int, status: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE manual_task_submissions SET status = ? WHERE id = ?", (status, submission_id))
    conn.commit()

def count_total_submissions(manual_task_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM manual_task_submissions WHERE manual_task_id = ?", (manual_task_id,))
    row = cur.fetchone()
    return row[0] if row else 0

def get_user_submission_for_task(user_id: int, manual_task_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM manual_task_submissions
        WHERE user_id = ? AND manual_task_id = ?
        ORDER BY created_at DESC
        LIMIT 1
    """, (user_id, manual_task_id))
    row = cur.fetchone()
    return dict(row) if row else None

def add_manual_task_with_limit(title: str, description: str, link: str, stars: float, max_uses: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO manual_tasks (title, description, link, stars, max_uses, current_uses) VALUES (?, ?, ?, ?, ?, 0)",
        (title, description, link, stars, max_uses)
    )
    conn.commit()
    return cur.lastrowid


def complete_manual_task(user_id: int, manual_task_id: int) -> str | bool:
    conn = get_conn()
    cur = conn.cursor()

    # Загружаем задание
    cur.execute("SELECT * FROM manual_tasks WHERE id = ?", (manual_task_id,))
    task = cur.fetchone()
    if not task:
        return False

    max_uses = task["max_uses"] or 0
    current_uses = task["current_uses"] or 0

    # Проверяем лимит
    if max_uses > 0 and current_uses >= max_uses:
        return "limit_reached"

    # Проверяем, делал ли уже этот юзер задание
    cur.execute("SELECT 1 FROM manual_task_submissions WHERE user_id = ? AND manual_task_id = ?", (user_id, manual_task_id))
    if cur.fetchone():
        return False

    # Начисляем звезды
    update_stars(user_id, task["stars"], reason=f"Ручное задание #{manual_task_id}")

    # Увеличиваем счётчик
    cur.execute("UPDATE manual_tasks SET current_uses = current_uses + 1 WHERE id = ?", (manual_task_id,))

    # Отмечаем выполнение
    cur.execute(
        "INSERT INTO manual_task_submissions (user_id, manual_task_id, file_id, status) VALUES (?, ?, '', 'approved')",
        (user_id, manual_task_id)
    )

    conn.commit()
    return True

def increment_manual_task_use(task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE manual_tasks SET current_uses = current_uses + 1 WHERE id = ?", (task_id,))
    conn.commit()

def add_manual_submission(user_id: int, task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO manual_task_submissions (user_id, task_id, status, created_at) VALUES (?, ?, ?, datetime('now'))",
        (user_id, task_id, "pending")
    )
    conn.commit()

def increment_manual_task_use(task_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE manual_tasks SET current_uses = current_uses + 1 WHERE id = ?", (task_id,))
    conn.commit()

def get_all_manual_tasks() -> list:
    """
    Возвращает все ручные задания (включая те, у которых исчерпан лимит).
    Используется в админке — чтобы админ видел задания даже после исчерпания лимита.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM manual_tasks ORDER BY id DESC")
    return [dict(r) for r in cur.fetchall()]

def add_vip_and_clicker_fields():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("ALTER TABLE users ADD COLUMN vip_level INTEGER DEFAULT 0")
    cur.execute("ALTER TABLE users ADD COLUMN last_click_time TEXT")
    conn.commit()

def set_vip(user_id: int, level: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET vip_level = ? WHERE id = ?", (level, user_id))
    conn.commit()

def get_vip_level(user_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT vip_level FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    return row["vip_level"] if row else 0

def update_last_click(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_click_time = ? WHERE id = ?", (datetime.utcnow().isoformat(), user_id))
    conn.commit()

def get_last_click(user_id: int) -> str | None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT last_click_time FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    return row["last_click_time"] if row else None

# database.py
def get_top_clicker_users(today_only: bool = False, limit: int = 10) -> list[tuple[str, int]]:
    conn = get_conn()
    cur = conn.cursor()
    if today_only:
        # ИЗМЕНЕНИЕ 1: Определяем "сегодня" по МСК (UTC + 3 часа)
        today = (datetime.utcnow() + timedelta(hours=3)).date().isoformat()
        
        cur.execute("""
            SELECT u.full_name, u.username, COUNT(l.id) as clicks
            FROM stars_log l
            JOIN users u ON u.id = l.user_id
            -- ИЗМЕНЕНИЕ 2: Используем смещение -3 часа для соответствия MSK (UTC+3)
            -- DATE(l.created_at, '-3 hours') = ? - это было бы верно, если бы `today` был в UTC.
            -- Однако, поскольку мы выше сместили `today` на MSK, просто сравниваем даты:
            WHERE DATE(l.created_at, '+3 hours') = ? AND l.reason = 'Clicker reward'
            GROUP BY l.user_id
            ORDER BY clicks DESC
            LIMIT ?
        """, (today, limit))
    else:
        cur.execute("""
            SELECT u.full_name, u.username, COUNT(l.id) as clicks
            FROM stars_log l
            JOIN users u ON u.id = l.user_id
            WHERE l.reason = 'Clicker reward'
            GROUP BY l.user_id
            ORDER BY clicks DESC
            LIMIT ?
        """, (limit,))
        
    rows = cur.fetchall()
    result = []
    for r in rows:
        name = r["full_name"] if r["full_name"] else (f"@{r['username']}" if r["username"] else "Без имени")
        clicks = int(r["clicks"] or 0)
        result.append((name, clicks))
    return result

def set_referral_bonus_given(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE users 
        SET referral_bonus_given = 1 
        WHERE id = ?
    """, (user_id,))
    conn.commit()

def get_referrals_count(referrer_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT COUNT(id) 
        FROM users 
        WHERE referrer_id = ? AND referral_bonus_given = 1
    """, (referrer_id,))
    
    count = cur.fetchone()[0]
    return count

# В database.py

def get_referral_top_for_date(target_date: str, limit: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            u.referrer_id,
            r.full_name,
            r.username,
            COUNT(u.id) as referral_count
        FROM users u
        JOIN users r ON r.id = u.referrer_id
        WHERE
            u.referrer_id IS NOT NULL AND
            u.referral_bonus_given = 1 AND
            DATE(u.created_at, '+3 hours') = ?  -- ИСПРАВЛЕНО: +3 часа для МСК
        GROUP BY u.referrer_id
        ORDER BY referral_count DESC
        LIMIT ?
    """, (target_date, limit))
    rows = cur.fetchall()
    result = []
    for row in rows:
        name = row["full_name"] or (f"@{row['username']}" if row["username"] else f"ID: {row['referrer_id']}")
        result.append({"id": row["referrer_id"], "name": name, "count": row["referral_count"]})
    return result

# <-- НОВОЕ: Функция для получения ВСЕХ рангов за день -->
def get_all_referral_ranks_for_date(target_date: str) -> dict: 
    """
    Рассчитывает полный рейтинг всех пользователей по рефералам за день (по МСК).
    Возвращает словарь: {user_id: {"rank": int, "count": int}}
    """
    conn = get_conn()
    cur = conn.cursor()
    query = """
        WITH AggregatedData AS (
            SELECT
                u.referrer_id,
                COUNT(u.id) as referral_count
            FROM users u
            WHERE
                u.referrer_id IS NOT NULL AND
                u.referral_bonus_given = 1 AND
                DATE(u.created_at, '+3 hours') = ? -- ИСПРАВЛЕНИЕ: +3 часа для МСК
            GROUP BY u.referrer_id
        )
        SELECT 
            referrer_id, 
            referral_count, 
            RANK() OVER (ORDER BY referral_count DESC) as user_rank -- Ранжируем уже агрегированные данные
        FROM AggregatedData;
    """
    cur.execute(query, (target_date,))
    rows = cur.fetchall()

    ranks_dict = {
        row['referrer_id']: {"rank": row['user_rank'], "count": row['referral_count']}
        for row in rows
    }
    return ranks_dict

def get_users_today_count(target_date: str) -> int:
    """
    Считает общее количество пользователей, зарегистрировавшихся сегодня по МСК.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            COUNT(id)
        FROM users
        WHERE
            DATE(created_at, '+3 hours') = ? 
    """, (target_date,))
    
    count = cur.fetchone()[0]
    return count


def get_verified_users_today_count(target_date: str) -> int:
    """
    Считает количество пользователей, которые сегодня зарегистрировались (по МСК)
    и прошли полную верификацию (телефон + подписки/задания).
    
    💡 Предполагаем, что "полная проверка" = phone IS NOT NULL AND tasks_done > 0.
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            COUNT(id)
        FROM users
        WHERE
            phone IS NOT NULL AND   
            DATE(created_at, '+3 hours') = ? 
    """, (target_date,))
    
    count = cur.fetchone()[0]
    return count



def get_verified_referrals_count(referrer_id: int) -> int:
    """
    Считает количество рефералов, которые завершили полную регистрацию:
    - имеют phone (подтвердили номер)
    - имеют referral_bonus_given = 1 (прошли проверку Flyer API)
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(id)
        FROM users
        WHERE 
            referrer_id = ? 
            AND referral_bonus_given = 1 
            AND phone IS NOT NULL
    """, (referrer_id,))
    count = cur.fetchone()[0]
    return count

# --- ДОБАВИТЬ В database.py ---

def get_all_active_users() -> List[int]:
    """
    Возвращает список ID всех пользователей для периодической проверки.
    """
    conn = get_conn()
    cur = conn.cursor()
    # Просто возвращаем все ID. 
    cur.execute("SELECT id FROM users")
    return [row[0] for row in cur.fetchall()]

# --- Убедитесь, что функции set_vip и get_vip_level существуют и работают с int: ---
# set_vip(user_id: int, level: int): Обновляет поле vip_level в таблице users
# get_vip_level(user_id: int) -> int: Возвращает текущее значение vip_level

# --- ДОБАВИТЬ В database.py --
# ... остальные импорты ...

def get_referral_top_for_week() -> List[Tuple[int, int]]:
    conn = get_conn()
    cur = conn.cursor()
    
    # --- Динамический расчет текущей недели (Четверг 00:00:00 MSK) ---
    
    MSK_OFFSET = timedelta(hours=3)
    
    # Получаем текущее время в UTC и делаем его "наивным"
    now_naive_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    
    # Переводим текущее время в "наивное" МСК для расчета дня недели
    now_msk_naive = now_naive_utc + MSK_OFFSET
    
    # Расчет, сколько дней прошло с последнего ЧЕТВЕРГА (0=Пн, 6=Вс. Четверг = 3)
    days_since_thurs = (now_msk_naive.weekday() - 3) % 7 
    
    # Рассчитываем НАЧАЛО НЕДЕЛИ в МСК (00:00:00 МСК)
    start_of_week_msk_naive = (now_msk_naive - timedelta(days=days_since_thurs)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # Переводим НАЧАЛО НЕДЕЛИ из МСК обратно в UTC (UTC_TIME = MSK_TIME - MSK_OFFSET)
    start_of_week_utc_naive = start_of_week_msk_naive - MSK_OFFSET
    
    # Конец текущей недели (7 дней после начала)
    end_of_week_utc_naive = start_of_week_utc_naive + timedelta(days=7)
    
    # Формат для сравнения в SQLite
    START_DATE_TIME = start_of_week_utc_naive.strftime('%Y-%m-%d %H:%M:%S')
    END_DATE_TIME = end_of_week_utc_naive.strftime('%Y-%m-%d %H:%M:%S')
    
    # DEBUG вывод
    end_of_week_msk = end_of_week_utc_naive + MSK_OFFSET
    print(f"DEBUG: Период топа: СТАРТ - {start_of_week_msk_naive.strftime('%Y-%m-%d %H:%M:%S')} | КОНЕЦ - {end_of_week_msk.strftime('%Y-%m-%d %H:%M:%S')}. Используется {START_DATE_TIME} UTC.")
    
    cur.execute("""
        SELECT
            referrer_id,
            COUNT(id) AS referral_count
        FROM users
        WHERE 
            referrer_id IS NOT NULL AND
            referral_bonus_given = 1 AND
            phone IS NOT NULL AND
            created_at >= ? AND 
            created_at < ?
        GROUP BY referrer_id
        ORDER BY referral_count DESC
        LIMIT 10
    """, (START_DATE_TIME, END_DATE_TIME))
    
    return cur.fetchall()

def set_user_verified(user_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET is_verified = ? WHERE id = ?",
        (1, user_id)
    )
    conn.commit()
