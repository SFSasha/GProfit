import os
import logging
import asyncio
import sqlite3
import hmac
import hashlib
import json # <-- ФИКС: Добавлен отсутствующий импорт
import random # <-- ФИКС: Добавлен отсутствующий импорт
from time import time
from typing import Optional, Dict, List
from urllib.parse import parse_qs, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates 
from pydantic import BaseModel
import uvicorn

# Telegram imports are usually not needed if you only run FastAPI
# from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
# from telegram.ext import Application, CommandHandler, ContextTypes

# --- Настройка логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO 
)
logger = logging.getLogger(__name__)

# --- ГЛОБАЛЬНАЯ КОНФИГУРАЦИЯ ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL")

DB_PATH = "/data/app.db"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "star_miner_bot") 
# ID администратора. Добавьте его в переменные окружения!
ADMIN_TG_ID = os.environ.get("ADMIN_TG_ID") 

# Проверка переменных
if not TELEGRAM_TOKEN:
    raise ValueError("Не найден TELEGRAM_TOKEN в переменных окружения!")
if not WEBAPP_URL:
    raise ValueError("Не найден WEBAPP_URL в переменных окружения!")
# if not ADMIN_TG_ID: # Оставляем предупреждение, как было
#     logger.warning("ADMIN_TG_ID не установлен. Доступ к админ-панели будет отключен.")


# === МОДЕЛИ Pydantic ===

class RequestData(BaseModel):
    init_data: str 

class WithdrawRequest(BaseModel):
    init_data: str
    amount: float

class BlastResponse(BaseModel):
    prize_amount: float
    new_stars: float
    new_dynamite: int
    referrer_bonus: float = 0.0 # Добавлено для фронтенда

class AdminAction(BaseModel):
    init_data: str
    withdrawal_id: int
    action: str 

# === ИНИЦИАЛИЗАЦИЯ БД и УТИЛИТЫ ===

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            stars REAL DEFAULT 0.0,
            dynamite INTEGER DEFAULT 3,
            last_blast INTEGER DEFAULT 0,
            referrer_id INTEGER,
            referral_earnings REAL DEFAULT 0.0, -- НОВОЕ ПОЛЕ: Доход с рефералов
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    # Таблица заявок на вывод
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending', -- pending, approved, rejected
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

# Вызов инициализации БД при запуске
initialize_db()

# --- Логика аутентификации Telegram Web App ---
def init_data_auth(init_data: str) -> Dict[str, any]:
    if not init_data:
        raise HTTPException(status_code=401, detail="Auth failed: No init_data provided.")

    try:
        key = hmac.new(
            key=TELEGRAM_TOKEN.strip().encode(),
            msg=b"WebAppData",
            digestmod=hashlib.sha256
        ).digest()
    except Exception as e:
        logger.error(f"Error creating HMAC key: {e}")
        raise HTTPException(status_code=500, detail="Internal Auth Error.")


    query_params = parse_qs(unquote(init_data)) 
    received_hash_list = query_params.pop('hash', [None])
    received_hash = received_hash_list[0]

    if not received_hash or not query_params.get('auth_date'):
        raise HTTPException(status_code=401, detail="Auth failed: Missing hash or auth_date.")

    data_check_string = "\n".join([
        f"{key}={value[0]}"
        for key, value in sorted(query_params.items())
    ])

    calculated_hash = hmac.new(
        key=key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    logger.info("--- AUTH DEBUG START ---")
    logger.info(f"DATA CHECK STRING: '{data_check_string[:100]}...'")
    logger.info(f"CALCULATED HASH: {calculated_hash}")
    logger.info(f"RECEIVED HASH: {received_hash}")
    logger.info("--- AUTH DEBUG END ---")

    if calculated_hash != received_hash:
        logger.error(f"Auth failed: Hash mismatch! Calculated: {calculated_hash}, Received: {received_hash}")
        raise HTTPException(status_code=401, detail="Auth failed: Hash mismatch.")

    user_data = query_params.get('user', query_params.get('receiver', [None]))[0]
    if not user_data:
        raise HTTPException(status_code=401, detail="Auth failed: User data not found.")
        
    auth_data = json.loads(user_data) # 'json' теперь импортирован
    
    return auth_data


# --- ЛОГИКА БД (ПОЛЬЗОВАТЕЛЬ) ---

# КОНСТАНТА: Приветственный бонус
INITIAL_STAR_BONUS = 2.0 

def get_or_create_user(user_id: int, username: str, start_parameter: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Поиск пользователя
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        # 2. Создание нового пользователя
        referrer_id = None
        if start_parameter and start_parameter.isdigit() and int(start_parameter) != user_id:
            # Проверяем, существует ли реферер
            potential_referrer_id = int(start_parameter)
            cursor.execute("SELECT id FROM users WHERE id = ?", (potential_referrer_id,))
            if cursor.fetchone():
                referrer_id = potential_referrer_id
                
        # Вставка нового пользователя с бонусом
        cursor.execute("""
            INSERT INTO users (id, username, stars, dynamite, referrer_id, referral_earnings)
            VALUES (?, ?, ?, ?, ?, 0.0)
        """, (user_id, username, INITIAL_STAR_BONUS, 3, referrer_id)) # НОВОЕ: 2.0 звезды
        conn.commit()
        
        # Повторный запрос для получения полных данных
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        logger.info(f"New user created: {username} ({user_id}). Referrer: {referrer_id}, Bonus: {INITIAL_STAR_BONUS} ★")
        
    conn.close()
    return dict(user)


# --- API FastAPI ---
app = FastAPI()
templates = Jinja2Templates(directory=".") 

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    start_param = request.query_params.get("tgWebAppStartParam")
    
    return templates.TemplateResponse("index.html", {"request": request, "start_param": start_param})


@app.post("/api/v1/data")
async def get_user_data(data: RequestData):
    init_data = data.init_data 
    
    try:
        auth_data = init_data_auth(init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for data endpoint: {e.detail}")
        raise e
        
    user_id = auth_data['id']
    username = auth_data.get('username') or f"id_{user_id}"
    
    user_data = get_or_create_user(user_id, username)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    referrals_count = cursor.fetchone()[0]
    conn.close()
    
    # user_data теперь включает referral_earnings
    return JSONResponse(content={
        "user_data": user_data,
        "referrals_count": referrals_count,
        "bot_username": BOT_USERNAME,
        "is_admin": str(user_id) == ADMIN_TG_ID
    })


@app.post("/api/v1/blast", response_model=BlastResponse)
async def blast_mine(data: RequestData):
    init_data = data.init_data
    
    try:
        auth_data = init_data_auth(init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for blast endpoint: {e.detail}")
        raise e

    user_id = auth_data['id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Проверка динамита и кулдауна
    cursor.execute("SELECT stars, dynamite, last_blast, referrer_id FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
        
    current_stars, current_dynamite, last_blast, referrer_id = result
    
    MIN_BLAST_INTERVAL = 30 # секунд
    current_time = int(time())
    
    if current_dynamite <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Нет динамита (0 💣). Пригласите друга.")
        
    if current_time - last_blast < MIN_BLAST_INTERVAL:
        remaining = MIN_BLAST_INTERVAL - (current_time - last_blast)
        conn.close()
        raise HTTPException(status_code=429, detail=f"Пожалуйста, подождите {remaining} секунд до следующего взрыва.")

    # 2. Расчет добычи и обновление баланса
    
    # НОВОЕ: Фиксированные призы и выбор
    PRIZE_AMOUNTS = [0.1, 0.3, 0.5, 1.0, 3.0, 5.0]
    # import random уже добавлен в начале
    prize_amount = random.choice(PRIZE_AMOUNTS)
    
    new_stars = current_stars + prize_amount
    new_dynamite = current_dynamite - 1
    
    referrer_bonus = 0.0
    
    # Обновление баланса текущего пользователя
    cursor.execute("""
        UPDATE users 
        SET stars = ?, 
            dynamite = ?, 
            last_blast = ? 
        WHERE id = ?
    """, (new_stars, new_dynamite, current_time, user_id))
    
    # 3. Начисление реферального бонуса (10%)
    if referrer_id is not None:
        REFERRAL_PERCENT = 0.10 # 10%
        referrer_bonus = round(prize_amount * REFERRAL_PERCENT, 2)
        
        cursor.execute("""
            UPDATE users 
            SET stars = stars + ?, 
                referral_earnings = referral_earnings + ? 
            WHERE id = ?
        """, (referrer_bonus, referrer_bonus, referrer_id))
        logger.info(f"Referral bonus: User {referrer_id} received {referrer_bonus} ★ from user {user_id}'s blast.")

    conn.commit()
    conn.close()
    
    return JSONResponse(content={
        "prize_amount": prize_amount,
        "new_stars": new_stars,
        "new_dynamite": new_dynamite,
        "referrer_bonus": referrer_bonus
    })


@app.post("/api/v1/withdraw")
async def request_withdraw(data: WithdrawRequest):
    init_data = data.init_data
    
    try:
        auth_data = init_data_auth(init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for withdraw endpoint: {e.detail}")
        raise e
        
    user_id = auth_data['id']
    username = auth_data.get('username') or f"id_{user_id}"
    amount = data.amount
    
    MIN_WITHDRAW = 50.0 # НОВОЕ: Минимальный вывод 50.0
    if amount < MIN_WITHDRAW:
        raise HTTPException(status_code=400, detail=f"Минимальная сумма вывода: {MIN_WITHDRAW} ★.")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Проверка баланса
    cursor.execute("SELECT stars FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
        
    current_stars = result[0]
    
    if amount > current_stars:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе.")

    # 2. Списание и создание заявки
    new_stars = current_stars - amount
    
    cursor.execute("UPDATE users SET stars = ? WHERE id = ?", (new_stars, user_id))
    
    cursor.execute("""
        INSERT INTO withdrawals (user_id, username, amount)
        VALUES (?, ?, ?)
    """, (user_id, username, amount))
    
    conn.commit()
    conn.close()
    
    logger.info(f"Withdrawal requested: User {username} ({user_id}) requested {amount} ★")
    
    return JSONResponse(content={
        "status": "ok",
        "message": f"Заявка на вывод {amount} ★ принята в обработку. Ожидайте подтверждения.",
        "new_stars": new_stars # Возвращаем новый баланс для обновления UI
    })


# --- АДМИН ПАНЕЛЬ ---

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    if not ADMIN_TG_ID:
        return False
    return str(user_id) == ADMIN_TG_ID


@app.get("/admin/withdrawals", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """Отдача пустой HTML страницы, чтобы удовлетворить требованию TWA."""
    # Поскольку вся логика встроена во фронтенд index.html, 
    # этот эндпойнт должен быть адаптирован, если бы админ-панель была отдельной страницей.
    # Но для TWA можно оставить или удалить, если не используется. Оставляю для совместимости.
    return templates.TemplateResponse("admin.html", {"request": request, "admin_tg_id": ADMIN_TG_ID})


@app.post("/api/v1/admin/withdrawals")
async def get_all_withdrawals(data: RequestData):
    """Получение списка всех заявок."""
    init_data = data.init_data
    
    try:
        auth_data = init_data_auth(init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for admin endpoint: {e.detail}")
        raise e
        
    if not is_admin(auth_data['id']):
        raise HTTPException(status_code=403, detail="Доступ запрещен. Требуются права администратора.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    # НОВОЕ: Добавляем user_id в выборку, чтобы было видно, кто выводит
    cursor.execute("SELECT id, user_id, username, amount, status, created_at FROM withdrawals ORDER BY created_at DESC")
    withdrawals = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return JSONResponse(content={"withdrawals": withdrawals})


@app.post("/api/v1/admin/action")
async def process_admin_action(data: AdminAction):
    """Обработка заявки (approve/reject)."""
    init_data = data.init_data
    withdrawal_id = data.withdrawal_id
    action = data.action
    
    try:
        auth_data = init_data_auth(init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for admin action: {e.detail}")
        raise e

    if not is_admin(auth_data['id']):
        raise HTTPException(status_code=403, detail="Доступ запрещен.")
        
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (withdrawal_id,))
    withdrawal = cursor.fetchone()
    
    if not withdrawal:
        conn.close()
        raise HTTPException(status_code=404, detail="Заявка не найдена.")

    user_id, amount, current_status = withdrawal
    
    if current_status != 'pending':
        conn.close()
        raise HTTPException(status_code=400, detail=f"Заявка уже имеет статус: {current_status}")

    if action == 'approve':
        new_status = 'approved'
        cursor.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (new_status, withdrawal_id))
        conn.commit()
        
    elif action == 'reject':
        new_status = 'rejected'
        # Возвращаем средства на баланс пользователя
        cursor.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (amount, user_id))
        cursor.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (new_status, withdrawal_id))
        conn.commit()
        
    else:
        conn.close()
        raise HTTPException(status_code=400, detail="Неверное действие.")
        
    conn.close()
    logger.info(f"Admin Action: Withdrawal #{withdrawal_id} updated to {new_status} by Admin {auth_data['id']}")
    return JSONResponse(content={"status": "ok", "message": f"Заявка #{withdrawal_id} обновлена до {new_status}"})


# --- Основная точка входа для Railway ---
if __name__ == "__main__":
    PORT = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
