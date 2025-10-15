import os
import logging
import asyncio
import sqlite3
import hmac
import hashlib
import json
import random
from time import time
from typing import Optional, Dict, List
from urllib.parse import parse_qs, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn

# --- Настройка логирования ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Конфигурация ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL")
DB_PATH = "/data/app.db"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "star_miner_bot")
ADMIN_TG_ID = os.environ.get("ADMIN_TG_ID")

if not TELEGRAM_TOKEN:
    raise ValueError("Не найден TELEGRAM_TOKEN в переменных окружения!")
if not WEBAPP_URL:
    raise ValueError("Не найден WEBAPP_URL в переменных окружения!")

# === Pydantic модели ===
class RequestData(BaseModel):
    init_data: str

class WithdrawRequest(BaseModel):
    init_data: str
    amount: float

class BlastResponse(BaseModel):
    prize_amount: float
    new_stars: float
    new_dynamite: int
    referrer_bonus: float = 0.0

class AdminAction(BaseModel):
    init_data: str
    withdrawal_id: int
    action: str  # approve / reject

# === Работа с БД ===
def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            stars REAL DEFAULT 0.0,
            dynamite INTEGER DEFAULT 3,
            last_blast INTEGER DEFAULT 0,
            referrer_id INTEGER,
            referral_earnings REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()
    logger.info("Database initialized at %s", DB_PATH)

initialize_db()

# === Проверка Telegram initData ===
def init_data_auth(init_data: str) -> Dict[str, any]:
    if not init_data:
        raise HTTPException(status_code=401, detail="Auth failed: No init_data provided.")

    try:
        # ✅ Исправленный порядок параметров HMAC
        key = hmac.new(
            b"WebAppData",
            TELEGRAM_TOKEN.strip().encode(),
            hashlib.sha256
        ).digest()
    except Exception as e:
        logger.error(f"Error creating HMAC key: {e}")
        raise HTTPException(status_code=500, detail="Internal Auth Error.")

    query_params = parse_qs(unquote(init_data))
    received_hash = query_params.pop("hash", [None])[0]

    if not received_hash or not query_params.get("auth_date"):
        raise HTTPException(status_code=401, detail="Auth failed: Missing hash or auth_date.")

    data_check_string = "\n".join(
        f"{k}={v[0]}" for k, v in sorted(query_params.items())
    )

    calculated_hash = hmac.new(
        key=key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256
    ).hexdigest()

    if calculated_hash != received_hash:
        logger.error("Auth failed: Hash mismatch")
        raise HTTPException(status_code=401, detail="Auth failed: Hash mismatch.")

    user_data = query_params.get("user", [None])[0]
    if not user_data:
        raise HTTPException(status_code=401, detail="Auth failed: User data not found.")

    try:
        auth_data = json.loads(user_data)
    except Exception as e:
        logger.error(f"Invalid user JSON: {e}")
        raise HTTPException(status_code=401, detail="Invalid user JSON.")

    return auth_data

# === Работа с пользователями ===
INITIAL_STAR_BONUS = 2.0

def get_or_create_user(user_id: int, username: str, start_parameter: Optional[str] = None):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cur.fetchone()
    if not user:
        referrer_id = None
        if start_parameter and start_parameter.isdigit() and int(start_parameter) != user_id:
            pid = int(start_parameter)
            cur.execute("SELECT id FROM users WHERE id = ?", (pid,))
            if cur.fetchone():
                referrer_id = pid
        cur.execute("""
            INSERT INTO users (id, username, stars, dynamite, referrer_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, INITIAL_STAR_BONUS, 3, referrer_id))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cur.fetchone()
        logger.info(f"New user {username} ({user_id}) created. Referrer: {referrer_id}")

    conn.close()
    return dict(user)

# === FASTAPI ===
app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    start_param = request.query_params.get("tgWebAppStartParam")
    return templates.TemplateResponse("index.html", {"request": request, "start_param": start_param})

@app.post("/api/v1/data")
async def get_user_data(data: RequestData):
    auth_data = init_data_auth(data.init_data)
    user_id = auth_data["id"]
    username = auth_data.get("username") or f"id_{user_id}"

    user_data = get_or_create_user(user_id, username)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    refs = cur.fetchone()[0]
    conn.close()

    return JSONResponse(content={
        "user_data": user_data,
        "referrals_count": refs,
        "bot_username": BOT_USERNAME,
        "is_admin": str(user_id) == ADMIN_TG_ID
    })

@app.post("/api/v1/blast", response_model=BlastResponse)
async def blast_mine(data: RequestData):
    auth_data = init_data_auth(data.init_data)
    user_id = auth_data["id"]

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT stars, dynamite, last_blast, referrer_id FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")

    stars, dynamite, last_blast, ref_id = row
    now = int(time())
    if dynamite <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Нет динамита (0 💣). Пригласите друга.")
    if now - last_blast < 30:
        remain = 30 - (now - last_blast)
        conn.close()
        raise HTTPException(status_code=429, detail=f"Подождите {remain} секунд.")

    prize = random.choice([0.1, 0.3, 0.5, 1.0, 3.0, 5.0])
    new_stars = stars + prize
    new_dynamite = dynamite - 1
    cur.execute("UPDATE users SET stars=?, dynamite=?, last_blast=? WHERE id=?",
                (new_stars, new_dynamite, now, user_id))

    ref_bonus = 0.0
    if ref_id:
        ref_bonus = round(prize * 0.1, 2)
        cur.execute("UPDATE users SET stars=stars+?, referral_earnings=referral_earnings+? WHERE id=?",
                    (ref_bonus, ref_bonus, ref_id))
    conn.commit()
    conn.close()

    return JSONResponse(content={
        "prize_amount": prize,
        "new_stars": new_stars,
        "new_dynamite": new_dynamite,
        "referrer_bonus": ref_bonus
    })

@app.post("/api/v1/withdraw")
async def withdraw(data: WithdrawRequest):
    auth_data = init_data_auth(data.init_data)
    user_id = auth_data["id"]
    username = auth_data.get("username") or f"id_{user_id}"
    amount = data.amount

    if amount < 50:
        raise HTTPException(status_code=400, detail="Минимальная сумма вывода: 50 ★")

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT stars FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="User not found.")
    stars = row[0]
    if amount > stars:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно средств.")

    new_stars = stars - amount
    cur.execute("UPDATE users SET stars=? WHERE id=?", (new_stars, user_id))
    cur.execute("INSERT INTO withdrawals (user_id, username, amount) VALUES (?, ?, ?)",
                (user_id, username, amount))
    conn.commit()
    conn.close()

    return JSONResponse(content={
        "status": "ok",
        "message": f"Заявка на вывод {amount} ★ принята.",
        "new_stars": new_stars
    })

def is_admin(user_id: int) -> bool:
    return ADMIN_TG_ID and str(user_id) == ADMIN_TG_ID

@app.post("/api/v1/admin/withdrawals")
async def admin_withdrawals(data: RequestData):
    auth_data = init_data_auth(data.init_data)
    if not is_admin(auth_data["id"]):
        raise HTTPException(status_code=403, detail="Access denied.")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, username, amount, status, created_at FROM withdrawals ORDER BY created_at DESC")
    res = [dict(row) for row in cur.fetchall()]
    conn.close()
    return JSONResponse(content={"withdrawals": res})

@app.post("/api/v1/admin/action")
async def admin_action(data: AdminAction):
    auth_data = init_data_auth(data.init_data)
    if not is_admin(auth_data["id"]):
        raise HTTPException(status_code=403, detail="Access denied.")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, amount, status FROM withdrawals WHERE id=?", (data.withdrawal_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Withdrawal not found.")
    user_id, amount, status = row
    if status != "pending":
        conn.close()
        raise HTTPException(status_code=400, detail="Already processed.")
    if data.action == "approve":
        cur.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (data.withdrawal_id,))
    elif data.action == "reject":
        cur.execute("UPDATE users SET stars=stars+? WHERE id=?", (amount, user_id))
        cur.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (data.withdrawal_id,))
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid action.")
    conn.commit()
    conn.close()
    return JSONResponse(content={"status": "ok", "message": f"Withdrawal #{data.withdrawal_id} updated."})

# === Запуск ===
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
