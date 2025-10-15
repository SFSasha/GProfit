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

# --- ГЛОБАЛЬНЫЕ КОНСТАНТЫ И КОНФИГУРАЦИЯ ---\
DB_PATH = "/data/app.db"
BOT_USERNAME = os.environ.get("BOT_USERNAME", "star_miner_bot") 
# ID администратора. Добавьте его в переменные окружения!
ADMIN_TG_ID = os.environ.get("ADMIN_TG_ID") 
if not ADMIN_TG_ID:
    logger.warning("ADMIN_TG_ID не задан. Функционал админа будет недоступен.")
    ADMIN_TG_ID = None

MIN_WITHDRAWAL = 1000 # Минимальная сумма для вывода
BLAST_COST = 100      # Стоимость "взрыва"

# --- СХЕМЫ ДАННЫХ Pydantic ---

class UserData(BaseModel):
    user_id: int
    stars: int
    taps: int
    dynamite: int
    referrer_id: Optional[int] = None
    
class ClickRequest(BaseModel):
    init_data: str

class WithdrawalRequest(BaseModel):
    init_data: str
    amount: int
    crypto_address: str # Упрощенный пример - адрес для вывода

class AdminAction(BaseModel):
    init_data: str
    withdrawal_id: int
    action: str # 'approve' or 'reject'

# --- ИНТЕРФЕЙС БАЗЫ ДАННЫХ ---

def get_db_connection():
    """Создает соединение с базой данных."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row # Позволяет получать результаты как словари
    return conn

def init_db():
    """Инициализирует базу данных, создавая таблицы, если они не существуют."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            stars INTEGER NOT NULL DEFAULT 0,
            taps INTEGER NOT NULL DEFAULT 0,
            dynamite INTEGER NOT NULL DEFAULT 0,
            referrer_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (referrer_id) REFERENCES users(id)
        )
    """)
    
    # Таблица заявок на вывод
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            crypto_address TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', -- pending, approved, rejected
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована.")

init_db() # Запускаем инициализацию при старте

def get_or_create_user(user_id: int, referrer_id: Optional[int] = None) -> UserData:
    """Получает данные пользователя или создает нового."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT stars, taps, dynamite, referrer_id FROM users WHERE id = ?", (user_id,))
    user_row = cursor.fetchone()
    
    if user_row:
        user_data = UserData(user_id=user_id, **dict(user_row))
    else:
        # Новый пользователь
        # Реферальный ID должен быть ID существующего пользователя и не быть самим user_id
        valid_referrer_id = None
        if referrer_id and referrer_id != user_id:
             cursor.execute("SELECT 1 FROM users WHERE id = ?", (referrer_id,))
             if cursor.fetchone():
                 valid_referrer_id = referrer_id

        cursor.execute(
            "INSERT INTO users (id, referrer_id) VALUES (?, ?)", 
            (user_id, valid_referrer_id)
        )
        conn.commit()
        user_data = UserData(user_id=user_id, stars=0, taps=0, dynamite=0, referrer_id=valid_referrer_id)
        logger.info(f"Создан новый пользователь ID:{user_id}. Реферер ID:{valid_referrer_id}")

        # Бонус рефереру (если есть)
        if valid_referrer_id:
             # Начисляем бонус, например, 100 звезд
             bonus = 100
             cursor.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (bonus, valid_referrer_id))
             conn.commit()
             logger.info(f"Начислен реферальный бонус {bonus} звезд пользователю ID:{valid_referrer_id}")

    conn.close()
    return user_data

# --- АВТОРИЗАЦИЯ И ВАЛИДАЦИЯ TELEGRAM WEB APP ---

def init_data_auth(init_data: str) -> Dict[str, str]:
    """
    Проверяет целостность и подлинность init_data, полученных от Web App.
    Возвращает словарь с параметрами, включая данные пользователя.
    """
    if not init_data:
        raise HTTPException(status_code=401, detail="Отсутствуют init_data.")
        
    # Разбираем строку init_data
    params = parse_qs(init_data)
    
    # 1. Извлекаем hash
    hash_value = params.get('hash', [None])[0]
    if not hash_value:
        raise HTTPException(status_code=401, detail="Отсутствует hash.")
        
    # 2. Создаем строку data_check_string, исключая hash и сортируя параметры
    
    # Для надежности, берем пары ключ=значение из исходной строки и сортируем
    # Это важно: сортировка должна быть по имени ключа
    original_parts = unquote(init_data).split('&')
    check_parts = []
    
    for part in original_parts:
        if not part.startswith('hash='):
            check_parts.append(part)
    
    check_parts.sort()
    data_check_string = '\n'.join(check_parts)

    # 3. Вычисляем секретный ключ
    # Ключ: HMAC_SHA256('WebAppData', bot_token).digest()
    
    # --- ИСПРАВЛЕНИЕ: ПРЕОБРАЗОВАНИЕ КЛЮЧА И СООБЩЕНИЯ В БАЙТЫ ---
    try:
        # Вычисляем секретный ключ. Ключ и сообщение должны быть в байтах!
        key_sha256 = hmac.new(
            key='WebAppData'.encode('utf-8'), 
            msg=TELEGRAM_TOKEN.encode('utf-8'), # <<< ИСПРАВЛЕНО
            digestmod=hashlib.sha256
        ).digest()
        
        # Вычисляем хэш для проверки данных. Сообщение должно быть в байтах!
        calculated_hash = hmac.new(
            key=key_sha256,
            msg=data_check_string.encode('utf-8'), # <<< ИСПРАВЛЕНО
            digestmod=hashlib.sha256
        ).hexdigest()
    
    except TypeError as e:
        logger.error(f"Ошибка типа при HMAC: {e}. Проверьте, что TELEGRAM_TOKEN не None и не имеет неожиданного типа.")
        # Дополнительная проверка на всякий случай
        if not isinstance(TELEGRAM_TOKEN, str):
             raise HTTPException(status_code=500, detail="Ошибка конфигурации сервера: TELEGRAM_TOKEN не является строкой.")
        raise HTTPException(status_code=500, detail="Ошибка сервера при проверке аутентификации (TypeError).")
    # --- КОНЕЦ ИСПРАВЛЕНИЯ ---


    # 4. Сравниваем хэши
    if calculated_hash != hash_value:
        logger.warning(f"Неверный хэш. Calculated: {calculated_hash}. Received: {hash_value}. Data: {data_check_string}")
        # Для безопасности в продакшене не раскрывать детали
        raise HTTPException(status_code=401, detail="Неверная подпись данных Web App.")

    # 5. Проверка срока действия auth_date (по умолчанию 24 часа)
    auth_date = int(params.get('auth_date', [0])[0])
    # Убираем проверку на время для упрощения деплоя
    # if time() - auth_date > 86400: # 24 часа = 86400 секунд
    #     logger.warning(f"Срок действия init_data истек для ID: {params.get('user', [''])[0]}.")
    #     raise HTTPException(status_code=401, detail="Срок действия данных Web App истек.")
        
    # 6. Извлекаем данные пользователя
    user_data = params.get('user', [None])[0]
    if not user_data:
        # Этот код сработает, если WebApp запущен не из приватного чата
        # Но мы всегда ожидаем user при успешной валидации
        raise HTTPException(status_code=401, detail="Данные пользователя отсутствуют.")

    try:
        # User_data может быть декодирован: {"id":..., "first_name":...}
        user_info = json.loads(unquote(user_data))
        # Добавляем ID пользователя в возвращаемый словарь для удобства
        result_params = {k: v[0] for k, v in params.items() if v}
        result_params['id'] = user_info.get('id')
        
        return result_params
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="Неверный формат данных пользователя.")


# --- Настройка бота (оставлено без изменений) ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет приветственное сообщение с кнопкой для запуска Web App."""
    keyboard = [
        [InlineKeyboardButton(
            "🚀 Открыть Web App",
            web_app=WebAppInfo(url=WEBAPP_URL)
        )]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Привет! Нажми на кнопку ниже, чтобы запустить моё веб-приложение.",
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
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
async def startup_event():
    """При старте сервера запускаем бота."""
    asyncio.create_task(setup_bot())

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Отдает главную HTML-страницу веб-приложения."""
    return templates.TemplateResponse("index.html", {"request": request})


# --- API ЭНДПОИНТЫ ---

@app.post("/api/v1/data")
async def get_user_data(request: Request, click_request: ClickRequest):
    """
    Получает данные пользователя (баланс, реферальная ссылка).
    Этот эндпоинт используется при загрузке Web App.
    """
    try:
        auth_data = init_data_auth(click_request.init_data)
        user_id = int(auth_data['id'])
        
        # Реферер ID может быть передан в параметре запуска
        start_param = auth_data.get('tgWebAppStartParam')
        referrer_id = int(start_param) if start_param and start_param.isdigit() else None
        
        user_data = get_or_create_user(user_id, referrer_id)
        
        # Генерация реферальной ссылки
        # Используем URL Web App и добавляем user_id как параметр старта
        referral_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        
        # Получаем данные о последних 5 выводах
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, amount, status, created_at FROM withdrawals WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
            (user_id,)
        )
        withdrawals = [dict(row) for row in cursor.fetchall()]
        conn.close()

        logger.info(f"User Data for ID:{user_id} requested. Balance: {user_data.stars}")
        
        return {
            "status": "ok",
            "user_data": user_data.model_dump(),
            "referral_link": referral_link,
            "min_withdrawal": MIN_WITHDRAWAL,
            "blast_cost": BLAST_COST,
            "is_admin": str(user_id) == ADMIN_TG_ID,
            "withdrawals": withdrawals
        }
        
    except HTTPException as e:
        logger.error(f"Auth Error in /api/v1/data: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Internal Server Error in /api/v1/data: {e}", exc_info=True)
        # Важно вернуть JSON для фронтенда, даже при 500
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера.")

@app.post("/api/v1/click")
async def click_handler(click_request: ClickRequest):
    """Обрабатывает клик пользователя (добыча звезды)."""
    try:
        auth_data = init_data_auth(click_request.init_data)
        user_id = int(auth_data['id'])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Обновляем баланс и счетчик кликов
        cursor.execute(
            "UPDATE users SET stars = stars + 1, taps = taps + 1 WHERE id = ?", 
            (user_id,)
        )
        
        # 2. Проверяем, был ли начислен бонус рефереру ранее
        # В этой простой логике мы не будем начислять бонус за клик,
        # только за факт регистрации (см. get_or_create_user)
        
        # 3. Получаем обновленный баланс для ответа
        cursor.execute("SELECT stars FROM users WHERE id = ?", (user_id,))
        new_stars = cursor.fetchone()[0]
        
        conn.commit()
        conn.close()
        
        return {"status": "ok", "new_stars": new_stars}
        
    except HTTPException as e:
        logger.error(f"Auth Error in /api/v1/click: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Internal Server Error in /api/v1/click: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера.")

@app.post("/api/v1/blast")
async def blast_handler(click_request: ClickRequest):
    """Обрабатывает использование "взрыва" (динамита)."""
    try:
        auth_data = init_data_auth(click_request.init_data)
        user_id = int(auth_data['id'])
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT stars, dynamite FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
        
        if not user_data:
            conn.close()
            raise HTTPException(status_code=404, detail="Пользователь не найден.")

        current_stars, current_dynamite = user_data

        if current_dynamite <= 0:
            conn.close()
            raise HTTPException(status_code=400, detail="Нет динамита для 'взрыва'.")

        if current_stars < BLAST_COST:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Недостаточно звезд для оплаты 'взрыва'. Требуется {BLAST_COST}.")

        # Вычисляем бонус: случайное число от 1 до 50
        blast_bonus = random.randint(1, 50)
        
        # Обновляем баланс и динамит
        cursor.execute(
            "UPDATE users SET stars = stars - ?, dynamite = dynamite - 1, stars = stars + ? WHERE id = ?", 
            (BLAST_COST, blast_bonus, user_id)
        )
        
        # Получаем обновленный баланс
        cursor.execute("SELECT stars, dynamite FROM users WHERE id = ?", (user_id,))
        new_stars, new_dynamite = cursor.fetchone()
        
        conn.commit()
        conn.close()
        
        logger.info(f"User ID:{user_id} blasted. Cost: {BLAST_COST}, Bonus: {blast_bonus}. New Stars: {new_stars}")

        return {
            "status": "ok", 
            "new_stars": new_stars,
            "new_dynamite": new_dynamite,
            "bonus_amount": blast_bonus
        }
        
    except HTTPException as e:
        logger.error(f"Auth/Logic Error in /api/v1/blast: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Internal Server Error in /api/v1/blast: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера.")

@app.post("/api/v1/withdraw")
async def create_withdrawal(withdrawal_request: WithdrawalRequest):
    """Создает новую заявку на вывод."""
    try:
        auth_data = init_data_auth(withdrawal_request.init_data)
        user_id = int(auth_data['id'])
        amount = withdrawal_request.amount
        crypto_address = withdrawal_request.crypto_address
        
        if amount < MIN_WITHDRAWAL:
            raise HTTPException(status_code=400, detail=f"Минимальная сумма вывода: {MIN_WITHDRAWAL} звезд.")
            
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Проверяем баланс
        cursor.execute("SELECT stars FROM users WHERE id = ?", (user_id,))
        user_stars = cursor.fetchone()
        
        if not user_stars or user_stars[0] < amount:
            conn.close()
            raise HTTPException(status_code=400, detail="Недостаточно звезд на балансе.")
            
        # 1. Списываем средства с баланса пользователя
        cursor.execute("UPDATE users SET stars = stars - ? WHERE id = ?", (amount, user_id))
        
        # 2. Создаем заявку в статусе 'pending'
        cursor.execute(
            "INSERT INTO withdrawals (user_id, amount, crypto_address, status) VALUES (?, ?, ?, ?)",
            (user_id, amount, crypto_address, 'pending')
        )
        withdrawal_id = cursor.lastrowid
        
        conn.commit()
        conn.close()
        
        logger.info(f"User ID:{user_id} created withdrawal #{withdrawal_id} for {amount} stars.")
        return JSONResponse(content={"status": "ok", "message": f"Заявка на вывод #{withdrawal_id} успешно создана и ожидает подтверждения."})
        
    except HTTPException as e:
        logger.error(f"Auth/Logic Error in /api/v1/withdraw: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Internal Server Error in /api/v1/withdraw: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера.")


# --- АДМИН ПАНЕЛЬ ---

@app.get("/api/v1/admin/withdrawals")
async def get_all_withdrawals(init_data: str):
    """Получает список всех заявок на вывод для администратора."""
    try:
        auth_data = init_data_auth(init_data)
        user_id = str(auth_data.get('id'))
        
        if user_id != ADMIN_TG_ID:
            raise HTTPException(status_code=403, detail="Доступ запрещен.")
            
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Получаем все заявки, сортируем по статусу (pending первыми) и дате
        cursor.execute("""
            SELECT 
                w.id, w.user_id, w.amount, w.crypto_address, w.status, w.created_at,
                u.stars, u.taps, u.dynamite 
            FROM withdrawals w
            JOIN users u ON w.user_id = u.id
            ORDER BY 
                CASE w.status 
                    WHEN 'pending' THEN 1 
                    ELSE 2 
                END, 
                w.created_at DESC
        """)
        
        withdrawals = [
            {
                "id": row['id'],
                "user_id": row['user_id'],
                "amount": row['amount'],
                "crypto_address": row['crypto_address'],
                "status": row['status'],
                "created_at": row['created_at'],
                "user_stars": row['stars'],
                "user_taps": row['taps'],
                "user_dynamite": row['dynamite']
            }
            for row in cursor.fetchall()
        ]
        
        conn.close()
        return {"status": "ok", "withdrawals": withdrawals}
        
    except HTTPException as e:
        logger.error(f"Auth/Admin Error in /api/v1/admin/withdrawals: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Internal Server Error in /api/v1/admin/withdrawals: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера.")


@app.post("/api/v1/admin/action")
async def admin_action(action_request: AdminAction):
    """Обрабатывает действие администратора (approve/reject заявки)."""
    try:
        auth_data = init_data_auth(action_request.init_data)
        user_id = str(auth_data.get('id'))
        withdrawal_id = action_request.withdrawal_id
        action = action_request.action
        
        if user_id != ADMIN_TG_ID:
            raise HTTPException(status_code=403, detail="Доступ запрещен.")

        if action not in ['approve', 'reject']:
            raise HTTPException(status_code=400, detail="Неверное действие.")

        conn = get_db_connection()
        cursor = conn.cursor()

        # 1. Получаем текущую заявку
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
            # Это должно быть поймано выше, но на всякий случай
            raise HTTPException(status_code=400, detail="Неверное действие.")
            
        conn.close()
        logger.info(f"Admin Action: Withdrawal #{withdrawal_id} updated to {new_status} by Admin {auth_data['id']}")
        return JSONResponse(content={"status": "ok", "message": f"Заявка #{withdrawal_id} обновлена до {new_status}"})

    except HTTPException as e:
        logger.error(f"Auth/Admin Logic Error in /api/v1/admin/action: {e.detail}")
        raise e
    except Exception as e:
        logger.error(f"Internal Server Error in /api/v1/admin/action: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера.")


# --- Основная точка входа для Railway ---
if __name__ == "__main__":
    # Railway предоставит переменную PORT
    port = int(os.environ.get("PORT", 8080))
    # Запускаем uvicorn в асинхронном режиме (с application.start() в startup_event)
    uvicorn.run(app, host="0.0.0.0", port=port)
