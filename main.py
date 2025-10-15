import os
import logging
import asyncio
import sqlite3
import hmac
import hashlib
import json             # <-- КРИТИЧЕСКИЙ ФИКС: Добавлен импорт json
import random           # <-- КРИТИЧЕСКИЙ ФИКС: Добавлен импорт random
from time import time
from typing import Optional, Dict, List
from urllib.parse import parse_qs, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates 
from pydantic import BaseModel
import uvicorn

from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Настройка логирования ---
# Установим уровень INFO для вывода критических сообщений в Railway
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
if not ADMIN_TG_ID:
    logger.warning("ADMIN_TG_ID не установлен. Доступ к админ-панели будет отключен.")


# === МОДЕЛИ Pydantic ===

class RequestData(BaseModel):
    init_data: str # Строка инициализации, отправленная клиентом

class WithdrawRequest(BaseModel):
    init_data: str
    amount: float

class BlastResponse(BaseModel):
    prize_amount: float
    new_stars: float
    new_dynamite: int

class AdminAction(BaseModel):
    init_data: str
    withdrawal_id: int
    action: str # 'approve' или 'reject'


# === ИНИЦИАЛИЗАЦИЯ БД и УТИЛИТЫ ===

def get_db_connection():
    # Создаем директорию для БД, если ее нет (важно для Docker/Railway)
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    try:
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
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error during database initialization: {e}")
        # Вызовем исключение, если БД не инициализируется, чтобы избежать дальнейших сбоев
        raise

# Вызов инициализации БД при запуске
initialize_db()

# --- Логика аутентификации Telegram Web App ---
def init_data_auth(init_data: str) -> Dict[str, any]:
    """
    Проверяет hash, подписанный Telegram, и возвращает данные пользователя.
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="Auth failed: No init_data provided.")

    try:
        # 1. Секретный ключ, производный от TELEGRAM_TOKEN
        key = hmac.new(
            key=TELEGRAM_TOKEN.strip().encode(),
            msg=b"WebAppData",
            digestmod=hashlib.sha256
        ).digest()
    except Exception as e:
        logger.error(f"Error creating HMAC key: {e}")
        raise HTTPException(status_code=500, detail="Internal Auth Error.")


    # 2. Парсинг и декодирование
    query_params = parse_qs(unquote(init_data)) 
    
    # Извлечение хеша
    received_hash_list = query_params.pop('hash', [None])
    received_hash = received_hash_list[0]

    if not received_hash or not query_params.get('auth_date'):
        raise HTTPException(status_code=401, detail="Auth failed: Missing hash or auth_date.")

    # 3. Формирование строки для проверки хеша
    data_check_string = "\n".join([
        f"{key}={value[0]}"
        for key, value in sorted(query_params.items())
    ])

    # 4. Вычисляем HMAC-SHA256
    calculated_hash = hmac.new(
        key=key,
        msg=data_check_string.encode(),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    # --- ДОБАВЛЕНО ДЛЯ ДЕБАГА --- (Поможет диагностировать 401 ошибку)
    logger.info("--- AUTH DEBUG START ---")
    logger.info(f"DATA CHECK STRING: '{data_check_string[:100]}...'")
    logger.info(f"CALCULATED HASH: {calculated_hash}")
    logger.info(f"RECEIVED HASH: {received_hash}")
    logger.info("--- AUTH DEBUG END ---")
    # -----------------------------

    # 5. Сравнение хешей
    if calculated_hash != received_hash:
        logger.error(f"Auth failed: Hash mismatch! Calculated: {calculated_hash}, Received: {received_hash}")
        raise HTTPException(status_code=401, detail="Auth failed: Hash mismatch.")

    # 6. Извлечение данных пользователя
    user_data = query_params.get('user', query_params.get('receiver', [None]))[0]
    if not user_data:
        raise HTTPException(status_code=401, detail="Auth failed: User data not found.")
        
    try:
        auth_data = json.loads(user_data) # <-- ТЕПЕРЬ 'json' ОПРЕДЕЛЕН
    except json.JSONDecodeError as e:
        logger.error(f"Auth failed: JSON decode error on user data: {e}. Data: {user_data[:100]}...")
        raise HTTPException(status_code=401, detail="Auth failed: Invalid user data format.")
    
    # Проверка актуальности (5 минут) - опционально, но рекомендуется
    # auth_date = int(query_params['auth_date'][0])
    # if time() - auth_date > 300:
    #     raise HTTPException(status_code=401, detail="Auth failed: Data too old ( > 5 min).")

    return auth_data


# --- ЛОГИКА БД (ПОЛЬЗОВАТЕЛЬ) ---

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
                
        # Вставка нового пользователя
        cursor.execute("""
            INSERT INTO users (id, username, stars, dynamite, referrer_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, 0.0, 3, referrer_id))
        conn.commit()
        
        # Повторный запрос для получения полных данных (включая default values)
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        logger.info(f"New user created: {username} ({user_id}). Referrer: {referrer_id}")
        
    conn.close()
    return dict(user)


# --- API FastAPI ---
app = FastAPI()
templates = Jinja2Templates(directory=".") # Шаблоны из текущей папки

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Отдача HTML-страницы приложения."""
    # Получение параметра 'tgWebAppStartParam' из URL (если пользователь пришел по реф. ссылке)
    start_param = request.query_params.get("tgWebAppStartParam")
    
    return templates.TemplateResponse("index.html", {"request": request, "start_param": start_param})


@app.post("/api/v1/data")
async def get_user_data(data: RequestData):
    """Получение всех данных пользователя и реферальной информации."""
    init_data = data.init_data 
    
    # 1. Аутентификация
    try:
        auth_data = init_data_auth(init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for data endpoint: {e.detail}")
        raise e
        
    user_id = auth_data['id']
    username = auth_data.get('username') or f"id_{user_id}"
    
    # 2. Получение или создание пользователя
    # start_parameter не доступен напрямую в init_data, поэтому регистрация реферера 
    # должна происходить через команду /start в боте.
    user_data = get_or_create_user(user_id, username)
    
    # 3. Подсчет рефералов
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    referrals_count = cursor.fetchone()[0]
    conn.close()
    
    return JSONResponse(content={
        "user_data": user_data,
        "referrals_count": referrals_count,
        "bot_username": BOT_USERNAME,
        "is_admin": str(user_id) == ADMIN_TG_ID
    })


@app.post("/api/v1/blast", response_model=BlastResponse)
async def blast_mine(data: RequestData):
    """Выполнение взрыва (майнинг)."""
    init_data = data.init_data
    
    try:
        auth_data = init_data_auth(init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for blast endpoint: {e.detail}")
        raise e

    user_id = auth_data['id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Проверка динамита и кулдауна (блокировка на уровне БД)
    cursor.execute("SELECT stars, dynamite, last_blast FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
        
    current_stars, current_dynamite, last_blast = result
    
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
    
    # Случайный приз от 0.05 до 0.15
    # import random уже добавлен в начале
    prize_amount = round(random.uniform(0.05, 0.15), 2)
    
    new_stars = current_stars + prize_amount
    new_dynamite = current_dynamite - 1
    
    cursor.execute("""
        UPDATE users 
        SET stars = ?, 
            dynamite = ?, 
            last_blast = ? 
        WHERE id = ?
    """, (new_stars, new_dynamite, current_time, user_id))
    
    conn.commit()
    conn.close()
    
    return JSONResponse(content={
        "prize_amount": prize_amount,
        "new_stars": new_stars,
        "new_dynamite": new_dynamite
    })


@app.post("/api/v1/withdraw")
async def request_withdraw(data: WithdrawRequest):
    """Создание заявки на вывод."""
    init_data = data.init_data
    
    try:
        auth_data = init_data_auth(init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for withdraw endpoint: {e.detail}")
        raise e
        
    user_id = auth_data['id']
    username = auth_data.get('username') or f"id_{user_id}"
    amount = data.amount
    
    MIN_WITHDRAW = 10.0
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
        "message": f"Заявка на вывод {amount} ★ принята в обработку. Ожидайте подтверждения."
    })


# --- АДМИН ПАНЕЛЬ (для тестирования) ---

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    if not ADMIN_TG_ID:
        return False
    return str(user_id) == ADMIN_TG_ID


@app.get("/admin/withdrawals", response_class=HTMLResponse)
async def admin_panel(request: Request):
    """
    Простейшая админ-панель для просмотра и обработки заявок.
    Требует аутентификации через init_data (для Railway).
    """
    # Этот эндпойнт должен быть защищен
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
        # Деньги уже списаны при создании заявки. Просто обновляем статус.
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
    # Запуск только FastAPI.
    # Если вам нужно, чтобы бот (polling) работал вместе с FastAPI, 
    # нужно использовать асинхронный запуск, но это часто вызывает проблемы.
    # В Railway лучше запускать два отдельных сервиса (один для FastAPI, один для бота) или 
    # использовать вебхуки.
    # Для простого запуска Web App используем Uvicorn.
    PORT = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=PORT)
