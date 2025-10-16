import sqlite3
import os
import re
import asyncio
import logging
import httpx # <-- НОВЫЙ ИМПОРТ ДЛЯ АСИНХРОННЫХ ЗАПРОСОВ
from typing import List, Optional, Dict
from datetime import datetime, date, timedelta
from aiogram import Bot, Dispatcher, Router, types, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.filters.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest # Импортируем для обработки ошибок

# -----------------------------------------------------------
# --------------------- 1. КОНФИГУРАЦИЯ ---------------------
# -----------------------------------------------------------

# !!! ОБЯЗАТЕЛЬНО ЗАМЕНИТЕ ЭТИ ЗНАЧЕНИЯ НА ВАШИ !!!
BOT_TOKEN = "8417661454:AAFxQA5ASaCYyknxt_zJBLpK2I9yP6bti-c" 
ADMIN_ID = 1500618394  # Ваш Telegram ID
# -----------------------------------------------------------

# --- КОНСТАНТЫ ЛОГИКИ ЗАКАЗОВ ---
USER_ORDER_COST_STARS = 2.0 # Цена для покупателя (2 звезды за 1 подписчика)
USER_TASK_REWARD_STARS = 1.0 # Награда для исполнителя (1 звезда за 1 подписку)

# --- КОНСТАНТЫ FLYER API (ДОБАВЛЕНО) ---
FLYER_API_KEY = "FL-kQDJlw-CUUelI-KCQwTc-pajfkp" # <--- ОБЯЗАТЕЛЬНО ЗАМЕНИТЬ!
FLYER_API_ENDPOINT = "https://api.flyerservice.io"
FLYER_TASK_REWARD = 1.0 # Награда за задание Flyer
# -----------------------------------------------------------

# --- ПУТЬ К БАЗЕ ---
DB_PATH = os.getenv("DB_PATH", "bot.db") 
os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)

# --- ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ DB ---
_conn = None
_initialized = False
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
router = Router()

# -----------------------------------------------------------
# ------------------ 2. ФУНКЦИИ БАЗЫ ДАННЫХ ------------------
# -----------------------------------------------------------

# ... (Все функции БД (get_conn, init_db, add_user, get_user, update_stars,
#      add_user_order, get_user_orders, get_order_details, 
#      increment_order_completion, get_next_order_task, add_user_task_done)
#      остаются без изменений)
#      Я их не повторяю, чтобы не делать код слишком длинным.
#      В вашем случае они должны быть скопированы сюда целиком.

def get_conn():
    """Получает или создает соединение с базой данных."""
    global _conn, _initialized
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30) 
        _conn.row_factory = sqlite3.Row
    if not _initialized:
        init_db(_conn)
        _initialized = True
    return _conn

def init_db(conn):
    """Инициализирует таблицы базы данных."""
    cur = conn.cursor()

    # 1. USERS (Пользователи)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        stars REAL DEFAULT 0.0,
        referrer_id INTEGER DEFAULT NULL,
        registration_date TEXT DEFAULT (DATETIME('now'))
    )
    """)

    # 2. TASKS (Задания/Заказы)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks ( 
        id INTEGER PRIMARY KEY,
        channel TEXT,
        stars REAL,
        max_completions INTEGER,
        current_completions INTEGER DEFAULT 0,
        type TEXT,
        creator_id INTEGER
    )
    """)
    
    # 3. USER_TASKS_DONE (Кто какое задание выполнил)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_tasks_done (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        task_id INTEGER,
        created_at TEXT DEFAULT (DATETIME('now')),
        UNIQUE(user_id, task_id)
    )
    """)

    conn.commit()
    logging.info("База данных инициализирована.")

# --- CRUD для Пользователей и Звезд ---

def add_user(user_id: int, referrer_id: Optional[int] = None):
    """Добавляет пользователя в БД."""
    conn = get_conn()
    cur = conn.cursor()
    
    if referrer_id is not None and referrer_id == user_id:
        referrer_id = None
        
    try:
        cur.execute(
            "INSERT OR IGNORE INTO users (id, referrer_id) VALUES (?, ?)", 
            (user_id, referrer_id)
        )
        conn.commit()
    except Exception as e:
        logging.error(f"Error adding user {user_id}: {e}")

def get_user(user_id: int) -> Optional[Dict]:
    """Получает данные пользователя."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None
    
def update_stars(user_id: int, delta: float, reason: str):
    """Обновляет баланс звезд пользователя."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (delta, user_id))
    conn.commit()

# --- CRUD для Заказов ---

def add_user_order(user_id: int, channel: str, max_subs: int) -> Optional[int]:
    """Создает новый заказ на подписку."""
    conn = get_conn()
    cur = conn.cursor()
    
    try:
        cur.execute(
            "INSERT INTO tasks (channel, stars, max_completions, current_completions, type, creator_id) VALUES (?, ?, ?, 0, 'user_channel', ?)",
            (channel, USER_TASK_REWARD_STARS, max_subs, user_id)
        )
        conn.commit()
        return cur.lastrowid
    except Exception as e:
        logging.error(f"Error adding user order: {e}")
        return None

def get_user_orders(user_id: int) -> List[Dict]:
    """Возвращает все заказы, созданные пользователем."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE creator_id = ? ORDER BY id DESC", (user_id,))
    return [dict(row) for row in cur.fetchall()]

def get_order_details(task_id: int) -> Optional[Dict]:
    """Возвращает детали конкретного заказа/задания."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    return dict(row) if row else None

def increment_order_completion(task_id: int) -> bool:
    """Увеличивает счетчик выполненных подписок."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE tasks SET current_completions = current_completions + 1 WHERE id = ? AND current_completions < max_completions", 
            (task_id,)
        )
        conn.commit()
        return cur.rowcount > 0 
    except Exception as e:
        logging.error(f"Error incrementing order completion: {e}")
        return False
        
def get_next_order_task(user_id: int) -> Optional[Dict]:
    """Возвращает следующее доступное задание для выполнения."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT t.*
        FROM tasks t
        LEFT JOIN user_tasks_done utd ON t.id = utd.task_id AND utd.user_id = ?
        WHERE t.creator_id != ? 
          AND t.type = 'user_channel'
          AND t.current_completions < t.max_completions
          AND utd.task_id IS NULL 
        ORDER BY RANDOM()
        LIMIT 1
    """, (user_id, user_id))
    row = cur.fetchone()
    return dict(row) if row else None
    
def add_user_task_done(user_id: int, task_id: int):
    """Отмечает, что пользователь выполнил задание."""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT OR IGNORE INTO user_tasks_done (user_id, task_id) VALUES (?, ?)", (user_id, task_id))
        conn.commit()
    except Exception as e:
        logging.error(f"Error adding user task done: {e}")


# -----------------------------------------------------------
# --------------------- 3. ЛОГИКА БОТА ----------------------
# -----------------------------------------------------------

# --- FSM STATES ---
class OrderState(StatesGroup):
    WAITING_FOR_CHANNEL_USERNAME = State()
    WAITING_FOR_TARGET_SUBS = State()

# --- KEYBOARDS ---

main_menu_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="👤 Мой Профиль 👤", callback_data="profile"),
    ],
    [
        InlineKeyboardButton(text="✨ Купить подписчиков", callback_data="buy_subs_start"), # <-- ИСПРАВЛЕНИЕ ОПЕЧАТКИ
        InlineKeyboardButton(text="💎 Заработать", callback_data="earn_task_menu"),
    ],
    [
        InlineKeyboardButton(text="Ваши заказы", callback_data="my_orders"),
    ]
])

def get_back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]])

# --- HELPER FUNCTIONS ---

async def show_main_menu(message_or_callback: types.Message | types.CallbackQuery, state: FSMContext, bot: Bot):
    """Отображает главное меню и сбрасывает FSM."""
    await state.clear()
    user_id = message_or_callback.from_user.id
    user_db = get_user(user_id)
    stars = user_db.get('stars', 0) if user_db else 0

    msg = (
        f"💰 Ваш баланс: **{stars:.1f} ⭐️**\n\n"
        f"📈 **{USER_ORDER_COST_STARS:.1f} ⭐️**/подписчик (Покупка). **{USER_TASK_REWARD_STARS:.1f} ⭐️**/подписка (Заработок)."
    )
    
    if isinstance(message_or_callback, types.CallbackQuery):
        await message_or_callback.message.edit_text(
            msg,
            parse_mode="Markdown",
            reply_markup=main_menu_kb
        )
        await message_or_callback.answer()
    else:
         await message_or_callback.answer(
            msg,
            parse_mode="Markdown",
            reply_markup=main_menu_kb
        )

# --- НОВЫЕ АСИНХРОННЫЕ ФУНКЦИИ ДЛЯ FLYER API ---

async def get_flyer_tasks(user_id: int) -> Optional[Dict]:
    """Получает одну задачу от Flyer API с логированием."""
    logging.info(f"[Flyer] Получение задачи для пользователя {user_id}")
    
    if FLYER_API_KEY == "FL-kQDJlw-CUUelI-KCQwTc-pajfkp":
        logging.warning("[Flyer] API Key не настроен. Пропуск запроса.")
        return None
        
    async with httpx.AsyncClient(base_url=FLYER_API_ENDPOINT, timeout=10) as client:
        try:
            response = await client.post(
                "/get_tasks",
                json={
                    "key": FLYER_API_KEY,
                    "user_id": user_id,
                    "limit": 1
                }
            )
            logging.info(f"[Flyer] Ответ от API получен: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            
            if data.get('error'):
                logging.error(f"[Flyer] API Error (get_tasks): {data['error']}")
                return None
            
            if data.get('result') and isinstance(data['result'], list) and data['result']:
                logging.info(f"[Flyer] Задача найдена: {data['result'][0].get('signature')}")
                return data['result'][0]
                
        except httpx.HTTPStatusError as e:
            logging.error(f"[Flyer] HTTP Error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            logging.error(f"[Flyer] Request Error: {e}")
        except Exception as e:
            logging.error(f"[Flyer] Unknown Error: {e}")
            
    logging.info(f"[Flyer] Задача не найдена для пользователя {user_id}")
    return None


async def check_flyer_task(user_id: int, signature: str) -> Dict:
    """Проверяет выполнение задачи Flyer с логированием."""
    logging.info(f"[Flyer] Проверка задания {signature} для пользователя {user_id}")
    
    if FLYER_API_KEY == "FL-kQDJlw-CUUelI-KCQwTc-pajfkp":
        logging.warning("[Flyer] API Key не настроен.")
        return {"success": False, "result": "key_error"}
        
    async with httpx.AsyncClient(base_url=FLYER_API_ENDPOINT, timeout=10) as client:
        try:
            response = await client.post(
                "/check_task",
                json={
                    "key": FLYER_API_KEY,
                    "signature": signature
                }
            )
            logging.info(f"[Flyer] Ответ от check_task: {response.status_code}")
            response.raise_for_status()
            data = response.json()
            
            if data.get('error'):
                logging.error(f"[Flyer] API Error (check_task): {data['error']}")
                return {"success": False, "result": "api_error", "error": data['error']}

            logging.info(f"[Flyer] Результат проверки задания {signature}: {data.get('result')}")
            return {"success": data.get('result') == "success", "result": data.get('result', 'failed')}
            
        except httpx.HTTPStatusError as e:
            logging.error(f"[Flyer] HTTP Error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            logging.error(f"[Flyer] Request Error: {e}")
        except Exception as e:
            logging.error(f"[Flyer] Unknown Error: {e}")
            
    return {"success": False, "result": "internal_error"}

# --- ФУНКЦИЯ-ОБЕРТКА FLYER (ОБНОВЛЕНО) ---

async def flyer_check_wrapper(user: types.User, message: types.Message, action: str = "subscribe") -> Dict:
    """
    Получает задачу Flyer, если она есть, и отображает её. 
    ИСПРАВЛЕНА ошибка KeyError: 'url' путем проверки полей 'url' и 'link'.
    Возвращает {'skip': True} если задач нет или произошла ошибка.
    """
    user_id = user.id
    logging.info(f"[FlyerWrapper] Начало обработки задачи Flyer для пользователя {user_id}")

    # Если ключ не настроен, пропускаем
    if FLYER_API_KEY == "FL-kQDJlw-CUUelI-KCQwTc-pajfkp":
        logging.warning(f"[FlyerWrapper] Flyer API Key не настроен. Пропуск запроса для пользователя {user_id}")
        return {"skip": True} 
        
    # Пытаемся получить задачу от Flyer
    logging.info(f"[FlyerWrapper] Получение задачи Flyer для пользователя {user_id}")
    task_data = await get_flyer_tasks(user_id)
    
    if task_data:
        logging.info(f"[FlyerWrapper] Получена задача Flyer: {task_data}")
        reward = FLYER_TASK_REWARD  # 1 звезда за задачу Flyer
        task_signature = task_data['signature']
        
        # --- БЕЗОПАСНОЕ ПОЛУЧЕНИЕ ССЫЛКИ ---
        task_url = task_data.get('url') or task_data.get('link')
        if not task_url:
            logging.error(f"[FlyerWrapper] Flyer API task {task_signature} пропущена. Нет 'url' и 'link'.")
            await message.edit_text(
                "❌ **Ошибка задания Flyer**. Не удалось получить ссылку на канал. Попробуйте снова.",
                parse_mode="Markdown",
                reply_markup=get_back_to_menu_keyboard()
            )
            return {"skip": True} 

        # Подготовка кнопок
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🚀 Перейти и Выполнить", url=task_url)], 
            [InlineKeyboardButton(text=f"✅ Проверить ({reward:.1f} ⭐️)", callback_data=f"check_flyer_{task_signature}")],
            [InlineKeyboardButton(text="🔁 Пропустить/След. задание", callback_data="earn_task_menu")] 
        ])
        
        logging.info(f"[FlyerWrapper] Отображение задания Flyer пользователю {user_id}, ссылка: {task_url}")
        await message.edit_text(
            "💎 **СРОЧНОЕ ЗАДАНИЕ (Flyer)**\n\n"
            f"Вам доступно задание от системы **Flyer/Subgram**.\n"
            f"**Награда**: **{reward:.1f} ⭐️**",
            parse_mode="Markdown",
            reply_markup=kb
        )
        logging.info(f"[FlyerWrapper] Задача Flyer успешно показана пользователю {user_id}")
        return {"skip": False}  # Не пропускаем, задание показано
    
    logging.info(f"[FlyerWrapper] Для пользователя {user_id} задач Flyer нет. Пропуск.")
    return {"skip": True}  # Пропускаем, задач Flyer нет



# ----------------------------- CORE HANDLERS --------------------------

# ... (command_start_handler, back_to_menu_handler, grant_stars_handler, 
#      profile_handler без изменений) ...

@router.message(CommandStart())
async def command_start_handler(
    message: types.Message, 
    state: FSMContext, 
    bot: Bot, 
    command: Optional[CommandObject] = None 
):
    user_id = message.from_user.id
    referrer_id = None
    
    # Обработка реферального аргумента
    if command and command.args:
        try:
            referrer_id = int(command.args)
        except ValueError:
            logging.warning(f"Invalid referrer ID format: {command.args}")
            referrer_id = None
            
    # Добавление/проверка пользователя в БД
    add_user(user_id, referrer_id) 
    
    await show_main_menu(message, state, bot)

@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: types.CallbackQuery, state: FSMContext, bot: Bot):
    await show_main_menu(callback, state, bot)

# --- БЛОК: КОМАНДА АДМИНА ДЛЯ ВЫДАЧИ ЗВЕЗД ---

@router.message(F.text.startswith('/grant_stars'))
async def grant_stars_handler(message: types.Message):
    user_id = message.from_user.id
    
    # 1. Проверка на администратора
    if user_id != ADMIN_ID:
        await message.answer("❌ **Доступ запрещен.** Это команда только для Администратора.")
        return

    # 2. Парсинг аргументов: /grant_stars <user_id> <amount>
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("❌ **Неверный формат команды.** Используйте: `/grant_stars <user_id> <сумма>`")
        return

    try:
        target_user_id = int(parts[1])
        amount = float(parts[2])
    except ValueError:
        await message.answer("❌ **Неверный формат ID пользователя или суммы.** ID должен быть целым числом, сумма — числом.")
        return

    if amount <= 0:
         await message.answer("❌ **Сумма должна быть больше нуля.**")
         return

    # 3. Проверка существования пользователя и получение текущего баланса
    user_db = get_user(target_user_id)
    if not user_db:
        await message.answer(f"❌ **Пользователь с ID `{target_user_id}` не найден в базе данных.**")
        return

    current_stars = user_db.get('stars', 0)

    # 4. Выдача звезд
    update_stars(target_user_id, amount, reason="admin_grant")
    
    # 5. Уведомление администратора
    await message.answer(
        f"✅ **Успех!**\n"
        f"Пользователю `{target_user_id}` начислено **{amount:.1f} ⭐️**.\n"
        f"Новый баланс: **{(current_stars + amount):.1f} ⭐️**",
        parse_mode="Markdown"
    )
    
    # 6. Попытка уведомить пользователя
    try:
        await message.bot.send_message(
            target_user_id,
            f"🎁 **Администратор начислил вам {amount:.1f} ⭐️**.\n"
            f"Текущий баланс: **{(current_stars + amount):.1f} ⭐️**",
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.warning(f"Could not notify user {target_user_id} about star grant: {e}")


# --- ОБНОВЛЕННЫЙ profile_handler ---

@router.callback_query(F.data == "profile")
async def profile_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_db = get_user(user_id)
    stars = user_db.get('stars', 0) if user_db else 0
    
    bot_info = await callback.bot.get_me() 

    msg = (
        f"👤 **МОЙ ПРОФИЛЬ**\n\n"
        f"🆔 **Ваш ID**: `{user_id}`\n"
        f"💰 **Баланс**: **{stars:.1f} ⭐️**\n"
        f"🔗 **Ваша реферальная ссылка**: `t.me/{bot_info.username}?start={user_id}`"
    )

    # Добавляем блок админа, если это администратор
    if user_id == ADMIN_ID:
         admin_info = (
             "\n\n--- 🛡️ **ПАНЕЛЬ АДМИНИСТРАТОРА** 🛡️ ---\n"
             "**Выдача звезд**: Используйте команду:\n"
             "`/grant_stars <user_id> <сумма>`"
         )
         msg += admin_info
    
    await callback.message.edit_text(
        msg,
        parse_mode="Markdown",
        reply_markup=get_back_to_menu_keyboard()
    )
    await callback.answer()


# --- БЛОК 1: ПОКУПКА ПОДПИСЧИКОВ (buy_subs_start) ---

# ... (buy_subscribers_start, process_channel_username без изменений) ...

@router.callback_query(F.data == "buy_subs_start")
async def buy_subscribers_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(OrderState.WAITING_FOR_CHANNEL_USERNAME)
    await callback.message.edit_text(
        "📝 **ДОБАВЛЕНИЕ НОВОГО ЗАКАЗА**\n\n"
        "Отправьте мне **@username** вашего канала (например, `@MyChannel`).\n\n"
        "⚠️ **Важно**: Бот должен быть **Администратором** в этом канале, чтобы мы могли проверять выполнение задания.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Отмена", callback_data="back_to_menu")]
        ])
    )
    await callback.answer()

@router.message(OrderState.WAITING_FOR_CHANNEL_USERNAME)
async def process_channel_username(message: types.Message, state: FSMContext, bot: Bot): 
    channel_username = message.text.strip().lower()
    
    if not channel_username.startswith('@'):
        channel_username = '@' + channel_username
    
    if not re.match(r'^@[a-z0-9_]{5,32}$', channel_username):
        await message.answer("❌ **Неверный формат @username.** Пожалуйста, отправьте его в формате `@ChannelUsername`.")
        return

    # 1. Отправляем сообщение о проверке (эффект "загрузки")
    checking_message = await message.answer("🔄 **Идет проверка канала... Пожалуйста, подождите.** (5 сек.)", parse_mode="Markdown")
    
    # 2. Добавляем задержку
    await asyncio.sleep(5) 

    # 3. ПРОВЕРКА: Бот должен быть администратором в канале
    try:
        # Пытаемся получить информацию о боте в чате
        bot_member = await bot.get_chat_member(channel_username, bot.id)
        
        # Проверяем, является ли бот администратором или создателем
        if bot_member.status not in ['administrator', 'creator']:
            await checking_message.edit_text(
                "❌ **Ошибка доступа!** Бот не является администратором в этом канале.\n\n"
                "Для продолжения: **добавьте бота в администраторы канала** и **предоставьте ему право на приглашение пользователей** (Invite Users via Link).",
                parse_mode="Markdown",
                reply_markup=get_back_to_menu_keyboard()
            )
            await state.clear()
            return
            
    except TelegramBadRequest as e:
        # Ошибка, если канал не найден или бот не имеет доступа
        error_text = str(e).lower()
        
        # Унифицированное сообщение для всех ошибок, связанных с доступом/приватностью/списком участников
        if "chat not found" in error_text or "bot is not a member" in error_text or "member list is inaccessible" in error_text:
            await checking_message.edit_text(
                f"❌ **Канал не найден, приватный или список участников недоступен.**\n\n"
                f"Убедитесь, что бот **добавлен и является Администратором** в канале.",
                parse_mode="Markdown",
                reply_markup=get_back_to_menu_keyboard()
            )
        else:
            logging.error(f"TelegramBadRequest during admin check: {e}")
            await checking_message.edit_text(
                f"❌ Произошла ошибка при проверке канала. Код ошибки: `{e}`. Попробуйте еще раз.",
                reply_markup=get_back_to_menu_keyboard()
            )
        await state.clear()
        return
    except Exception as e:
        logging.error(f"General error during admin check: {e}")
        await checking_message.edit_text(
            "❌ Произошла непредвиденная ошибка при проверке канала. Попробуйте еще раз.",
            reply_markup=get_back_to_menu_keyboard()
        )
        await state.clear()
        return

    # 4. Если проверка пройдена успешно:
    try:
        # Пытаемся удалить сообщение о проверке. Если не удается - ничего страшного.
        await checking_message.delete() 
    except Exception:
        pass 

    await state.update_data(channel=channel_username)
    await state.set_state(OrderState.WAITING_FOR_TARGET_SUBS)

    await message.answer(
        f"✅ Канал **{channel_username}** принят и права администратора проверены.\n\n"
        f"🔢 Теперь укажите, **сколько подписчиков** вы хотите. (Минимум 15)\n"
        f"**Стоимость**: **{USER_ORDER_COST_STARS:.1f} ⭐️** за 1 подписчика.",
        parse_mode="Markdown"
    )

@router.message(OrderState.WAITING_FOR_TARGET_SUBS)
async def process_target_subs(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    
    MIN_SUBS_COUNT = 15 # <-- Ваш лимит 15

    try:
        count = int(message.text.strip())
        
        # --- ДОБАВЛЕНА ПРОВЕРКА МИНИМАЛЬНОГО КОЛИЧЕСТВА ---
        if count < MIN_SUBS_COUNT:
            await message.answer(f"❌ **Минимальное количество подписчиков** для заказа — **{MIN_SUBS_COUNT}**.")
            return
        # ---------------------------------------------------
            
    except ValueError:
        await message.answer("❌ **Неверное количество.** Введите целое число (минимум 15).")
        return

    data = await state.get_data()
    channel_username = data.get("channel")
    user_db = get_user(user_id)
    current_stars = user_db.get("stars", 0)
    total_cost = count * USER_ORDER_COST_STARS

    if current_stars < total_cost:
        await message.answer(
            f"❌ **Недостаточно звёзд!**\n\n"
            f"Вам нужно **{total_cost:.1f} ⭐️** для {count} подписчиков. У вас **{current_stars:.1f} ⭐️**.",
            parse_mode="Markdown",
            reply_markup=get_back_to_menu_keyboard()
        )
        await state.clear()
        return

    # Списываем звезды и создаем заказ
    order_id = add_user_order(user_id, channel_username, count)
    
    if order_id is None:
        await message.answer("❌ **Произошла ошибка при сохранении заказа.** Попробуйте позже.")
        await state.clear()
        return

    update_stars(user_id, -total_cost, reason=f"order_purchase_{order_id}")
    
    await message.answer(
        f"🎉 **ЗАКАЗ СОЗДАН!**\n\n"
        f"**Канал**: {channel_username}\n"
        f"**Количество**: {count} подписчиков\n"
        f"**Списано**: **-{total_cost:.1f} ⭐️**\n"
        f"**Остаток**: **{(current_stars - total_cost):.1f} ⭐️**",
        parse_mode="Markdown",
        reply_markup=main_menu_kb
    )
    await state.clear()

# --- БЛОК 2: ПРОСМОТР ЗАКАЗОВ (my_orders) ---

# ... (view_orders, view_order_details без изменений) ...

@router.callback_query(F.data == "my_orders")
async def view_orders(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await callback.answer()
    
    orders = get_user_orders(user_id)
    
    if not orders:
        text = "😔 У вас пока нет активных заказов на подписчиков."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✨ Купить подписчиков", callback_data="buy_subs_start")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_menu")]
        ])
    else:
        # Генерируем кнопки для каждого заказа
        keyboard_buttons = []
        for order in orders:
            task_id = order['id']
            completion_progress = order.get('current_completions', 0)
            target = order.get('max_completions', 0)
            status_emoji = '🎉' if completion_progress >= target else '⏳'
            
            # Формат кнопки: [Эмодзи] Заказ №ID (Прогресс/Цель)
            button_text = f"{status_emoji} Заказ №{task_id} ({completion_progress}/{target})"
            keyboard_buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"show_order_{task_id}")])
            
        # Добавляем кнопки управления
        keyboard_buttons.append([InlineKeyboardButton(text="✨ Купить ещё подписчиков", callback_data="buy_subs_start")])
        keyboard_buttons.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="back_to_menu")])
        
        kb = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        text = (
            "📋 **ВАШИ ЗАКАЗЫ**\n\n"
            "Выберите заказ из списка ниже для просмотра деталей и статистики:"
        )

    await callback.message.edit_text(
        text, 
        parse_mode="Markdown",
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("show_order_"))
async def view_order_details(callback: types.CallbackQuery):
    global USER_ORDER_COST_STARS, USER_TASK_REWARD_STARS 
    
    task_id = int(callback.data.split("_")[-1])
    await callback.answer()
    
    order = get_order_details(task_id)
    
    if not order:
        await callback.message.edit_text(
            "❌ **Ошибка**. Заказ не найден.",
            reply_markup=get_back_to_menu_keyboard()
        )
        return

    completion_progress = order.get('current_completions', 0)
    target = order.get('max_completions', 0)
    total_cost_paid = target * USER_ORDER_COST_STARS
    
    status_emoji = '🎉' if completion_progress >= target else '⏳'
    status = 'Завершено' if completion_progress >= target else 'В работе'

    msg = (
        f"**📋 ДЕТАЛИ ЗАКАЗА №{task_id}**\n\n"
        f"{status_emoji} **Статус**: **{status}**\n"
        f"🔗 **Канал**: `{order['channel']}`\n"
        f"📈 **Прогресс**: **{completion_progress}** из **{target}** подписчиков\n\n"
        f"💰 **Общая стоимость заказа**: **{total_cost_paid:.1f} ⭐️**\n"
        f"💎 **Награда исполнителю**: {USER_TASK_REWARD_STARS:.1f} ⭐️/подписка"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ К списку заказов", callback_data="my_orders")],
        [InlineKeyboardButton(text="🏠 В меню", callback_data="back_to_menu")]
    ])
    
    await callback.message.edit_text(
        msg,
        parse_mode="Markdown",
        reply_markup=kb
    )

# --- БЛОК 3: ЗАРАБОТОК (earn_task_menu) (ОБНОВЛЕНО) ---

@router.callback_query(F.data == "earn_task_menu")
async def earn_stars_start(callback: types.CallbackQuery, bot: Bot):
    """Приоритет: Flyer/Subgram -> Пользовательские задания (1 ⭐️)."""
    user_id = callback.from_user.id
    user = callback.from_user
    
    # 1. Проверяем внешние задачи (Flyer/Subgram) - Приоритет 1
    # Эта функция теперь отображает задание Flyer, если оно есть.
    subgram_data = await flyer_check_wrapper(user=user, message=callback.message, action="subscribe")
    
    # Если Flyer API показал задание (skip=False), то выполнение функции прекращается.
    if not subgram_data.get("skip"):
        await callback.answer()
        return

    await callback.answer() # Ответ на callback, если Flyer не дал задания

    # 2. Переходим к пользовательским задачам, если Flyer не дал заданий
    task = get_next_order_task(user_id) 
    
    if task:
        # Найдена пользовательская задача
        reward = USER_TASK_REWARD_STARS 
        channel = task['channel']
        task_id = task['id']
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🚀 Перейти и Подписаться", url=f"https://t.me/{channel.strip('@')}")],
            [InlineKeyboardButton(text=f"✅ Проверить ({reward:.1f} ⭐️)", callback_data=f"check_user_order_{task_id}")],
            [InlineKeyboardButton(text="🔁 Пропустить/След. задание", callback_data="earn_task_menu")] 
        ])
        
        await callback.message.edit_text(
            "💰 **ЗАДАНИЕ: ПОДПИСКА НА КАНАЛ**\n\n"
            f"Подпишитесь на канал: **`{channel}`**\n"
            f"**Награда**: **{reward:.1f} ⭐️**",
            parse_mode="Markdown",
            reply_markup=kb
        )
        
    else:
        # Нет доступных пользовательских задач
        await callback.message.edit_text(
            "😔 **ЗАДАНИЯ ЗАКОНЧИЛИСЬ**\n\n"
            "На данный момент нет доступных заказов ни от Flyer, ни от пользователей. Попробуйте зайти позже.",
            parse_mode="Markdown",
            reply_markup=get_back_to_menu_keyboard()
        )

# --- НОВЫЙ ХЕНДЛЕР: ПРОВЕРКА ЗАДАНИЯ FLYER ---

@router.callback_query(F.data.startswith("check_flyer_"))
async def check_flyer_task_done(callback: types.CallbackQuery, bot: Bot):
    signature = callback.data.split("check_flyer_")[-1]
    user_id = callback.from_user.id
    logging.info(f"[Flyer] Пользователь {user_id} нажал 'check_flyer' для задания {signature}")
    
    await callback.answer("⏳ Идет проверка задания...", show_alert=False)
    
    result = await check_flyer_task(user_id, signature)
    
    if result['success']:
        reward = FLYER_TASK_REWARD
        update_stars(user_id, reward, reason=f"flyer_task_complete_{signature}")
        logging.info(f"[Flyer] Пользователю {user_id} начислено {reward} ⭐️ за задачу {signature}")
        await callback.answer(f"✅ Задание выполнено! Начислено {reward:.1f} ⭐️", show_alert=True)
        
    elif result.get('result') == 'wait':
        logging.info(f"[Flyer] Задание {signature} для пользователя {user_id} ожидает подтверждения")
        await callback.answer("🔄 Задание ожидает подтверждения. Попробуйте позже.", show_alert=True)
        await earn_stars_start(callback, bot)
        return
        
    elif result.get('result') in ['key_error', 'api_error']:
        logging.warning(f"[Flyer] API ошибка при проверке задания {signature} пользователем {user_id}")
        await callback.answer("❌ Ошибка API при проверке задания.", show_alert=True)
        
    else:
        logging.info(f"[Flyer] Задание {signature} для пользователя {user_id} не выполнено или просрочено")
        await callback.answer("❌ Задание не выполнено или истек срок.", show_alert=True)
        
    await earn_stars_start(callback, bot)



@router.callback_query(F.data.startswith("check_user_order_"))
async def check_user_order_done(callback: types.CallbackQuery, bot: Bot):
    """Проверка подписки на пользовательский канал и начисление награды."""
    task_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    task = get_order_details(task_id)
    if not task:
        await callback.answer("❌ Задание не найдено или уже выполнено.", show_alert=True)
        await earn_stars_start(callback, bot) 
        return
        
    reward = USER_TASK_REWARD_STARS
    channel = task['channel']
    
    try:
        # Проверяем подписку. 
        member = await bot.get_chat_member(channel, user_id)
        
        if member.status in ['member', 'creator', 'administrator']:
            # Успех: Начисляем звезды и обновляем прогресс
            update_stars(user_id, reward, reason=f"user_order_complete_{task_id}")
            add_user_task_done(user_id, task_id)
            increment_order_completion(task_id) 
            
            await callback.answer(f"✅ Задание выполнено! Начислено {reward:.1f} ⭐️", show_alert=True)
            
            # Показываем следующее задание/меню
            await earn_stars_start(callback, bot) 
            
            # Проверка завершения заказа и уведомление создателя
            task_details_after = get_order_details(task_id)
            if task_details_after and task_details_after['current_completions'] >= task_details_after['max_completions']:
                 creator_id = task_details_after.get('creator_id')
                 if creator_id:
                     # Уведомление создателя заказа, что его заказ выполнен
                     await bot.send_message(creator_id, f"🎉 Ваш заказ на канал **{channel}** ({task_details_after['max_completions']} подписок) **полностью выполнен!**", parse_mode="Markdown")
                             
        else:
            await callback.answer("❌ Вы не подписаны на канал. Пожалуйста, сначала подпишитесь.", show_alert=True)
            
    except Exception as e:
        logging.error(f"Error checking sub for order {task_id}: {e}")
        # Это сообщение возникает, если бот не имеет прав администратора в канале.
        await callback.answer("❌ Ошибка проверки подписки. Канал, вероятно, приватный. Пожалуйста, убедитесь, что бот является администратором в канале.", show_alert=True)


# -----------------------------------------------------------
# ---------------------- 4. ЗАПУСК БОТА ---------------------
# -----------------------------------------------------------

async def main():
    # Инициализация Bot
    bot = Bot(
        token=BOT_TOKEN, 
        default=DefaultBotProperties(parse_mode="Markdown") # Используем Markdown для форматирования
    )
    dp = Dispatcher()
    
    # Подключаем роутер с логикой
    dp.include_router(router)
    
    # Инициализация БД
    get_conn() 
    
    logging.info("🚀 Бот запущен!")
    # Запуск
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Бот остановлен вручную.")