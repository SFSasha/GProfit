import os
import logging
import asyncio
import sqlite3
import json
from time import time
from typing import Optional, Dict
from urllib.parse import parse_qs, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
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

# --- ГЛОБАЛЬНАЯ КОНФИГУРАЦИЯ ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL")

# Используем Volume Railway. Файл БД будет храниться в /data/app.db
DB_PATH = "/data/app.db"
# Используется в качестве заглушки для реферальной ссылки
BOT_USERNAME = os.environ.get("BOT_USERNAME", "star_miner_bot") 

if not TELEGRAM_TOKEN:
    raise ValueError("Не найден TELEGRAM_TOKEN в переменных окружения!")
if not WEBAPP_URL:
    raise ValueError("Не найден WEBAPP_URL в переменных окружения!")

# === МОДЕЛИ Pydantic ===

class WithdrawRequest(BaseModel):
    amount: float

class BlastResponse(BaseModel):
    prize_amount: float
    new_stars: float
    new_dynamite: int

# === ИНИЦИАЛИЗАЦИЯ БД и УТИЛИТЫ ===

def get_db_connection():
    """Возвращает соединение с БД."""
    return sqlite3.connect(DB_PATH)

def init_db():
    """Инициализирует базу данных, создавая таблицы."""
    # Убедимся, что директория /data существует
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            stars REAL DEFAULT 0.0,
            dynamite INTEGER DEFAULT 0,
            referrer_id INTEGER,
            referral_earnings REAL DEFAULT 0.0
        )
    """)
    
    # Таблица заявок на вывод
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending', -- pending, processing, completed, rejected
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    logger.info(f"Database initialized at {DB_PATH}")

def get_user(user_id: int, initial_data: Optional[Dict] = None):
    """Получает или создает пользователя по ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    
    if user_row:
        # User exists
        keys = ["id", "username", "first_name", "stars", "dynamite", "referrer_id", "referral_earnings"]
        user_data = dict(zip(keys, user_row))
        conn.close()
        return user_data
    else:
        # User does not exist, create new
        new_stars = 0.0
        new_dynamite = 1 # Стартовая взрывчатка
        
        # Обработка реферального параметра
        referrer_id = None
        if initial_data and initial_data.get('start_param'):
            try:
                referrer_id = int(initial_data['start_param'])
                
                # Логика начисления 1 динамита рефереру (проверка, что реферер существует)
                cursor.execute("SELECT id FROM users WHERE id = ?", (referrer_id,))
                if cursor.fetchone():
                     cursor.execute("UPDATE users SET dynamite = dynamite + 1 WHERE id = ?", (referrer_id,))
                     conn.commit()
                     logger.info(f"User {user_id} referred by {referrer_id}. Dynamite credited.")
                else:
                    referrer_id = None # Отключаем реферера, если он не существует

            except ValueError:
                pass # start_param не является числом

        username = initial_data.get('username') if initial_data else None
        first_name = initial_data.get('first_name') if initial_data else None

        cursor.execute("""
            INSERT INTO users (id, username, first_name, stars, dynamite, referrer_id, referral_earnings)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, first_name, new_stars, new_dynamite, referrer_id, 0.0))
        
        conn.commit()
        conn.close()
        
        return {
            "id": user_id,
            "username": username,
            "first_name": first_name,
            "stars": new_stars,
            "dynamite": new_dynamite,
            "referrer_id": referrer_id,
            "referral_earnings": 0.0
        }

def get_user_referrals_count(user_id: int) -> int:
    """Считает количество рефералов пользователя."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(id) FROM users WHERE referrer_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def check_init_data_auth(init_data: str) -> Optional[Dict]:
    """
    Имитация проверки initData (только парсинг). 
    ВАЖНО: В продакшене используйте криптографическую проверку hash!
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствуют данные инициализации.")

    # Декодирование и парсинг initData
    parsed_data = parse_qs(init_data)
    user_data_str = parsed_data.get('user', [None])[0]
    start_param = parsed_data.get('start_param', [None])[0]
    
    if not user_data_str:
        # Эту ошибку могут вызвать боты, но не реальные пользователи. Пропускаем.
        logger.warning("User data missing in initData.")
        raise HTTPException(status_code=401, detail="Данные пользователя не найдены.")

    try:
        user_info = json.loads(unquote(user_data_str))
        user_id = user_info.get('id')
        if not user_id:
            raise HTTPException(status_code=401, detail="ID пользователя не найден.")
        
        return {
            "id": user_id,
            "username": user_info.get('username'),
            "first_name": user_info.get('first_name'),
            "start_param": start_param
        }

    except Exception as e:
        logger.error(f"Error parsing initData: {e}")
        raise HTTPException(status_code=401, detail=f"Неверный формат данных: {e}")

# === НАСТРОЙКА БОТА ===

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение с кнопкой для запуска Web App и реферальным параметром."""
    user_id = update.effective_user.id
    
    # Передаем ID пользователя как реферальный параметр
    start_url = f"{WEBAPP_URL}?start={user_id}"

    keyboard = [
        [InlineKeyboardButton(
            "🚀 Открыть Web App",
            web_app=WebAppInfo(url=start_url)
        )]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Привет! Нажми на кнопку ниже, чтобы запустить Web App. Твой ID используется как реферальный параметр.",
        reply_markup=reply_markup
    )

async def setup_bot():
    """Настраивает и запускает бота в фоновом режиме."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    # Запускаем бота в фоновом режиме
    await application.initialize()
    await application.start()
    await application.updater.start_polling(poll_interval=1.0) # Устанавливаем poll_interval для Railway
    logger.info("Telegram бот запущен...")

# === НАСТРОЙКА FASTAPI (веб-сервер) ===
app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """При старте сервера инициализируем БД и запускаем бота."""
    init_db()
    # Создаем задачу для запуска бота в фоне
    asyncio.create_task(setup_bot())

@app.get("/", response_class=HTMLResponse)
async def serve_app():
    """Отдает статический index.html."""
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
            # Вставляем юзернейм бота в HTML
            html_content = html_content.replace("YOUR_BOT_USERNAME_HERE", BOT_USERNAME)
        return html_content
    except FileNotFoundError:
        return HTMLResponse("<html><body><h1>index.html не найден. Убедитесь, что он есть в корне проекта.</h1></body></html>", status_code=404)

# === API ЭНДПОИНТЫ ===

@app.post("/api/v1/data")
async def get_user_data(request: Request):
    """Получает данные пользователя, проверяя initData."""
    try:
        body = await request.json()
        init_data = body.get('init_data')
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат запроса.")

    auth_data = check_init_data_auth(init_data)
    user_id = auth_data['id']
    
    user = get_user(user_id, auth_data)
    referrals_count = get_user_referrals_count(user_id)
    
    return JSONResponse(content={
        "status": "ok",
        "user_data": user,
        "referrals_count": referrals_count,
        "bot_username": BOT_USERNAME
    })

@app.post("/api/v1/chest/blast", response_model=BlastResponse)
async def blast_chest(request: Request):
    """Обрабатывает взрыв сундука."""
    try:
        body = await request.json()
        init_data = body.get('init_data')
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат запроса.")

    auth_data = check_init_data_auth(init_data)
    user_id = auth_data['id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Проверка взрывчатки
    cursor.execute("SELECT dynamite, stars, referrer_id FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
        
    current_dynamite, current_stars, referrer_id = result
    
    if current_dynamite <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно взрывчатки.")

    # 2. Логика приза
    prizes = [0.1, 0.3, 0.5, 1.0, 3.0, 10.0]
    import random
    prize = random.choice(prizes)
    
    # 3. Начисление рефереру (10% комиссии)
    referral_commission = prize * 0.10
    
    if referrer_id:
        try:
            cursor.execute("""
                UPDATE users SET stars = stars + ?, referral_earnings = referral_earnings + ? WHERE id = ?
            """, (referral_commission, referral_commission, referrer_id))
            logger.info(f"Referral commission {referral_commission} credited to {referrer_id}")
        except Exception as e:
            logger.error(f"Failed to credit referrer {referrer_id}: {e}")
            
    # 4. Обновление БД для текущего пользователя
    new_stars = current_stars + prize
    new_dynamite = current_dynamite - 1
    
    cursor.execute("""
        UPDATE users SET stars = ?, dynamite = ? WHERE id = ?
    """, (new_stars, new_dynamite, user_id))
    
    conn.commit()
    conn.close()

    return JSONResponse(content={
        "prize_amount": prize,
        "new_stars": new_stars,
        "new_dynamite": new_dynamite
    })


@app.post("/api/v1/withdraw/request")
async def request_withdraw(request: Request, data: WithdrawRequest):
    """Создает заявку на вывод."""
    try:
        body = await request.json()
        init_data = body.get('init_data')
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат запроса.")

    auth_data = check_init_data_auth(init_data)
    user_id = auth_data['id']
    username = auth_data['username'] or f"id_{user_id}"
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

    # 2. Вычитание средств и создание заявки
    new_stars = current_stars - amount
    
    cursor.execute("UPDATE users SET stars = ? WHERE id = ?", (new_stars, user_id))
    
    # В заявку падает сумма и юзернейм/ID
    cursor.execute("""
        INSERT INTO withdrawals (user_id, username, amount)
        VALUES (?, ?, ?)
    """, (user_id, username, amount))
    
    conn.commit()
    conn.close()
    
    logger.info(f"Withdrawal requested: User {username} ({user_id}) requested {amount} ★")
    
    return JSONResponse(content={
        "status": "ok",
        "message": "Заявка на вывод успешно создана.",
        "new_stars": new_stars
    })

# --- Основная точка входа для Railway ---
if __name__ == "__main__":
    # Railway предоставит переменную PORT
    port = int(os.environ.get("PORT", 8000))
    # Запуск uvicorn без запуска бота, так как setup_bot() вызывается в startup_event
    uvicorn.run(app, host="0.0.0.0", port=port)
