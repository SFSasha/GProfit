import os
import logging
import asyncio
import sqlite3
import hmac
import hashlib
import json  # Добавлен
import random  # Добавлен
from time import time
from typing import Optional, Dict, List
from urllib.parse import parse_qs, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn

import telegram
from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

# --- Настройка логирования ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Получение переменных окружения ---
# Токен бота, который вы получили от @BotFather
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
# URL вашего веб-приложения, который сгенерирует Railway
WEBAPP_URL = os.environ.get("WEBAPP_URL")

if not TELEGRAM_TOKEN:
    raise ValueError("Не найден TELEGRAM_TOKEN в переменных окружения!")
if not WEBAPP_URL:
    raise ValueError("Не найден WEBAPP_URL в переменных окружения! Сначала задеплойте проект, получите URL и добавьте его.")

# --- ГЛОБАЛЬНЫЕ КОНСТАНТЫ И КОНФИГУРАЦИЯ ---
DB_PATH = "/data/app.db" # <-- ДОБАВЛЕНО/ИСПРАВЛЕНО
BOT_USERNAME = os.environ.get("BOT_USERNAME", "star_miner_bot") # <-- ДОБАВЛЕНО
ADMIN_TG_ID = os.environ.get("ADMIN_TG_ID") # <-- ДОБАВЛЕНО

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
    referrer_bonus: float = 0.0

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
# --- Логика аутентификации Telegram Web App ---
# --- Логика аутентификации Telegram Web App (ИСПРАВЛЕНО) ---
def init_data_auth(init_data: str) -> Dict[str, any]:
    if not init_data:
        raise HTTPException(status_code=401, detail="Auth failed: No init_data provided.")

    try:
        # Ваш бот-токен используется как ключ для HMAC
        key = hmac.new(
            key=TELEGRAM_TOKEN.encode(),
            msg=b"WebAppData",
            digestmod=hashlib.sha256
        ).digest()
    except Exception as e:
        logger.error(f"Error creating HMAC key: {e}")
        raise HTTPException(status_code=500, detail="Internal Auth Error.")
    
    # 1. Разделяем init_data на отдельные пары "ключ=значение"
    params = init_data.split('&')
    
    # 2. Ищем hash и собираем список сырых данных для проверки
    data_check = []
    received_hash = None
    
    for param in params:
        if param.startswith('hash='):
            received_hash = param.split('=', 1)[1]
        elif param.startswith('signature='): # <--- НОВОЕ: ИСКЛЮЧАЕМ signature
            continue
        else:
            # Все остальные СЫРЫЕ пары добавляем в список
            data_check.append(param)

    if not received_hash:
        raise HTTPException(status_code=401, detail="Auth failed: Missing hash.")

    # 3. Сортируем сырые пары по ключу (алфавитный порядок)
    data_check.sort()
    
    # 4. Объединяем их через \n (это и есть data_check_string)
    data_check_string = "\n".join(data_check)
    
    # 5. Рассчитываем хэш
    calculated_hash = hmac.new(
        key=key,
        msg=data_check_string.encode(), # Используем сырую строку
        digestmod=hashlib.sha256
    ).hexdigest()

    # 6. Сравнение
    if calculated_hash != received_hash:
        logger.error(f"Auth failed: Hash mismatch! Calculated: {calculated_hash}, Received: {received_hash}. String checked: {data_check_string}")
        raise HTTPException(status_code=401, detail="Auth failed: Hash mismatch.")

    # ... оставшаяся часть функции остается без изменений
    query_params = parse_qs(unquote(init_data))
    user_data = query_params.get('user', query_params.get('receiver', [None]))[0]
    
    if not user_data:
        raise HTTPException(status_code=401, detail="Auth failed: User data not found.")

    auth_data = json.loads(user_data)
    
    start_param = query_params.get('tgWebAppStartParam', [None])[0]
    if start_param:
        auth_data['start_param'] = start_param
    
    return auth_data


# --- ЛОГИКА БД (ПОЛЬЗОВАТЕЛЬ) ---
INITIAL_STAR_BONUS = 2.0  # Приветственный бонус
MIN_WITHDRAW = 50.0 # Минимальный вывод

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
        """, (user_id, username, INITIAL_STAR_BONUS, 3, referrer_id))
        conn.commit()

        # Повторный запрос для получения полных данных
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        logger.info(f"New user created: {username} ({user_id}). Referrer: {referrer_id}, Bonus: {INITIAL_STAR_BONUS} ★")

    conn.close()
    return dict(user)

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    if not ADMIN_TG_ID:
        return False
    return str(user_id) == ADMIN_TG_ID

# --- Настройка бота (КОД ИЗ ВАШЕГО ПОСЛЕДНЕГО ФАЙЛА) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение с кнопкой для запуска Web App."""
    
    user_id = update.effective_user.id
    start_parameter = context.args[0] if context.args else ""
    
    # Передача реферального параметра или ID пользователя для инициализации
    app_url_with_params = f"{WEBAPP_URL}?tgWebAppStartParam={start_parameter or user_id}"
    
    keyboard = [
        [InlineKeyboardButton(
            "🚀 Открыть Star Miner",
            web_app=WebAppInfo(url=app_url_with_params)
        )]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Нажмите на кнопку, чтобы запустить Web App и начать добычу Звезд!",
        reply_markup=reply_markup
    )

async def setup_bot():
    """Настраивает и запускает бота в фоновом режиме."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))

    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("Telegram бот запущен...")

# --- Настройка FastAPI (веб-сервер) ---
app = FastAPI()
templates = Jinja2Templates(directory=".") # Указан текущий каталог

@app.on_event("startup")
async def startup_event():
    """При старте сервера запускаем бота."""
    asyncio.create_task(setup_bot())

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Отдает главную HTML-страницу веб-приложения."""
    # Получаем параметр из URL, чтобы передать его в Web App для логики рефералов
    start_param = request.query_params.get("tgWebAppStartParam")
    return templates.TemplateResponse("index.html", {"request": request, "start_param": start_param})

# --- API ЭНДПОИНТЫ ---

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
    # Параметр tgWebAppStartParam передается из фронтенда при первом запуске
    start_param = auth_data.get('start_param')

    user_data = get_or_create_user(user_id, username, start_param)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    referrals_count = cursor.fetchone()[0]
    conn.close()

    return JSONResponse(content={
        "user_data": user_data,
        "referrals_count": referrals_count,
        "bot_username": BOT_USERNAME,
        "is_admin": is_admin(user_id)
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

    MIN_BLAST_INTERVAL = 15 # секунд (уменьшено для тестирования, можно изменить)
    current_time = int(time())

    if current_dynamite <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Нет динамита (0 💣). Пригласите друга.")

    if current_time - last_blast < MIN_BLAST_INTERVAL:
        remaining = MIN_BLAST_INTERVAL - (current_time - last_blast)
        conn.close()
        raise HTTPException(status_code=429, detail=f"Пожалуйста, подождите {remaining} секунд до следующего взрыва.")

    # 2. Расчет добычи и обновление баланса
    PRIZE_AMOUNTS = [0.1, 0.3, 0.5, 1.0, 3.0, 5.0]
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
        REFERRAL_PERCENT = 0.10
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

    # Заявка с юзером телеграма
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
        "new_stars": new_stars
    })

# --- АДМИН ПАНЕЛЬ API ---

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
    # Railway предоставит переменную PORT
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
