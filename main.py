import os
import logging
import asyncio
import sqlite3
import json
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

class WithdrawRequest(BaseModel):
    amount: float

class BlastResponse(BaseModel):
    prize_amount: float
    new_stars: float
    new_dynamite: int

class AdminAction(BaseModel):
    withdrawal_id: int
    action: str # 'approve' or 'reject'

class ClaimBonusResponse(BaseModel):
    new_stars: float
    last_claim_time: float # Новое время сбора бонуса

# === ИНИЦИАЛИЗАЦИЯ БД и УТИЛИТЫ ===

def get_db_connection():
    """Возвращает соединение с БД."""
    return sqlite3.connect(DB_PATH)

def init_db():
    """Инициализирует базу данных, создавая таблицы."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Обновление схемы: добавлено last_claim_time
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            stars REAL DEFAULT 0.0,
            dynamite INTEGER DEFAULT 0,
            referrer_id INTEGER,
            referral_earnings REAL DEFAULT 0.0,
            last_claim_time REAL DEFAULT 0.0 -- Время последнего сбора бонуса (timestamp)
        )
    """)
    
    # Проверка и добавление колонки, если она отсутствует (для совместимости)
    try:
        cursor.execute("SELECT last_claim_time FROM users LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE users ADD COLUMN last_claim_time REAL DEFAULT 0.0")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            amount REAL,
            status TEXT DEFAULT 'pending', 
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
    
    cursor.execute("SELECT id, username, first_name, stars, dynamite, referrer_id, referral_earnings, last_claim_time FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    
    keys = ["id", "username", "first_name", "stars", "dynamite", "referrer_id", "referral_earnings", "last_claim_time"]

    if user_row:
        user_data = dict(zip(keys, user_row))
        conn.close()
        return user_data
    else:
        # Логика создания нового пользователя
        referrer_id = None
        if initial_data and initial_data.get('start_param'):
            try:
                # Попытка получить ID реферера
                potential_referrer_id = int(initial_data['start_param'])
                cursor.execute("SELECT id FROM users WHERE id = ?", (potential_referrer_id,))
                if cursor.fetchone():
                     referrer_id = potential_referrer_id
                     # Начисляем динамит рефереру за приглашение
                     cursor.execute("UPDATE users SET dynamite = dynamite + 1 WHERE id = ?", (referrer_id,))
                     conn.commit()
            except ValueError:
                pass # start_param не является числом

        username = initial_data.get('username')
        first_name = initial_data.get('first_name')

        new_user_data = {
            "id": user_id,
            "username": username,
            "first_name": first_name,
            "stars": 0.0,
            "dynamite": 1,
            "referrer_id": referrer_id,
            "referral_earnings": 0.0,
            "last_claim_time": 0.0
        }

        cursor.execute("""
            INSERT INTO users (id, username, first_name, stars, dynamite, referrer_id, referral_earnings, last_claim_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, username, first_name, new_user_data["stars"], new_user_data["dynamite"], 
              new_user_data["referrer_id"], new_user_data["referral_earnings"], new_user_data["last_claim_time"]))
        
        conn.commit()
        conn.close()
        
        return new_user_data

def get_user_referrals_count(user_id: int) -> int:
    """Считает количество рефералов пользователя."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(id) FROM users WHERE referrer_id = ?", (user_id,))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def check_init_data_auth(init_data: str) -> Optional[Dict]:
    """Имитация проверки initData (только парсинг)."""
    # В реальном приложении здесь должна быть криптографическая проверка HMAC
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствуют данные инициализации.")

    parsed_data = parse_qs(init_data)
    user_data_str = parsed_data.get('user', [None])[0]
    start_param = parsed_data.get('start_param', [None])[0]
    
    if not user_data_str:
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
    start_url = f"{WEBAPP_URL}?start={user_id}"

    keyboard = [
        [InlineKeyboardButton(
            "🚀 Открыть Star Miner App",
            web_app=WebAppInfo(url=start_url)
        )]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Добро пожаловать в Star Miner! Нажмите, чтобы начать добычу.",
        reply_markup=reply_markup
    )

async def setup_bot():
    """Настраивает и запускает бота в фоновом режиме."""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling(poll_interval=1.0)
    logger.info("Telegram бот запущен...")

# === НАСТРОЙКА FASTAPI (веб-сервер) ===
app = FastAPI()
templates = Jinja2Templates(directory="templates") 


@app.on_event("startup")
async def startup_event():
    """При старте сервера инициализируем БД и запускаем бота."""
    init_db()
    asyncio.create_task(setup_bot())

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Отдает главную HTML-страницу веб-приложения, используя Jinja2."""
    # Передаем ID администратора в шаблон, чтобы фронтенд знал, кто админ
    admin_id_int = int(ADMIN_TG_ID) if ADMIN_TG_ID and ADMIN_TG_ID.isdigit() else None
    
    return templates.TemplateResponse(
        "index.html", 
        {"request": request, "BOT_USERNAME": BOT_USERNAME, "ADMIN_TG_ID": admin_id_int} 
    )

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
    
    is_admin = False
    if ADMIN_TG_ID and str(user_id) == ADMIN_TG_ID:
        is_admin = True
    
    return JSONResponse(content={
        "status": "ok",
        "user_data": user,
        "referrals_count": referrals_count,
        "bot_username": BOT_USERNAME,
        "is_admin": is_admin
    })

@app.post("/api/v1/claim/bonus", response_model=ClaimBonusResponse)
async def claim_bonus(request: Request):
    """Обрабатывает сбор бонуса раз в 10 минут."""
    try:
        body = await request.json()
        init_data = body.get('init_data')
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат запроса.")

    auth_data = check_init_data_auth(init_data)
    user_id = auth_data['id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT stars, last_claim_time FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
        
    current_stars, last_claim_time = result
    
    current_time = time()
    CLAIM_INTERVAL = 10 * 60 # 10 минут в секундах
    BONUS_AMOUNT = 0.2
    
    if (current_time - last_claim_time) < CLAIM_INTERVAL:
        conn.close()
        # Вычисляем оставшееся время для фронтенда
        remaining = CLAIM_INTERVAL - (current_time - last_claim_time)
        raise HTTPException(status_code=400, detail=f"Подождите еще {int(remaining)} секунд до следующего сбора.")

    # Начисление бонуса
    new_stars = current_stars + BONUS_AMOUNT
    new_claim_time = current_time
    
    cursor.execute("""
        UPDATE users SET stars = ?, last_claim_time = ? WHERE id = ?
    """, (new_stars, new_claim_time, user_id))
    
    conn.commit()
    conn.close()

    return JSONResponse(content={
        "new_stars": new_stars,
        "last_claim_time": new_claim_time
    })


@app.post("/api/v1/chest/blast", response_model=BlastResponse)
async def blast_chest(request: Request):
    """Обрабатывает взрыв сундука."""
    # (Логика оставлена без изменений, так как она не вызывала проблем)
    try:
        body = await request.json()
        init_data = body.get('init_data')
    except Exception:
        raise HTTPException(status_code=400, detail="Неверный формат запроса.")

    auth_data = check_init_data_auth(init_data)
    user_id = auth_data['id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT dynamite, stars, referrer_id FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
        
    current_dynamite, current_stars, referrer_id = result
    
    if current_dynamite <= 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно взрывчатки.")

    prizes = [0.1, 0.3, 0.5, 1.0, 3.0, 10.0]
    import random
    prize = random.choice(prizes)
    
    referral_commission = prize * 0.10
    
    if referrer_id:
        try:
            # Начисление комиссии рефереру (только звездами)
            cursor.execute("SELECT stars, referral_earnings FROM users WHERE id = ?", (referrer_id,))
            referrer_data = cursor.fetchone()
            if referrer_data:
                new_ref_stars = referrer_data[0] + referral_commission
                new_ref_earnings = referrer_data[1] + referral_commission
                cursor.execute("""
                    UPDATE users SET stars = ?, referral_earnings = ? WHERE id = ?
                """, (new_ref_stars, new_ref_earnings, referrer_id))
                conn.commit()

        except Exception as e:
            logger.error(f"Failed to credit referrer {referrer_id}: {e}")
            
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
    # (Логика оставлена без изменений)
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
    
    cursor.execute("SELECT stars FROM users WHERE id = ?", (user_id,))
    result = cursor.fetchone()
    if not result:
        conn.close()
        raise HTTPException(status_code=404, detail="Пользователь не найден.")
        
    current_stars = result[0]
    
    if amount > current_stars:
        conn.close()
        raise HTTPException(status_code=400, detail="Недостаточно средств на балансе.")

    new_stars = current_stars - amount
    
    # Сначала уменьшаем баланс
    cursor.execute("UPDATE users SET stars = ? WHERE id = ?", (new_stars, user_id))
    
    # Затем создаем заявку
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

# --- АДМИН ЭНДПОИНТЫ ---

@app.get("/api/v1/admin/withdrawals", response_model=List[Dict])
async def get_withdrawals(request: Request):
    """Получает все ожидающие заявки (только для админа)."""
    # Проверка админа
    try:
        query_params = request.query_params
        init_data = query_params.get('init_data')
        auth_data = check_init_data_auth(init_data)
        if not ADMIN_TG_ID or str(auth_data['id']) != ADMIN_TG_ID:
            raise HTTPException(status_code=403, detail="Доступ запрещен.")
    except Exception:
        raise HTTPException(status_code=403, detail="Доступ запрещен или неверные данные.")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, user_id, username, amount, status, created_at FROM withdrawals WHERE status = 'pending' ORDER BY created_at ASC")
    rows = cursor.fetchall()
    
    keys = ["id", "user_id", "username", "amount", "status", "created_at"]
    withdrawals = [dict(zip(keys, row)) for row in rows]
    
    conn.close()
    return withdrawals

@app.post("/api/v1/admin/action")
async def process_admin_action(request: Request, data: AdminAction):
    """Подтверждает или отклоняет заявку (только для админа)."""
    # Проверка админа
    try:
        body = await request.json()
        init_data = body.get('init_data')
        auth_data = check_init_data_auth(init_data)
        if not ADMIN_TG_ID or str(auth_data['id']) != ADMIN_TG_ID:
            raise HTTPException(status_code=403, detail="Доступ запрещен.")
    except Exception:
        raise HTTPException(status_code=403, detail="Доступ запрещен или неверные данные.")
        
    withdrawal_id = data.withdrawal_id
    action = data.action
    
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
    return JSONResponse(content={"status": "ok", "message": f"Заявка #{withdrawal_id} обновлена до {new_status}"})


# --- Основная точка входа для Railway ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
