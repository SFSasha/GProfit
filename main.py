import os
import logging
import asyncio
import sqlite3
import hmac
import hashlib
import json # <-- ВАЖНО: Добавлен import json, который мог отсутствовать
import random 
from time import time
from typing import Optional, Dict, List
from urllib.parse import parse_qs, unquote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates 
from pydantic import BaseModel
import uvicorn

# Потенциально проблемные импорты для чистого запуска FastAPI, 
# которые нужны только для логики бота.
# Мы оставляем их, но убедимся, что они используются только в блоке main.
try:
    from telegram import Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, ContextTypes
    TELEGRAM_BOT_AVAILABLE = True
except ImportError:
    # Это позволит FastAPI запуститься, даже если библиотеки telegram нет (но бот не будет работать)
    TELEGRAM_BOT_AVAILABLE = False
    class EmptyClass:
        pass
    Update, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup = (EmptyClass,) * 4
    Application, CommandHandler, ContextTypes = (EmptyClass,) * 3


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
# Используйте os.getenv для более безопасного получения
BOT_USERNAME = os.environ.get("BOT_USERNAME", "star_miner_bot") 
ADMIN_TG_ID = os.environ.get("ADMIN_TG_ID") 

# Новые константы для логики
PRIZE_AMOUNTS = [0.1, 0.3, 0.5, 1.0, 3.0, 5.0] 
REFERRAL_PERCENT = 0.10 
MIN_WITHDRAWAL_AMOUNT = 50.0 

# Проверка переменных
if not TELEGRAM_TOKEN:
    logger.error("Не найден TELEGRAM_TOKEN в переменных окружения! Auth не будет работать.")
if not WEBAPP_URL:
    logger.error("Не найден WEBAPP_URL в переменных окружения!")
if not ADMIN_TG_ID:
    logger.warning("ADMIN_TG_ID не установлен. Доступ к админ-панели будет отключен.")


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
                status TEXT DEFAULT 'pending', 
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        # При такой критической ошибке можно остановить приложение
        # raise

# Вызов инициализации БД при запуске
initialize_db()

# --- Логика аутентификации Telegram Web App ---
def init_data_auth(init_data: str) -> Dict[str, any]:
    if not init_data:
        raise HTTPException(status_code=401, detail="Auth failed: No init_data provided.")
    if not TELEGRAM_TOKEN:
         raise HTTPException(status_code=500, detail="Internal Auth Error: TELEGRAM_TOKEN is not set.")

    try:
        # Ваш токен бота используется для создания HMAC-ключа
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
    
    if calculated_hash != received_hash:
        logger.error(f"Auth failed: Hash mismatch! Calculated: {calculated_hash}, Received: {received_hash}")
        raise HTTPException(status_code=401, detail="Auth failed: Hash mismatch.")

    user_data = query_params.get('user', query_params.get('receiver', [None]))[0]
    if not user_data:
        # Если нет 'user' (обычно в init_data есть)
        raise HTTPException(status_code=401, detail="Auth failed: User data not found.")
        
    auth_data = json.loads(user_data)
    
    return auth_data


# --- ЛОГИКА БД (ПОЛЬЗОВАТЕЛЬ) ---
# (Остальные функции БД остаются без изменений, кроме того, что мы используем
# BOT_USERNAME, который должен быть передан в index.html)

def get_or_create_user(user_id: int, username: str, start_parameter: Optional[str] = None):
    # ... (логика создания пользователя с 2 звездами и реферером) ...
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Поиск пользователя
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        # 2. Создание нового пользователя
        referrer_id = None
        initial_stars = 0.0 
        
        # Проверка на реферера
        if start_parameter and start_parameter.isdigit() and int(start_parameter) != user_id:
            potential_referrer_id = int(start_parameter)
            cursor.execute("SELECT id FROM users WHERE id = ?", (potential_referrer_id,))
            if cursor.fetchone():
                referrer_id = potential_referrer_id
                # Новичок получает 2 звезды за регистрацию по ссылке
                initial_stars = 2.0 
                
        # Вставка нового пользователя
        cursor.execute("""
            INSERT INTO users (id, username, stars, dynamite, referrer_id)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, username, initial_stars, 3, referrer_id))
        conn.commit()
        
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        logger.info(f"New user created: {username} ({user_id}). Referrer: {referrer_id}. Initial stars: {initial_stars}")
        conn.close()
        return dict(user)
    
    conn.close()
    return dict(user)

def get_user_by_id(user_id: int) -> Optional[Dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None

def get_referral_stats(user_id: int) -> Dict[str, any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
    friends_count = cursor.fetchone()[0]
    conn.close()
    return {
        "friends_count": friends_count,
        "referral_earnings": 0.0 
    }

def is_admin_user(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return str(user_id) == ADMIN_TG_ID

# --- API FastAPI ---

app = FastAPI()
templates = Jinja2Templates(directory=".") 

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Отдача HTML-страницы приложения."""
    start_param = request.query_params.get("tgWebAppStartParam")
    # Передаем BOT_USERNAME для корректного формирования реферальной ссылки на фронтенде
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "start_param": start_param,
        "BOT_USERNAME": BOT_USERNAME # <-- Передача имени бота
    })

@app.post("/api/v1/data")
async def get_user_data(data: RequestData):
    """Получение всех данных пользователя и реферальной информации."""
    # 1. Аутентификация
    try:
        auth_data = init_data_auth(data.init_data)
    except HTTPException as e:
        logger.error(f"Auth failed for data endpoint: {e.detail}")
        raise e
        
    user_id = auth_data['id']
    username = auth_data.get('username', 'noname')

    # 2. Получение данных пользователя (создаем, если не существует)
    # В этом месте нет start_parameter, поэтому реферал сработает только в /start
    user_data = get_or_create_user(user_id, username)
        
    # 3. Реферальная статистика
    referral_stats = get_referral_stats(user_id)
    
    # 4. Проверка на админа
    is_admin = is_admin_user(user_id)
    
    return JSONResponse(content={
        "user": user_data,
        "referral_stats": referral_stats,
        "is_admin": is_admin
    })

@app.post("/api/v1/blast", response_model=BlastResponse)
async def blast_mine(data: RequestData):
    """Обработка взрыва."""
    # 1. Аутентификация
    try:
        auth_data = init_data_auth(data.init_data)
    except HTTPException as e:
        raise e
        
    user_id = auth_data['id']
    user = get_user_by_id(user_id)

    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    if user['dynamite'] <= 0:
        raise HTTPException(status_code=400, detail="Недостаточно Динамита.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 1. Выбираем случайный приз
        prize_amount = random.choice(PRIZE_AMOUNTS) 
        
        # 2. Обновляем баланс пользователя
        cursor.execute(
            "UPDATE users SET stars = stars + ?, dynamite = dynamite - 1, last_blast = ? WHERE id = ?",
            (prize_amount, int(time()), user_id)
        )
        
        # 3. ЛОГИКА РЕФЕРАЛЬНОГО БОНУСА (10%)
        referrer_id = user['referrer_id']
        referral_bonus = 0.0
        if referrer_id:
            referral_bonus = round(prize_amount * REFERRAL_PERCENT, 2) 
            cursor.execute(
                "UPDATE users SET stars = stars + ? WHERE id = ?",
                (referral_bonus, referrer_id)
            )
            
        conn.commit()
        
        # 4. Получаем обновленные данные
        cursor.execute("SELECT stars, dynamite FROM users WHERE id = ?", (user_id,))
        updated_user = cursor.fetchone()
        
        new_stars = updated_user['stars']
        new_dynamite = updated_user['dynamite']

        logger.info(f"User {user_id} blasted: Won {prize_amount} stars. Ref bonus: {referral_bonus}")
        
        return BlastResponse(
            prize_amount=prize_amount, 
            new_stars=new_stars, 
            new_dynamite=new_dynamite
        )
        
    except Exception as e:
        logger.error(f"Error during blast for user {user_id}: {e}")
        conn.rollback()
        raise HTTPException(status_code=500, detail="Internal server error during blast.")
    finally:
        conn.close()


@app.post("/api/v1/withdraw")
async def request_withdraw(data: WithdrawRequest):
    """Создание заявки на вывод."""
    # 1. Аутентификация
    try:
        auth_data = init_data_auth(data.init_data)
    except HTTPException as e:
        raise e

    user_id = auth_data['id']
    username = auth_data.get('username') 
    amount = data.amount

    if amount < MIN_WITHDRAWAL_AMOUNT: 
        raise HTTPException(status_code=400, detail=f"Минимальная сумма вывода: {MIN_WITHDRAWAL_AMOUNT} Звезд.")

    user = get_user_by_id(user_id)
    if not user or user['stars'] < amount:
        raise HTTPException(status_code=400, detail="Недостаточно Звезд на балансе.")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Списание средств
        cursor.execute("UPDATE users SET stars = stars - ? WHERE id = ?", (amount, user_id))
        
        # Запись заявки с Telegram username пользователя
        cursor.execute("""
            INSERT INTO withdrawals (user_id, username, amount, status)
            VALUES (?, ?, ?, ?)
        """, (user_id, username, amount, 'pending'))
        
        conn.commit()
        logger.info(f"Withdrawal request created: User {username} ({user_id}), Amount {amount}")
        
        return JSONResponse(content={"status": "ok", "message": "Заявка на вывод успешно создана."})
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Error during withdraw for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during withdrawal.")
    finally:
        conn.close()

# --- АДМИН ПАНЕЛЬ API ---

@app.post("/api/v1/admin/withdrawals")
async def get_admin_withdrawals(data: RequestData):
    """Получение всех ожидающих заявок на вывод."""
    # 1. Аутентификация и проверка админа
    try:
        auth_data = init_data_auth(data.init_data)
        user_id = auth_data['id']
        if not is_admin_user(user_id):
            raise HTTPException(status_code=403, detail="Доступ запрещен. Только для администраторов.")
    except HTTPException as e:
        raise e
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, username, amount, created_at FROM withdrawals WHERE status = 'pending' ORDER BY created_at ASC")
    withdrawals = cursor.fetchall()
    
    conn.close()
    
    result = [dict(row) for row in withdrawals]
    
    logger.info(f"Admin {user_id} fetched {len(result)} pending withdrawals.")
    return JSONResponse(content={"withdrawals": result})

@app.post("/api/v1/admin/action")
async def admin_withdrawal_action(action_data: AdminAction):
    """Одобрение или отклонение заявки на вывод."""
    # 1. Аутентификация и проверка админа
    try:
        auth_data = init_data_auth(action_data.init_data)
        user_id = auth_data['id']
        if not is_admin_user(user_id):
            raise HTTPException(status_code=403, detail="Доступ запрещен. Только для администраторов.")
    except HTTPException as e:
        raise e
        
    withdrawal_id = action_data.withdrawal_id
    action = action_data.action
    
    if action not in ['approve', 'reject']:
        raise HTTPException(status_code=400, detail="Неверное действие. Доступно: 'approve' или 'reject'.")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # 2. Проверка заявки
        cursor.execute("SELECT user_id, amount, status FROM withdrawals WHERE id = ?", (withdrawal_id,))
        withdrawal = cursor.fetchone()
        
        if not withdrawal:
            raise HTTPException(status_code=404, detail="Заявка не найдена.")

        user_id_target, amount, current_status = withdrawal
        
        if current_status != 'pending':
            raise HTTPException(status_code=400, detail=f"Заявка уже имеет статус: {current_status}")

        if action == 'approve':
            new_status = 'approved'
            cursor.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (new_status, withdrawal_id))
            conn.commit()
            
        elif action == 'reject':
            new_status = 'rejected'
            # Возвращаем средства на баланс пользователя
            cursor.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (amount, user_id_target))
            cursor.execute("UPDATE withdrawals SET status = ? WHERE id = ?", (new_status, withdrawal_id))
            conn.commit()
            
        logger.info(f"Admin Action: Withdrawal #{withdrawal_id} updated to {new_status} by Admin {user_id}")
        
        return JSONResponse(content={"status": "ok", "message": f"Заявка #{withdrawal_id} обновлена до {new_status}"})
        
    except Exception as e:
        conn.rollback()
        logger.error(f"Admin action failed for withdrawal {withdrawal_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка при обработке действия: {e}")
    finally:
        conn.close()


# --- Основная точка входа для Railway ---
if __name__ == "__main__":
    # Логика запуска бота
    if TELEGRAM_BOT_AVAILABLE:
        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            user_id = update.effective_user.id
            username = update.effective_user.username or ""
            
            start_payload = context.args[0] if context.args else None
            
            # Создаем или получаем пользователя
            get_or_create_user(user_id, username, start_payload)

            # Кнопка для запуска Web App
            keyboard = [
                [InlineKeyboardButton("🎮 Запустить Star Miner", web_app=WebAppInfo(url=f"{WEBAPP_URL}?tgWebAppStartParam={start_payload or user_id}"))]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await update.message.reply_text(
                'Добро пожаловать в Star Miner! Жми кнопку, чтобы начать добычу.', 
                reply_markup=reply_markup
            )

        application = Application.builder().token(TELEGRAM_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        
        # Запуск FastAPI в отдельном потоке
        loop = asyncio.get_event_loop()
        config = uvicorn.Config(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), loop=loop)
        server = uvicorn.Server(config)
        
        # Запуск обоих приложений
        try:
            loop.run_until_complete(asyncio.gather(
                application.run_polling(),
                server.serve()
            ))
        except Exception as e:
            logger.error(f"Error running bot and server concurrently: {e}")
            # Если бот не может запуститься, попробуем запустить только сервер uvicorn
            loop.run_until_complete(server.serve())
            
    else:
        # Если библиотеки telegram нет, запускаем только FastAPI
        logger.warning("Telegram Bot API library not found. Running Uvicorn server only.")
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))
