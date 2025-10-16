from aiogram import Router, types, F
from aiogram.types import ReplyKeyboardRemove
from aiogram.filters import CommandStart
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from database import delete_user
from database import (
    get_user, add_user, update_bonus_date, get_top_users_by_stars,
    get_top_users_by_tasks, increment_tasks_done, update_stars,
    create_withdraw_request, get_withdraw_requests, update_withdraw_request, get_withdraw_request_by_id, get_referrals_count
)
from datetime import datetime, timedelta
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram import Bot
from database import get_conn
import asyncio
import aiogram
import re
from aiogram.exceptions import TelegramBadRequest
import random, string
from aiogram.filters import CommandStart
from database import complete_task, get_task
from database import complete_manual_task
import aiohttp
import logging
from database import (
    get_user,
    update_stars,
    set_vip,
    get_vip_level,
    update_last_click,
    get_last_click
)
from aiogram.filters import Command
from database import get_top_clicker_users



log = logging.getLogger(__name__)


FLYER_API_KEY = "FL-elIDwf-wTDlrP-ritjwp-mbxRqG"

admin_task_creation = {}  # {admin_id: {"step": int, "channel": str, "type": str, "stars": float}}

admin_manual_task_creation = {}  # {admin_id: {"step": int, "title": str, "description": str, "link": str, "stars": float}}
all_referrals = 0
user_states = {}
router = Router()
referrals = {}
admin_adding_channel = {}
ADMIN_PASSWORD = "FREEPASSWORDx1" 
ADMIN_ID = [1500618394]
admin_auth_waiting = set()   # user_id которые ввели запрос на ввод пароля и ожидают ввести пароль
admin_sessions = set()       # user_id которые успешно вошли в админ панель
REQUIRED_CHANNELS = ["@FreeStarsXQ"]
WITHDRAW_OPTIONS = [50, 75, 100, 200]
admin_adding_channel = {}  # временное состояние добавления канала

FIXED_TASKS = [
    {"id": -1, "url": "https://t.me/+VDA7NAoJBbkwZjQy", "check_id": -1002920378443, "stars": 50},
    {"id": -2, "url": "https://t.me/+jZY37XZ12Cw0NjZi", "check_id": -1002996957244, "stars": 20},
    {"id": -3, "url": "https://t.me/+3XXGoaVvI7ViNTQy", "check_id": -1003174397291, "stars": 10},
]

def reset_user_states(user_id: int):
    user_states.pop(user_id, None)
    referrals.pop(user_id, None)
    admin_task_creation.pop(user_id, None)
    admin_task_editing.pop(user_id, None)
    admin_coupon_creation.pop(user_id, None)
    admin_adding_channel.pop(user_id, None)

def get_profile_kb(user_id: int):
    # Базовые кнопки для всех
    buttons = [
        [InlineKeyboardButton(text="💸 Вывод 💸", callback_data="withdraw")],
        [InlineKeyboardButton(text="🏷 Активировать купон 🏷", callback_data="activate_coupon")]
    ]
    buttons.append([InlineKeyboardButton(text="Подержка", url="https://t.me/deluxesl")])
    buttons.append([InlineKeyboardButton(text="Выводы", url="https://t.me/FreeStarsXQPay")])
    # Кнопка админа только для тебя
    if user_id in ADMIN_ID:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin_panel")])
        print("user_id:", user_id, "ADMIN_ID:", ADMIN_ID, "check:")

    # Кнопка назад для всех
    buttons.append([InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Статистика (меню выбора категории)
statistics_menu_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Топ звезд за сегодня", callback_data="stat_today")],
    [InlineKeyboardButton(text="Топ звезд за всё время", callback_data="stat_all")],
    [InlineKeyboardButton(text="Топ кликера", callback_data="clicker_top")],
    [InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")]
])

# Статистика (внутри топа — только назад)
statistics_back_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⬅️", callback_data="statistics")]
])

# Главное меню (InlineKeyboardMarkup)
main_menu_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="👤 Мой Профиль 👤", callback_data="profile"),
    ],
    [
        InlineKeyboardButton(text="✨ Кликер ✨", callback_data="clicker"),
    ],
    [
        InlineKeyboardButton(text="🎯 Задания 🎯", callback_data="tasks"),
    ],
    [
        InlineKeyboardButton(text="💎 VIP-подписки", callback_data="VIP_pod"),
        InlineKeyboardButton(text="🎰 Рулетка", callback_data="roulette_menu"),
    ],
    [
        InlineKeyboardButton(text="🎁 Бонус дня", callback_data="daily_bonus"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="statistics"),
    ],
    [
        InlineKeyboardButton(text="📊 Реферальная сcылка 📊", callback_data="ref_link"),
    ]
])

vip_help_kb = InlineKeyboardMarkup(inline_keyboard=[
    [
        InlineKeyboardButton(text="VIP-подписка I степени  ", url="https://t.me/+3XXGoaVvI7ViNTQy"),
        InlineKeyboardButton(text="VIP-Подписка II степени", url="https://t.me/+jZY37XZ12Cw0NjZi"),
        InlineKeyboardButton(text="VIP-Подписка III степени", url="https://t.me/+VDA7NAoJBbkwZjQy")
    ],
    [
        InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")
    ]
])

main_menu_reply_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="🏠 Главное меню")]
    ],
    resize_keyboard=True
)


admin_main_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="📋 Заявки на выплаты", callback_data="admin_requests")],
    [InlineKeyboardButton(text="👥 Участники", callback_data="admin_users")],
    [InlineKeyboardButton(text="👥 Участники с подписками", callback_data="admin_vip_users")],
    [InlineKeyboardButton(text="📊 Статистика пользователей", callback_data="admin_users_stats")],
    [InlineKeyboardButton(text="🏷 Управление купонами", callback_data="admin_coupons")],
    [InlineKeyboardButton(text="🎯 Список заданий", callback_data="admin_tasks_list")],
    [InlineKeyboardButton(text="🛠 Ручные задания", callback_data="admin_manual_tasks")],
    [InlineKeyboardButton(text="➕ Добавить задание", callback_data="admin_add_task")],
    [InlineKeyboardButton(text="➕ Добавить купон", callback_data="admin_add_coupon")],
    [InlineKeyboardButton(text="📣 Рассылка всем", callback_data="admin_broadcast")],
    [InlineKeyboardButton(text="📥 времено не работает!", callback_data="admin_task_submissions")],
    [InlineKeyboardButton(text="🛠 времено не работает!", callback_data="admin_channels")],
    [InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")]
])


# когда показываем конкретную заявку — кнопки принять/отклонить
def admin_request_actions_kb(req_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"req_{req_id}_approve"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"req_{req_id}_reject")],
        [InlineKeyboardButton(text="⬅️ Назад в список", callback_data="admin_requests")],
        [InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")]
    ])

backs_menu = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")]
            ])


# Коды стран СНГ
ALLOWED_COUNTRY_CODES = [
    "+7",   # Россия, Казахстан
    "+373", # Молдова
    "+374", # Армения
    "+375", # Беларусь
    "+380", # Украина
    "+992", # Таджикистан
    "+993", # Туркменистан
    "+994", # Азербайджан
    "+995", # Грузия
    "+996", # Кыргызстан
    "+998",  # Узбекистан
    "+48"
]

def normalize_phone(phone: str) -> str:
    digits = ''.join(filter(str.isdigit, phone))
    if digits.startswith("00"):
        digits = digits[2:]
    return f"+{digits}"

def update_user_phone(user_id: int, phone: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET phone = ? WHERE id = ?", (phone, user_id))
    conn.commit()

def create_contact_keyboard() -> ReplyKeyboardMarkup:
    button = KeyboardButton(text="📞 Отправить телефон", request_contact=True)
    return ReplyKeyboardMarkup(
        keyboard=[[button]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

@router.message(CommandStart())
async def cmd_start(message: types.Message):
    user = message.from_user
    user_id = user.id
    username = user.username
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()

    user_db = get_user(user_id)

    if user_db:
        phone = user_db.get("phone")
        if phone and any(normalize_phone(phone).startswith(code) for code in ALLOWED_COUNTRY_CODES):
            # 🔹 Проверка подписки через Flyer API даже для старых пользователей
            data = await flyer_check_subscription(user_id, message)

            if data.get("skip"):
                await message.answer(
                "📋 <b>Главное меню</b>\n\n"
                "⭐️ <i>Зарабатывай звёзды, выполняя задания и приглашая друзей!</i> 👥\n\n"
                "⚠️ <b>Важно:</b>\n"
                "Честная игра = честные награды 💎\n"
                "За накрутку рефералов — ❌ <u>бан без выплат</u>.",
                    reply_markup=main_menu_kb,
                    parse_mode="HTML"
                )
            else:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
                    ]
                )
                await message.answer(
                    data.get("info", "Для продолжения подпишитесь на обязательные каналы 👆"),
                    reply_markup=kb
                )
            return


    # Новый пользователь
    args = message.text.split()
    referrer_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    add_user(user_id, username, None, referrer_id, full_name)

    await message.answer(
        "Пройдите проверку на бота 👇🏻\n\nЧтобы избежать массовой накрутки со стороны нечестных пользователей, мы вынуждены установить данную проверку.\n\nСпасибо за понимание! 🫂",
        reply_markup=create_contact_keyboard()
    )

async def flyer_check_subscription(user_id: int, message: types.Message):
    url = "https://api.flyerservice.io/check"
    headers = {"Content-Type": "application/json"}
    payload = {
        "key": FLYER_API_KEY,
        "user_id": user_id,
        "language_code": message.from_user.language_code or "ru",
        "message": {
            "text": "⚠️ Подпишитесь на каналы, чтобы продолжить 👇",
            "button_bot": "🤖 Подписаться на бота",
            "button_channel": "📢 Подписаться на канал",
            "button_boost": "🚀 Boost",
            "button_url": "🔗 Перейти",
            "button_fp": "✅ Проверить"
        }
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    logging.error(f"[FlyerAPI] Ошибка {resp.status}, текст: {await resp.text()}")
                    return {"skip": False, "error": f"Flyer API недоступен ({resp.status})"}

                try:
                    data = await resp.json()
                    logging.info(f"[FlyerAPI] Ответ: {data}")
                    return data
                except Exception as e:
                    text = await resp.text()
                    logging.error(f"[FlyerAPI] Не JSON: {e}, ответ: {text}")
                    return {"skip": False, "error": "Некорректный ответ от Flyer API"}
    except Exception as e:
        logging.error(f"[FlyerAPI] Ошибка: {e}")
        return {"skip": False, "error": str(e)}


@router.callback_query(F.data == "fp_check")
async def flyer_check_done(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = await flyer_check_subscription(user_id, callback.message)
    logging.info(f"[Flyer CHECK DONE] Ответ: {data}")

    if not data.get("skip"):
        # ❌ всё ещё не подписан → показываем кнопку "проверить"
        try:
            await callback.message.delete()
        except:
            pass
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы 👆"),
            reply_markup=kb
        )

    else:
        # ✅ подписка есть → открываем меню
        try:
            await callback.message.delete()
        except:
            pass
        await callback.message.answer(
                "📋 <b>Главное меню</b>\n\n"
                "⭐️ <i>Зарабатывай звёзды, выполняя задания и приглашая друзей!</i> 👥\n\n"
                "⚠️ <b>Важно:</b>\n"
                "Честная игра = честные награды 💎\n"
                "За накрутку рефералов — ❌ <u>бан без выплат</u>.",
            reply_markup=main_menu_kb,
            parse_mode="HTML"
        )

    await callback.answer()



    
# Декоратор и функция объявляются только один раз!
@router.message(lambda m: m.contact is not None)
async def handle_contact(message: types.Message):
    user = message.from_user
    user_id = user.id
    username = user.username
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
    phone = normalize_phone(message.contact.phone_number)

    if any(phone.startswith(code) for code in ALLOWED_COUNTRY_CODES):
        update_user_phone(user_id, phone)

        await message.answer(
            "✅ Телефон подтверждён. Добро пожаловать!",
            reply_markup=ReplyKeyboardRemove()
        )

        # 🔹 Проверка обязательной подписки через Flyer API
        data = await flyer_check_subscription(user_id, message)

        if data.get("skip"):  
            # ✅ Подписка есть → открываем главное меню
            await message.answer(
                "📋 <b>Главное меню</b>\n\n"
                "⭐️ <i>Зарабатывай звёзды, выполняя задания и приглашая друзей!</i> 👥\n\n"
                "⚠️ <b>Важно:</b>\n"
                "Честная игра = честные награды 💎\n"
                "За накрутку рефералов — ❌ <u>бан без выплат</u>.",
                reply_markup=main_menu_kb,
                parse_mode="HTML"
            )
            
            # 🟢 ИСПРАВЛЕНИЕ: БОНУС ПЕРЕМЕЩЁН СЮДА!
            user_db = get_user(user_id)
            referrer_id = user_db.get("referrer_id") if user_db else None
            
            if referrer_id:
                update_stars(referrer_id, 3, reason="referral_bonus")
                try:
                    await message.bot.send_message(
                        referrer_id,
                        f"🎉 Пользователь @{username} зарегистрировался по вашей ссылке! Вы получили +3 ⭐️"
                    )
                except Exception as e:
                    # Лучше использовать logging.error, как мы договорились
                    print(f"[handle_contact] Ошибка уведомления реферала {referrer_id}: {e}")
            
            return # ❗ ДОБАВЛЕН RETURN, чтобы не выполнять лишний код

        else:
            # ❌ Подписки нет → даём кнопку "Я подписался"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
                ]
            )
            await message.answer(
                data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
                reply_markup=kb
            )
            return
            
    else:
        await message.answer(
            "❌ К сожалению, наш бот не доступен для вашего региона.",
            reply_markup=create_contact_keyboard()
        )




@router.callback_query(F.data == "check_channels")
async def check_channels_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bot = callback.bot

    user_info = referrals.get(user_id)
    if not user_info or "temp_user" not in user_info:
        await callback.answer("❌ Временные данные не найдены. Повторите регистрацию.", show_alert=True)
        return

    temp_data = user_info["temp_user"]
    referrer_id = user_info.get("referrer_id")

    # Добавляем пользователя в БД
    add_user(
        user_id,
        temp_data["username"],
        temp_data["phone"],
        referrer_id,
        temp_data["full_name"]
    )
    referrals.pop(user_id)  # удаляем временные данные

    await callback.message.answer("✅ Регистрация завершена! Добро пожаловать!")

    # Главное меню
    await callback.message.answer(
                "📋 <b>Главное меню</b>\n\n"
                "⭐️ <i>Зарабатывай звёзды, выполняя задания и приглашая друзей!</i> 👥\n\n"
                "⚠️ <b>Важно:</b>\n"
                "Честная игра = честные награды 💎\n"
                "За накрутку рефералов — ❌ <u>бан без выплат</u>.",
        reply_markup=main_menu_kb
    )

    # Начисляем бонус рефералу
    if referrer_id:
        try:
            update_stars(referrer_id, 3, reason="referral_bonus")
            await bot.send_message(
                referrer_id,
                f"🎉 Пользователь @{temp_data['username']} зарегистрировался по вашей ссылке! Вы получили +3 ⭐️"
            )
            print(f"[check_channels_cb] Бонус +3 ⭐️ начислен рефералу {referrer_id}")
        except Exception as e:
            print(f"[check_channels_cb] Ошибка уведомления реферала {referrer_id}: {e}")

# ----------------- profile -----------------
def get_user_info(user: dict):
    return {
        "user_id": user["id"],
        "username": user.get("username"),
        "phone": user.get("phone"),
        "stars": user.get("stars") or 0,
        "referrer_id": user.get("referrer_id"),
        "created_at": user.get("created_at"),
        "last_bonus_date": user.get("last_bonus_date"),
        "tasks_done": user.get("tasks_done") or 0,
        "full_name": user.get("full_name")
    }

@router.message(Command("setvip"))
async def cmd_setvip(message: types.Message):
    if message.from_user.id not in ADMIN_ID:
        await message.answer("⛔ У вас нет прав на эту команду.")
        return

    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Использование: /setvip <user_id> <level>\nПример: /setvip 123456789 2\nДля снятия VIP: /setvip 123456789 0")
        return

    try:
        uid = int(parts[1])
        level = int(parts[2])
        set_vip(uid, level)

        if level == 0:
            vip_text = "снята (отсутствует)"
        elif level == 1:
            vip_text = "I степени"
        elif level == 2:
            vip_text = "II степени"
        elif level == 3:
            vip_text = "III степени"
        else:
            vip_text = f"{level}-го уровня"

        await message.answer(f"✅ Пользователю {uid} установлена VIP {vip_text}")

        try:
            if level == 0:
                await message.bot.send_message(uid, "⚠️ Ваша VIP-подписка была снята администратором.")
            else:
                await message.bot.send_message(uid, f"🎉 Вам выдана новая VIP-подписка: <b>{vip_text}</b>!", parse_mode="HTML")
        except:
            pass

    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


@router.message(F.text == "📱 Профиль")
async def profile(message: types.Message):
    user = get_user(message.from_user.id)
    user_id = message.from_user.id
    data = await flyer_check_subscription(user_id, message)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
        ]
    )
    if not data.get("skip"):
        await message.answer(
            await message.answer(data.get("info", " Для продолжения подпишитесь на обязательные каналы. 👆"), reply_markup=kb)
        )
        return
    if not user:
        await message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        return

    info = get_user_info(user)
    bot_username = "FreeStarsxsbot"
    referral_link = f"https://t.me/{bot_username}?start={info['user_id']}"
    name_to_show = info['full_name'] or (f"@{info['username']}" if info['username'] else "Без имени")
    vip = get_vip_level(user_id)
    if vip == 1:
        vip_text = "I-степени"
    elif vip == 2:
        vip_text = "II-степени"
    elif vip == 3:
        vip_text = "III-степени"
    else:
        vip_text = "Отсутствует"

# 🟢 Считаем только тех, кто предоставил номер телефона (завершил основной этап)
    total_invites = get_conn().cursor().execute(
        "SELECT COUNT(*) FROM users WHERE referrer_id = ? AND phone IS NOT NULL", (user_id,)
    ).fetchone()[0]
    msg = (
        f"<b>✨Ваш профиль</b>\n"
        f"<b>──────────────</b>\n"
        f"<b>👤 Имя: {name_to_show}</b>\n"
        f"<b>🆔 ID: {info['user_id']}</b>\n"
        f"<b>──────────────</b>\n"
        f"💰 Баланс звезд: {info['stars']:.2f} ⭐️\n"
        f"📌 Приглашено вами: {total_invites}\n"
        f"💎 Ваша VIP-подписка: {vip_text}\n\n"
        f"🔗<b> Ваша реферальная ссылка:</b>\n<code>{referral_link}</code>"
    )
    kb = get_profile_kb(user_id)
    await message.answer(msg, parse_mode="HTML", reply_markup=kb)

@router.callback_query(F.data == "ref_link")
async def ref_links(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)

    # 🔹 Проверка подписки перед показом реф. ссылки
    data = await flyer_check_subscription(user_id, callback.message)
    if not data.get("skip"):
        # ❌ нет подписки → показываем кнопку "Я подписался"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        try:
            await callback.message.answer(
                data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
                reply_markup=kb
            )
        except:
            pass
        await callback.answer()
        return
    
    # 🔹 Если юзер не зарегистрирован
    if not user:
        await callback.message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        await callback.answer()
        return

    info = get_user_info(user)
    bot_username = "FreeStarsxsbot"
    referral_link = f"https://t.me/{bot_username}?start={info['user_id']}"
    name_to_show = info['full_name'] or (f"@{info['username']}" if info['username'] else "Без имени")

# 🟢 Считаем только тех, кто предоставил номер телефона (завершил основной этап)
    total_invites = get_conn().cursor().execute(
        "SELECT COUNT(*) FROM users WHERE referrer_id = ? AND phone IS NOT NULL", (user_id,)
    ).fetchone()[0]

    msg = (
        f"<b>Приглашайте по этой ссылке своих друзей, и получайте +3 ⭐️ за каждого!</b>\n\n"
        f"🔗 Ваша реферальная ссылка:\n<code>{referral_link}</code>\n\n"
        f"<b>🎉 Приглашайте по этой ссылке своих друзей, отправляйте её во все чаты и зарабатывайте Звёзды!</b>\n\n"
        f"<b>Приглашено вами: {total_invites} </b>"
    )

    # ✅ Если подписка есть → показываем меню
    await callback.message.edit_text(msg, parse_mode="HTML", reply_markup=backs_menu)
    await callback.answer()




@router.callback_query(F.data == "profile")
async def profile_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)

    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, callback.message)
    if not data.get("skip"):
        # ❌ Нет подписки → показываем кнопку "Я подписался"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        try:
            await callback.message.answer(
                data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
                reply_markup=kb
            )
        except:
            pass
        await callback.answer()
        return

    # 🔹 Если пользователь не найден
    if not user:
        await callback.message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        await callback.answer()
        return

    # ✅ Если всё ок → показываем профиль
    info = get_user_info(user)
    bot_username = "FreeStarsxsbot"
    referral_link = f"https://t.me/{bot_username}?start={info['user_id']}"
    name_to_show = info['full_name'] or (f"@{info['username']}" if info['username'] else "Без имени")

# 🟢 Считаем только тех, кто предоставил номер телефона (завершил основной этап)
    total_invites = get_conn().cursor().execute(
        "SELECT COUNT(*) FROM users WHERE referrer_id = ? AND phone IS NOT NULL", (user_id,)
    ).fetchone()[0]
    vip = get_vip_level(user_id)
    if vip == 1:
        vip_text = "I-степени"
    elif vip == 2:
        vip_text = "II-степени"
    elif vip == 3:
        vip_text = "III-степени"
    else:
        vip_text = "Отсутствует"
    msg = (
        f"<b>✨Ваш профиль</b>\n"
        f"<b>──────────────</b>\n"
        f"<b>👤 Имя: {name_to_show}</b>\n"
        f"<b>🆔 ID: {info['user_id']}</b>\n"
        f"<b>──────────────</b>\n"
        f"💰 Баланс звезд: {info['stars']:.2f} ⭐️\n"
        f"📌 Приглашено вами: {total_invites}\n"
        f"💎 Ваша VIP-подписка: {vip_text}\n\n"
        f"🔗<b> Ваша реферальная ссылка:</b>\n<code>{referral_link}</code>"
    )

    kb = get_profile_kb(user_id)
    await callback.message.edit_text(msg, parse_mode="HTML", reply_markup=kb)

    await callback.answer()



# ----------------- Bonus -----------------
def get_time_until_next_bonus():
    now = datetime.now()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    delta = tomorrow - now
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours} ч {minutes} мин"

@router.message(F.text == "🎁 Бонус дня")
async def bonus_day(message: types.Message):
    user = get_user(message.from_user.id)
    user_id = message.from_user.id
    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, message)
    if not data.get("skip"):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        return   

    if not user:
        await message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        return

    info = get_user_info(user)
    today = datetime.now().date().isoformat()
    if info['last_bonus_date'] == today:
        left = get_time_until_next_bonus()
        await message.answer(
            f"❗️ Бонус уже получен сегодня.\n⌛ До следующего бонуса: {left}",
            reply_markup=backs_menu
        )
        return

    update_bonus_date(info['user_id'], today)
    update_stars(info['user_id'], 0.6, reason="daily_bonus")
    await message.answer("🎉 Вы получили бонус дня +0.6 ⭐️", reply_markup=backs_menu)


@router.callback_query(F.data == "daily_bonus")
async def daily_bonus_cb(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    user_id = callback.from_user.id
    if not user:
        await callback.message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        await callback.answer()
        return

    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, callback.message)
    if not data.get("skip"):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        await callback.answer()
        return

    info = get_user_info(user)
    today = datetime.now().date().isoformat()
    if info['last_bonus_date'] == today:
        left = get_time_until_next_bonus()
        await callback.message.edit_text(
            f"❗️ Бонус уже получен сегодня.\n⌛ До следующего бонуса: {left}",
            reply_markup=backs_menu
        )
        await callback.answer()
        return

    update_bonus_date(info['user_id'], today)
    update_stars(info['user_id'], 0.6, reason="daily_bonus")
    await callback.message.edit_text("🎉 Вы получили бонус дня +0.6 ⭐️", reply_markup=backs_menu)
    await callback.answer()


# Inline клавиатура для заданий
def task_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выполнить задание", callback_data=f"complete_task_{task_id}")],
        [InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")]
    ])

# ----------------- Statistics -----------------
@router.message(F.text == "📊 Статистика")
async def statistics_menu(message: types.Message):
    user_id = message.from_user.id

    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, message)
    if not data.get("skip"):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        return

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT SUM(stars) as total_stars FROM users")
        total_stars = cur.fetchone()["total_stars"] or 0
        total_starx = total_stars + 3001

    await message.answer(
        "📊 Выберите категорию статистики:\n\n"
        "Баланс бота: 61100 ⭐️\n"
        f"Всего звезд на балансах: {total_starx:.2f} ⭐️",
        reply_markup=statistics_menu_kb
    )


@router.callback_query(F.data == "statistics")
async def statistics_cb(callback: types.CallbackQuery):
    # 🔹 Проверка подписки
    user_id = callback.from_user.id
    data = await flyer_check_subscription(user_id, callback.message)
    if not data.get("skip"):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        await callback.answer()
        return

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT SUM(stars) as total_stars FROM users")
        total_stars = cur.fetchone()["total_stars"] or 0
        total_starx = total_stars + 3001

    await callback.message.edit_text(
        "📊 Выберите категорию статистики:\n\n"
        "Баланс бота: 61100 ⭐️\n"
        f"Всего звезд на балансах: {total_starx} ⭐️",
        reply_markup=statistics_menu_kb
    )
    await callback.answer()

@router.callback_query(F.data.startswith("stat_"))
async def statistics_type_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    check = await flyer_check_subscription(user_id, callback.message)

    if not check.get("skip"):
        # ❌ нет подписки → кнопка "Я подписался"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        try:
            await callback.message.answer(
                check.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
                reply_markup=kb
            )
        except:
            pass
        await callback.answer()
        return

    # тут уже можно работать с реальными данными статистики
    data = callback.data
    if data == "stat_today":
        top = get_top_users_by_stars(today_only=True)
        title = "Топ-10 пользователей по звёздному балансу за сегодня"
    elif data == "stat_all":
        top = get_top_users_by_stars(today_only=False)
        title = "Топ-10 пользователей по звёздному балансу за все время"
    elif data == "stat_tasks":
        top = get_top_users_by_tasks()
        title = "🎯 Топ-10 пользователей по выполненным заданиям"
    else:
        await callback.answer()
        return

    if not top:
        text = f"{title}\n\nНет данных."
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, u in enumerate(top):
            emoji = medals[i] if i < 3 else f"{i+1}."
            if data == "stat_tasks":
                lines.append(f"{emoji} {u[0]} — {u[1]}")
            else:
                lines.append(f"{emoji} {u[0]} — {u[1]} ⭐️")
        text = title + "\n\n" + "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=statistics_back_kb)
    await callback.answer()


# ----------------- Back to menu -----------------
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = await flyer_check_subscription(user_id, callback.message)

    if not data.get("skip"):
        # ❌ нет подписки → показываем кнопку "Я подписался"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        try:
            await callback.message.answer(
                data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
                reply_markup=kb
            )
        except:
            pass
    else:
        # ✅ подписка есть → открываем главное меню
        try:
            await callback.message.delete()
        except:
            pass
        await callback.message.answer(
                "📋 <b>Главное меню</b>\n\n"
                "⭐️ <i>Зарабатывай звёзды, выполняя задания и приглашая друзей!</i> 👥\n\n"
                "⚠️ <b>Важно:</b>\n"
                "Честная игра = честные награды 💎\n"
                "За накрутку рефералов — ❌ <u>бан без выплат</u>.",
            reply_markup=main_menu_kb,
            parse_mode="HTML"
        )

    # 🔹 подтверждаем callback (один раз!)
    await callback.answer()





@router.callback_query(F.data == "VIP_pod")
async def VIP_POD(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    data = await flyer_check_subscription(user_id, callback.message)

    if not data.get("skip"):
        # ❌ нет подписки → показываем кнопку "Я подписался"
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        try:
            await callback.message.answer(
                data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
                reply_markup=kb
            )
        except:
            pass
    else:
        # ✅ подписка есть → удаляем старое сообщение и показываем VIP меню
        try:
            await callback.message.delete()
        except:
            pass

        await callback.message.answer(
            f"💎 <b>VIP-Подписки: III-степени </b>💎\n"
            f"Три уровня VIP-подписок открывают разные преимущества:\n\n"  
            f"▫️ <b>I-степень</b> [50 ⭐️] — Экслюзивные промокоды уровня I (меньше награды), оповещения о новых ручных заданиях, кешбек в заданиях 10 ⭐️\n" 
            f"▫️ <b>II-степень</b> [100 ⭐️] — Привилегии подписки I-уровня, Награда в кликере 0.2 ⭐️, Экслюзивные купоны уровня II (больше награды), оповещения о всех заданиях, кешбек в заданиях 20 ⭐️, участие в розыгрышах каждую неделю (10% дохода бота)\n"
            f"▫️ <b>III-степень</b> [250 ⭐️] — Привилегии подписок I и II уровня, Награда в кликере 0.4 ⭐️, Экслюзивные купоны уровня III (огромные награды) + абсолютно все промокоды которые активны, кешбек в заданиях 50 ⭐️, участие в розыгрыше дохода бота 30%\n",
            reply_markup=vip_help_kb,
            parse_mode="HTML"
        )

    # 🔹 подтверждаем callback в любом случае
    await callback.answer()


# ----------------- Withdraw flow (пользователь) -----------------
# Нажатие кнопки "💸 Вывод" в профиле
@router.callback_query(F.data == "withdraw")
async def withdraw_cb(callback: types.CallbackQuery):
    user = get_user(callback.from_user.id)
    user_id = callback.from_user.id

    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, callback.message)
    if not data.get("skip"):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        await callback.answer()
        return

    if not user:
        await callback.message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        await callback.answer()
        return

    kb = InlineKeyboardBuilder()
    for amount in WITHDRAW_OPTIONS:
        kb.button(text=f"{amount} ⭐️", callback_data=f"withdraw_amount_{amount}")
    kb.button(text="⬅️", callback_data="profile")

    await callback.message.answer("Выберите сумму для вывода:", reply_markup=kb.as_markup())
    await callback.answer()


# Выбор суммы для вывода
@router.callback_query(F.data.startswith("withdraw_amount_"))
async def withdraw_amount_choice(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)

    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, callback.message)
    if not data.get("skip"):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        await callback.answer()
        return

    if not user:
        await callback.message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        await callback.answer()
        return

    try:
        amount = float(callback.data.split("_")[-1])
    except:
        await callback.answer("Неверная сумма.")
        return

    current_stars = float(user['stars'])
    if amount > current_stars:
        await callback.answer(f"У вас недостаточно ⭐️. На балансе: {current_stars}", show_alert=True)
        return

    # создаём заявку
    req_id = create_withdraw_request(user_id, amount)
    update_stars(user_id, -amount)
    await callback.message.answer(f"✅ Заявка #{req_id} на вывод {amount} ⭐️ создана и ожидает рассмотрения.")
    await callback.answer()




# ---------- Обработка сообщений для админ-пароля и рассылки ----------
@router.message(lambda m: m.text and m.from_user.id not in admin_task_limit_editing)
async def handle_text_messages(message: types.Message):
    user_id = message.from_user.id
    admin_id = message.from_user.id
    text = (message.text or "").strip()

    # ----------------- Создание ручного задания админом (ранняя перехватка) -----------------
# ----------------- Создание ручного задания админом -----------------
    if user_id in admin_manual_task_creation:
        step = admin_manual_task_creation[user_id].get("step", 1)

        # Шаг 1: заголовок
        if step == 1:
            admin_manual_task_creation[user_id]["title"] = text
            admin_manual_task_creation[user_id]["step"] = 2
            await message.answer("🛠 Введите описание задания (что нужно сделать):")
            return

    # Шаг 2: описание
        if step == 2:
            admin_manual_task_creation[user_id]["description"] = text
            admin_manual_task_creation[user_id]["step"] = 3
            await message.answer("🛠 Введите ссылку (если есть). Просто вставьте текст ссылки:")
            return

    # Шаг 3: ссылка
        if step == 3:
            admin_manual_task_creation[user_id]["link"] = text
            admin_manual_task_creation[user_id]["step"] = 4
            await message.answer("🛠 Введите награду (⭐️) за ручное задание (например 2.5):")
            return

    # Шаг 4: награда
        if step == 4:
            try:
                stars = float(text)
                admin_manual_task_creation[user_id]["stars"] = stars
                admin_manual_task_creation[user_id]["step"] = 5
                await message.answer("🛠 Введите лимит выполнений (0 = без лимита):")
            except ValueError:
                await message.answer("❌ Неверный формат. Введите число (например 2.5):")
            return

    # Шаг 5: лимит
        if step == 5:
            try:
                max_sub = int(text)
                if max_sub < 0:
                    raise ValueError()
            except Exception:
                await message.answer("❌ Неверный формат. Введите целое число (0 = без лимита):")
                return

            st = admin_manual_task_creation[user_id]
            from database import add_manual_task_with_limit
            tid = add_manual_task_with_limit(
                st.get("title", "Без названия"),
                st.get("description", ""),
                st.get("link", ""),
                float(st.get("stars", 0)),
                max_sub
            )
            admin_manual_task_creation.pop(user_id, None)
            await message.answer(
                f"✅ Ручное задание добавлено: #{tid} — {st.get('title','Без названия')} — {st.get('stars')} ⭐️ (лимит: {max_sub})",
                reply_markup=admin_main_kb
            )
            return


    # ----------------- Добавление канала -----------------
    if user_id in admin_adding_channel:
        if not text.startswith("@"):
            await message.answer("❌ Канал должен начинаться с @")
            return
        if text in REQUIRED_CHANNELS:
            await message.answer("❌ Канал уже есть в списке")
            return

        REQUIRED_CHANNELS.append(text)
        admin_adding_channel.pop(user_id)
        await message.answer(f"✅ Канал {text} добавлен в список обязательных каналов.")
        return

    # ----------------- Активация купона пользователем -----------------
# ----------------- Активация купона пользователем -----------------
    state_coupon = referrals.get(user_id)
    if isinstance(state_coupon, dict) and state_coupon.get("await_coupon"):

# Сразу удаляем состояние, чтобы процесс купона завершился
        referrals.pop(user_id, None)
        code = text.strip()  
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, stars, max_uses, used_count FROM coupons WHERE code = ?", (code,))
            coupon = cur.fetchone()

            kb_main_menu = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Попробывать снова", callback_data="activate_coupon")],
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]
            ])
            if not coupon:
                await message.answer("❌ Купон недоступен или превышен лимит активаций.",reply_markup=kb_main_menu)
                return

            if coupon["used_count"] >= coupon["max_uses"]:
                await message.answer("❌ Купон недоступен или превышен лимит активаций.",reply_markup=kb_main_menu)
                return
            # Проверяем, использовал ли пользователь купон раньше
            cur.execute("SELECT 1 FROM coupon_uses WHERE user_id = ? AND coupon_id = ?", (user_id, coupon["id"]))
            if cur.fetchone():
                await message.answer("❌ Вы уже использовали этот купон.")
                return

        # Начисляем звёзды
            cur.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (coupon["stars"], user_id))
            cur.execute("UPDATE coupons SET used_count = used_count + 1 WHERE id = ?", (coupon["id"],))
            cur.execute("INSERT INTO coupon_uses (user_id, coupon_id) VALUES (?, ?)", (user_id, coupon["id"]))
            conn.commit()

        await message.answer(f"✅ Купон активирован! Вы получили {coupon['stars']} ⭐️",reply_markup=kb_main_menu)
        return


    # ----------------- Создание купона админом -----------------
    if user_id in admin_coupon_creation:
        step = admin_coupon_creation[user_id].get("step")

        if step == 1:
            # Ввод награды
            try:
                stars = float(text)
            except ValueError:
                await message.answer("❌ Введите число для награды:")
                return

            admin_coupon_creation[user_id]["stars"] = stars
            admin_coupon_creation[user_id]["step"] = 2
            await message.answer("Введите количество активаций купона:")
            return

        if step == 2:
            # Ввод количества активаций
            try:
                uses = int(text)
            except ValueError:
                await message.answer("❌ Введите число для количества активаций:")
                return

            stars = admin_coupon_creation[user_id]["stars"]
            code = generate_coupon_code()

            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO coupons (code, stars, max_uses, used_count) VALUES (?, ?, ?, 0)",
                    (code, stars, uses)
                )
                conn.commit()

            await message.answer(
                f"Купон: `{code}`\n"
                f"Награда: {stars} ⭐️\n"
                f"👥 Количество активаций: {uses}",
                parse_mode="Markdown"
            )
            print(f"Добавлен новый купон: {code}, награда: {stars} ⭐️, количество активаций: {uses}")
            del admin_coupon_creation[user_id]
            return


    # ----------------- Ввод админ-пароля -----------------
    if user_id in admin_auth_waiting:
        reset_user_states(user_id)    
        if text == ADMIN_PASSWORD:
            admin_auth_waiting.discard(user_id)
            admin_sessions.add(user_id)
            await message.answer("✅ Вход выполнен. Админ-панель:", reply_markup=admin_main_kb)
        else:
            admin_auth_waiting.discard(user_id)
            await message.answer("❌ Неверный пароль.")
        return

    # ----------------- Рассылка -----------------
    state = referrals.get(user_id)
    if isinstance(state, dict) and state.get("await_broadcast"):
        def get_username(uid: int) -> str | None:
            with get_conn() as conn:
                cur = conn.cursor()
                cur.execute("SELECT username FROM users WHERE id = ?", (uid,))
                row = cur.fetchone()
            if row:
                return row["username"]  # если включён row_factory = sqlite3.Row
            return None

        if not text:
            await message.answer("❌ Сообщение не может быть пустым.")
            print(f"{get_username(user_id)} пытается запустить рыссылку..")
            return

        await message.answer("⚡️ Начинаю рассылку... это может занять время ⚡️")
        print(f"{get_username(user_id)} запустил рыссылку: {text}")
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users")
            users = [row[0] for row in cur.fetchall()]

        sent_count = 0
        for uid in users:
            try:
                await message.bot.send_message(uid, text)
                sent_count += 1
                await asyncio.sleep(0.05)
            except:
                continue

        await message.answer(f"✅ Рассылка завершена! Сообщение отправлено {sent_count} пользователям.")
        referrals.pop(user_id, None)
        return


    admin_id = message.from_user.id
    if admin_id not in admin_task_creation:
        return  # это не процесс создания задания

    state = admin_task_creation[admin_id]

    if state["step"] == 1:
        # Получаем канал
        channel = message.text.strip()
        state["channel"] = channel
        state["step"] = 2
        await message.answer("Введите награду за выполнение задания (⭐️):")
        return

    if state["step"] == 2:
        try:
            stars = float(message.text.strip())
        except ValueError:
            await message.answer("❌ Неверный формат. Введите число для награды:")
            return

        state["stars"] = stars
        state["step"] = 3
        await message.answer("Введите лимит выполнений (0 = без лимита):")
        return

    if state["step"] == 3:
        try:
            max_completions = int(message.text.strip())
        except ValueError:
            await message.answer("❌ Введите число для лимита:")
            return

        state["max_completions"] = max_completions

        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO tasks (channel, stars, max_completions, current_completions) VALUES (?, ?, ?, 0)",
                (state["channel"], state["stars"], state["max_completions"])
            )

            conn.commit()

        await message.answer(
            f"✅ Задание добавлено:\n{state['channel']} — {state['stars']} ⭐️ (лимит: {state['max_completions'] or '∞'})",
            reply_markup=admin_main_kb
        )
        del admin_task_creation[admin_id]

    # ----------------- Редактирование награды задания -----------------
    if user_id in admin_task_editing:
        try:
            new_stars = float(text)
        except ValueError:
            await message.answer("❌ Введите число для награды.")
            return

        task_id = admin_task_editing[user_id]["task_id"]
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute("UPDATE tasks SET stars = ? WHERE id = ?", (new_stars, task_id))
            conn.commit()

        await update_admin_tasks_list(message)  # показать обновлённый список заданий
        admin_task_editing.pop(user_id)
        return

# ----------------- Admin panel callbacks -----------------
@router.callback_query(F.data == "admin_panel")
async def admin_panel_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    referrals.pop(user_id, None)  # убираем ожидание купона
    if user_id in admin_sessions:
        await callback.message.edit_text("✅ Вы в админ-панели.", reply_markup=admin_main_kb)
        await callback.answer()
        return

    admin_auth_waiting.add(user_id)
    await callback.message.answer("Введите пароль администратора:", reply_markup=backs_menu )
    await callback.answer()

# ----------------- Admin: список заявок -----------------
@router.callback_query(F.data == "admin_requests")
async def admin_requests_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    requests = get_withdraw_requests(status="pending")
    if not requests:
        await callback.message.edit_text("📋 Заявок нет.", reply_markup=admin_main_kb)
        await callback.answer()
        return

    text_lines = ["📋 Список заявок (pending):"]
    kb = InlineKeyboardBuilder()

    for r in requests:
        # Если get_withdraw_requests возвращает кортеж
        req_id = r[0]
        uid = r[1]
        username = r[2] or f"User {uid}"
        stars = r[3]
        created_at = r[5]  # уточни индекс по своей БД
        text_lines.append(f"#{req_id} — @{username} — {stars} ⭐️ — {created_at}")
        kb.button(text=f"Открыть #{req_id}", callback_data=f"admin_view_{req_id}")

    kb.button(text="⬅️", callback_data="back_to_menu")
    markup = kb.as_markup()
    new_text = "\n".join(text_lines)

    # Проверяем, чтобы не вызывать edit_text с тем же текстом
    if callback.message.text != new_text:
        try:
            await callback.message.edit_text(new_text, reply_markup=markup)
        except aiogram.exceptions.TelegramBadRequest as e:
            if "message is not modified" not in str(e):
                raise


    await callback.answer()


# ----------------- Admin: просмотр заявки -----------------
@router.callback_query(F.data.startswith("admin_view_"))
async def admin_view_request_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    try:
        req_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return

    req = get_withdraw_request_by_id(req_id)
    if not req:
        await callback.answer("Заявка не найдена.")
        return

    # Если req — словарь, всё ок
    uid = req['user_id']
    username = req['username'] or f"User {uid}"
    stars = req['stars']
    status = req['status']
    created_at = req['created_at']

    text = (
        f"Заявка #{req_id}\n"
        f"Пользователь: @{username} (ID {uid})\n"
        f"Сумма: {stars} ⭐️\n"
        f"Статус: {status}\n"
        f"Создана: {created_at}"
    )

    await callback.message.edit_text(text, reply_markup=admin_request_actions_kb(req_id))
    await callback.answer()


# ----------------- Admin: принять заявку -----------------
@router.callback_query(F.data.startswith("req_") & F.data.endswith("_approve"))
async def admin_approve_cb(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if user_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    try:
        req_id = int(callback.data.split("_")[1])
    except:
        await callback.answer()
        return

    req = get_withdraw_request_by_id(req_id)
    if not req or req['status'] != "pending":
        await callback.answer("Заявка уже обработана или не найдена.")
        return

    update_withdraw_request(req_id, "approved")
    uid = req['user_id']
    stars = req['stars']

    try:
        await bot.send_message(uid, f"✅ Ваша заявка на вывод {stars} ⭐️ принята.")
        print(f"Заявка {user_id} на выплату {stars} ⭐️ была одобрена")
    except Exception as e:
        print(f"Ошибка уведомления пользователя: {e}")

    await callback.message.edit_text(f"Заявка #{req_id} принята.", reply_markup=admin_main_kb)
    await callback.answer("Заявка принята.")


# ----------------- Admin: отклонить заявку -----------------
@router.callback_query(F.data.startswith("req_") & F.data.endswith("_reject"))
async def admin_reject_cb(callback: types.CallbackQuery, bot: Bot):
    user_id = callback.from_user.id
    if user_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    try:
        req_id = int(callback.data.split("_")[1])
    except:
        await callback.answer()
        return

    req = get_withdraw_request_by_id(req_id)
    if not req or req['status'] != "pending":
        await callback.answer("Заявка уже обработана или не найдена.")
        return

    uid = req['user_id']
    stars = req['stars']
    update_stars(uid, float(stars))  # вернуть звезды пользователю
    update_withdraw_request(req_id, "rejected")

    try:
        await bot.send_message(uid, f"❌ Ваша заявка на вывод на {stars} ⭐️ отклонена.")
        print(f"Заявка {user_id} на выплату {stars} ⭐️ была отклонена")

    except Exception as e:
        print(f"Ошибка уведомления пользователя: {e}")

    await callback.message.edit_text(f"Заявка #{req_id} отклонена.", reply_markup=admin_main_kb)
    await callback.answer("Заявка отклонена.")




@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    referrals[user_id] = {"await_broadcast": True}
    await callback.message.answer("Введите текст сообщения для рассылки всем пользователям:")
    await callback.answer()


# ----------------- Admin: статистика пользователей -----------------
@router.callback_query(F.data == "admin_users_stats")
async def admin_users_stats_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    today_iso = datetime.utcnow().date().isoformat()

    with get_conn() as conn:
        cur = conn.cursor()
        # Всего зарегистрированных
        cur.execute("SELECT COUNT(*) as total FROM users")
        total_users = cur.fetchone()["total"]

        # Зарегистрировавшиеся сегодня
        cur.execute("SELECT COUNT(*) as today FROM users WHERE date(created_at) = ?", (today_iso,))
        today_users = cur.fetchone()["today"]

        # Всего звезд на балансах
        cur.execute("SELECT SUM(stars) as total_stars FROM users")
        total_stars = cur.fetchone()["total_stars"] or 0

    text = (
        f"📊 Статистика пользователей:\n\n"
        f"👥 Всего зарегистрировано: {total_users}\n"
        f"📅 Сегодня зарегистрировались: {today_users}\n"
        f"⭐️ Всего звезд на балансах: {total_stars}"
    )

    await callback.message.edit_text(text, reply_markup=admin_main_kb)
    await callback.answer()

USERS_PER_PAGE = 20

@router.callback_query(F.data.startswith("admin_users"))
async def admin_users_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    try:
        page = int(callback.data.split("_")[-1])
    except:
        page = 1

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, full_name FROM users ORDER BY id ASC")
        users = cur.fetchall()

    if not users:
        await callback.message.edit_text("👥 Нет зарегистрированных пользователей.", reply_markup=admin_main_kb)
        await callback.answer()
        return

    start = (page - 1) * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    users_page = users[start:end]

    text_lines = [f"👥 Список участников (страница {page}/{(len(users)-1)//USERS_PER_PAGE+1}):"]
    kb = InlineKeyboardBuilder()

    for u in users_page:
        uid = u["id"]
        username = u["username"] or f"User {uid}"
        text_lines.append(f"@{username}")
        kb.button(text=f"@{username}", callback_data=f"admin_user_{uid}")

    nav_buttons = []
    if start > 0:
        nav_buttons.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin_users_{page-1}"))
    if end < len(users):
        nav_buttons.append(InlineKeyboardButton(text="➡️ Вперед", callback_data=f"admin_users_{page+1}"))

    if nav_buttons:
        kb.row(*nav_buttons)

    kb.button(text="⬅️ В меню", callback_data="back_to_menu")

    await safe_edit_text(callback.message, "\n".join(text_lines), kb.as_markup())
    await callback.answer()


# Callback для профиля конкретного пользователя
@router.callback_query(F.data.startswith("admin_user_"))
async def admin_user_profile_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    try:
        user_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return

    user = get_user(user_id)
    if not user:
        await callback.answer("Пользователь не найден.")
        return

    info = get_user_info(user)
# 🟢 Считаем только тех, кто предоставил номер телефона (завершил основной этап)
    total_invites = get_conn().cursor().execute(
        "SELECT COUNT(*) FROM users WHERE referrer_id = ? AND phone IS NOT NULL", (user_id,)
    ).fetchone()[0]
    text = (
        f"👤 Профиль @{info['username'] or 'Без имени'}\n"
        f"ID: {info['user_id']}\n"
        f"📞 Телефон: {info['phone'] or 'Не указан'}\n"
        f"📅 Зарегистрирован: {info['created_at']}\n"
        f"Баланс звезд: {info['stars']:.2f} ⭐️\n"
        f"Выполнено заданий: {info['tasks_done']} 🎯\n"
        f"Пригласил: {total_invites} пользователей 👥 "
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить участника", callback_data=f"admin_delete_user_{user_id}")],
        [InlineKeyboardButton(text="⬅️ Назад к участникам", callback_data="admin_users")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]
    ])

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# Словарь для хранения состояния админа при создании задания
admin_task_creation = {}

@router.callback_query(lambda c: c.data.startswith("admin_delete_user_"))
async def admin_delete_user_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.", show_alert=True)
        return

    try:
        user_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer("❌ Ошибка: некорректный пользователь.", show_alert=True)
        return

    delete_user(user_id)
    await callback.answer("✅ Пользователь удалён и может зарегистрироваться заново.")

    # Обновляем список пользователей
    await admin_users_cb(callback)


@router.callback_query(F.data == "admin_add_task")
async def admin_add_task_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    admin_task_creation[admin_id] = {"step": 1}
    await callback.message.answer("Введите ссылку на канал для задания (например https://t.me/):")
    await callback.answer()

async def safe_edit_text(message_or_callback, text: str, reply_markup: InlineKeyboardMarkup | None = None):
    if isinstance(message_or_callback, types.CallbackQuery):
        message = message_or_callback.message
    else:
        message = message_or_callback

    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except aiogram.exceptions.TelegramBadRequest as e:
        error_text = str(e)
        if "message is not modified" in error_text:
            return
        elif "message to edit not found" in error_text or "can't be edited" in error_text:
            # Отправляем новое сообщение, если редактировать нельзя
            await message.answer(text, reply_markup=reply_markup)
        else:
            raise


@router.callback_query(F.data == "admin_tasks_list")
async def admin_tasks_list_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, channel, stars, max_completions, current_completions FROM tasks")
        tasks = cur.fetchall()

    if not tasks:
        await safe_edit_text(callback.message, "🎯 Заданий нет.", admin_main_kb)
        await callback.answer()
        return

    text_lines = ["🎯 Список заданий:"]
    kb = InlineKeyboardBuilder()
    for t in tasks:
        task_id = t["id"]
        channel = t["channel"]
        stars = t["stars"]
        max_c = t["max_completions"] if t["max_completions"] not in (None, 0) else '∞'
        curr_c = t["current_completions"] or 0
        text_lines.append(
        f"#{t['id']} — {t['channel']} — {t['stars']} ⭐️ (лимит: {max_c or '∞'}, выполнено: {curr_c})"
        )
        kb.button(text=f"Открыть #{task_id}", callback_data=f"admin_task_{task_id}")

    kb.button(text="⬅️ Назад в меню", callback_data="back_to_menu")
    await safe_edit_text(callback.message, "\n".join(text_lines), kb.as_markup())
    await callback.answer()


def admin_task_actions_kb(task_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить награду", callback_data=f"admin_task_edit_{task_id}")],
        [InlineKeyboardButton(text="✏️ Изменить лимит", callback_data=f"admin_task_limit_{task_id}")],
        [InlineKeyboardButton(text="🗑 Удалить задание", callback_data=f"admin_task_delete_{task_id}")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="admin_tasks_list")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]
    ])

@router.callback_query(lambda c: bool(re.match(r"^admin_task_\d+$", (c.data or ""))))
async def admin_task_view_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    try:
        task_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, channel, stars, max_completions, current_completions FROM tasks WHERE id = ?", (task_id,))
        task = cur.fetchone()

    if not task:
        await callback.answer("Задание не найдено.")
        return

    max_c = task["max_completions"] if "max_completions" in task.keys() else 0
    curr_c = task["current_completions"] if "current_completions" in task.keys() else 0

    text = (
        f"🎯 Задание #{task['id']}\n"
        f"Канал: {task['channel']}\n"
        f"Награда: {task['stars']} ⭐️\n"
        f"Лимит: {max_c or '∞'}\n"
        f"Выполнено: {curr_c}"
    )
    await safe_edit_text(callback, text, admin_task_actions_kb(task['id']))
    await callback.answer()


admin_task_editing = {}  # словарь для хранения состояния редактирования

@router.callback_query(F.data.startswith("admin_task_edit_"))
async def admin_task_edit_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    try:
        task_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return

    admin_task_editing[admin_id] = {"task_id": task_id}
    await callback.message.answer("Введите новую награду (⭐️) для этого задания:")
    await callback.answer()

@router.callback_query(F.data.startswith("admin_task_delete_"))
async def admin_task_delete_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    task_id = int(callback.data.split("_")[-1])
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()

    await callback.answer("🗑 Задание удалено.")

    # Обновляем список заданий
    await update_admin_tasks_list(callback)  # <-- передаём callback, а не message


async def update_admin_tasks_list(message_or_callback):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, channel, stars, max_completions, current_completions FROM tasks ORDER BY id DESC")
        tasks = cur.fetchall()

    if not tasks:
        await safe_edit_text(message_or_callback, "🎯 Заданий нет.", admin_main_kb)
        return

    text_lines = ["🎯 Список заданий:"]
    kb = InlineKeyboardBuilder()
    for t in tasks:
        task_id = t["id"]
        channel = t["channel"]
        stars = t["stars"]
        text_lines.append(f"#{task_id} — {channel} — {stars} ⭐️ (лимит: {t['max_completions'] or '∞'}, выполнено: {t['current_completions']})")
        kb.button(text=f"Открыть #{task_id}", callback_data=f"admin_task_{task_id}")

    kb.button(text="⬅️ Назад в меню", callback_data="back_to_menu")
    await safe_edit_text(message_or_callback, "\n".join(text_lines), kb.as_markup())

@router.callback_query(F.data == "admin_channels")
async def admin_channels_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return

    text = "📌 Обязательные каналы для подписки:\n" + "\n".join(REQUIRED_CHANNELS)

    kb = InlineKeyboardMarkup(inline_keyboard=[])  # пустой список кнопок
    for ch in REQUIRED_CHANNELS:
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"❌ {ch}", callback_data=f"remove_channel_{ch[1:]}")
        ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")
    ])

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "add_channel")
async def add_channel_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return

    admin_adding_channel[admin_id] = True
    await callback.message.answer("Введите @username канала для добавления:")
    await callback.answer()
@router.callback_query(lambda c: c.data.startswith("remove_channel_"))
async def remove_channel_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return

    ch = "@" + callback.data.split("_")[-1]
    if ch in REQUIRED_CHANNELS:
        REQUIRED_CHANNELS.remove(ch)
        await callback.answer(f"✅ Канал {ch} удалён из списка.")
        # Обновляем список каналов
        await admin_channels_cb(callback)



def submission_actions_kb(submission_id: int):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"submission_approve_{submission_id}")],
        [InlineKeyboardButton(text="❌ Отклонить", callback_data=f"submission_reject_{submission_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_task_submissions")]
    ])

@router.callback_query(F.data.startswith("admin_submission_"))
async def admin_submission_view_cb(callback: types.CallbackQuery):
    sid = int(callback.data.split("_")[-1])

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ts.id, ts.user_id, ts.task_id, u.username, t.channel, t.stars
            FROM task_submissions ts
            JOIN users u ON ts.user_id = u.id
            LEFT JOIN tasks t ON ts.task_id = t.id
            WHERE ts.id = ?
        """, (sid,))
        s = cur.fetchone()

    if not s:
        await callback.answer("Заявка не найдена или задание удалено.", show_alert=True)
        return

    channel = s["channel"] if s["channel"] else "Задание удалено"
    stars = s["stars"] if s["stars"] else 0

    text = (
        f"📥 Заявка #{s['id']}\n"
        f"👤 Пользователь: @{s['username']}\n"
        f"🎯 Задание: {channel}\n"
        f"⭐️ Награда: {stars}"
    )
    await safe_edit_text(callback.message, text, submission_actions_kb(s['id']))
    await callback.answer()

# ----------------- Админ: список заявок -----------------
@router.callback_query(F.data == "admin_task_submissions")
async def admin_task_submissions_cb(callback: types.CallbackQuery):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ts.id, ts.user_id, ts.task_id, u.username, t.channel, t.stars
            FROM task_submissions ts
            JOIN users u ON ts.user_id = u.id
            LEFT JOIN tasks t ON ts.task_id = t.id
            WHERE ts.status = 'pending'
            ORDER BY ts.created_at ASC
        """)
        submissions = cur.fetchall()

    if not submissions:
        await callback.message.edit_text("📭 Нет заявок на проверку.", reply_markup=admin_main_kb)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    text_lines = ["📥 Заявки на проверку:"]
    for s in submissions:  # или manual_tasks, смотря что у тебя в выборке
        stars = s['stars']
        channel = s.get('channel') or s.get('link') or "—"

        max_uses = s.get("max_uses") or 0
        current_uses = s.get("current_uses") or 0

        # Скрываем задание, если лимит достигнут
        if max_uses > 0 and current_uses >= max_uses:
            continue

        text_lines.append(f"#{s['id']} — @{s['username']} — {channel} ({stars} ⭐️)")
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"Открыть #{s['id']}", callback_data=f"admin_submission_{s['id']}")
        ])

    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_menu")])
    await safe_edit_text(callback.message, "\n".join(text_lines), kb)
    await callback.answer()
# Показать задания с кнопками под постом
@router.callback_query(F.data == "tasks")
async def tasks_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id

    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, callback.message)

    if not data.get("skip"):
        # ❌ нет подписки → показываем проверку
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        await callback.answer()
        return




    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, channel, stars, max_completions, current_completions FROM tasks ORDER BY id DESC")
        tasks = cur.fetchall()

        kb_buttons = []

            # ===== Фиксированные задания =====
        for task in FIXED_TASKS:
            task_id = task["id"]

                # проверяем, выполнял ли уже юзер
            cur.execute("""
                SELECT status FROM task_submissions
                WHERE user_id = ? AND task_id = ?
            """, (user_id, task_id))
            row = cur.fetchone()
            if row and row["status"] == "approved":
                continue

            kb_buttons.append([
                InlineKeyboardButton(
                    text=f"✅ ПОДПИШИСЬ + {task['stars']} ⭐️",
                    url=task["url"]
                )
            ])

            # ===== Динамические из базы =====
        for task in tasks:
            task_id = task["id"]
            stars = task["stars"]
            channel = task["channel"]

            max_c = task["max_completions"] or 0
            curr_c = task["current_completions"] or 0
            if max_c > 0 and curr_c >= max_c:
                continue

            cur.execute("""
                SELECT status FROM task_submissions
                WHERE user_id = ? AND task_id = ?
            """, (user_id, task_id))
            row = cur.fetchone()
            if row and row["status"] == "approved":
                continue

            url = channel if channel.startswith("http") else f"https://t.me/{channel.lstrip('@')}"

            kb_buttons.append([
                InlineKeyboardButton(
                    text=f"✅ ПОДПИШИСЬ + {stars} ⭐️",
                    url=url
                )
            ])

            # ===== Если вообще ничего нет =====
        if not kb_buttons:
            await callback.message.answer(
                "🎯 Заданий пока нет.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Добавить свое задание", url="t.me/deluxesl")],
                        [InlineKeyboardButton(text="🛠 Ручные задания", callback_data="manual_tasks_list")],
                        [InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")]
                    ]
                )
            )
            await callback.answer()
            return

            # ===== Дополнительные кнопки =====
        kb_buttons.append([InlineKeyboardButton(text="🛠 Ручные задания", callback_data="manual_tasks_list")])
        kb_buttons.append([InlineKeyboardButton(text="Добавить свое задание", url="t.me/deluxesl")])
        kb_buttons.append([InlineKeyboardButton(text="Проверить подписки", callback_data="check_all_tasks")])
        kb_buttons.append([InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

        await callback.message.answer("🎯 Доступные задания:", reply_markup=kb)

    await callback.answer()





# Админ одобряет заявку — здесь начисляем звёзды
@router.callback_query(F.data.startswith("submission_approve_"))
async def submission_approve_cb(callback: types.CallbackQuery, bot: Bot):
    sid = int(callback.data.split("_")[-1])

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id, task_id FROM task_submissions WHERE id = ? AND status = 'pending'", (sid,))
        s = cur.fetchone()
        if not s:
            await callback.answer("❌ Заявка не найдена или уже обработана.")
            return

        user_id, task_id = s["user_id"], s["task_id"]

        # Получаем награду
        cur.execute("SELECT stars FROM tasks WHERE id = ?", (task_id,))
        stars = cur.fetchone()["stars"]

        # Начисляем звезды
        cur.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (stars, user_id))
        cur.execute("UPDATE task_submissions SET status = 'approved' WHERE id = ?", (sid,))
        conn.commit()

    try:
        await bot.send_message(user_id, f"✅ Ваша заявка #{sid} одобрена! Вы получили {stars} ⭐️")
    except:
        pass

    await callback.message.edit_text(f"✅ Заявка #{sid} одобрена.", reply_markup=admin_main_kb)
    await callback.answer()


# Админ отклоняет заявку
@router.callback_query(F.data.startswith("submission_reject_"))
async def submission_reject_cb(callback: types.CallbackQuery, bot: Bot):
    sid = int(callback.data.split("_")[-1])

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT user_id FROM task_submissions WHERE id = ? AND status = 'pending'", (sid,))
        s = cur.fetchone()
        if not s:
            await callback.answer("❌ Заявка не найдена или уже обработана.")
            return

        user_id = s["user_id"]

        cur.execute("UPDATE task_submissions SET status = 'rejected' WHERE id = ?", (sid,))
        conn.commit()

    try:
        await bot.send_message(user_id, f"❌ Ваша заявка #{sid} отклонена.")
    except:
        pass

    await callback.message.edit_text(f"❌ Заявка #{sid} отклонена.", reply_markup=admin_main_kb)
    await callback.answer()

def generate_coupon_code(length=12):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

admin_coupon_creation = {}

@router.callback_query(F.data == "admin_add_coupon")
async def admin_add_coupon_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return

    admin_coupon_creation[admin_id] = {"step": 1}
    await callback.message.answer("Введите количество ⭐️, которое будет начисляться при активации купона:")
    await callback.answer()


@router.message(lambda m: m.from_user.id in admin_coupon_creation and admin_coupon_creation[m.from_user.id]["step"] == 1)
async def process_coupon_stars(message: types.Message):
    admin_id = message.from_user.id
    try:
        stars = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число для награды:")
        return

    admin_coupon_creation[admin_id]["stars"] = stars
    admin_coupon_creation[admin_id]["step"] = 2
    await message.answer("Введите количество активаций купона:")



@router.callback_query(F.data == "activate_coupon")
async def activate_coupon_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    referrals[user_id] = {"await_coupon": True}
    await callback.message.answer("Введите купон для активации:", reply_markup=backs_menu)
    await callback.answer()


@router.callback_query(F.data == "admin_coupons")
async def admin_coupons_cb(callback: types.CallbackQuery):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, code, stars, max_uses, used_count,
                   (max_uses - used_count) as remaining_uses
            FROM coupons ORDER BY id DESC
        """)
        coupons = cur.fetchall()

    if not coupons:
        await callback.message.edit_text("📃 Купонов нет.", reply_markup=admin_main_kb)
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    text_lines = ["📃 Список купонов:"]

    for c in coupons:
        text_lines.append(
            f"{c['code']} — ⭐️ {c['stars']} — Осталось активаций: {c['remaining_uses']}"
        )
        kb.inline_keyboard.append([
            InlineKeyboardButton(text=f"❌ Удалить {c['code']}", callback_data=f"remove_coupon_{c['id']}")
        ])

    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")])
    await callback.message.edit_text("\n".join(text_lines), reply_markup=kb)


@router.callback_query(lambda c: c.data.startswith("remove_coupon_"))
async def remove_coupon_cb(callback: types.CallbackQuery):
    coupon_id = int(callback.data.split("_")[-1])
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM coupons WHERE id = ?", (coupon_id,))
        conn.commit()
    await callback.answer("✅ Купон удалён.")
    await admin_coupons_cb(callback)

@router.callback_query(F.data == "check_all_tasks")
async def check_all_tasks_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    approved_count = 0
    total_stars = 0

    with get_conn() as conn:
        cur = conn.cursor()

        # === Получаем все задания из базы ===
        cur.execute("SELECT id, channel, stars, max_completions, current_completions FROM tasks ORDER BY id DESC")
        tasks = cur.fetchall()

        # === Проверяем FIXED_TASKS ===
        for task in FIXED_TASKS:
            task_id = task["id"]
            stars = task["stars"]
            chat_id = task["check_id"]

            cur.execute("""
                SELECT status FROM task_submissions
                WHERE user_id = ? AND task_id = ?
            """, (user_id, task_id))
            row = cur.fetchone()
            if row and row["status"] == "approved":
                continue  # уже выполнено

            try:
                member = await callback.bot.get_chat_member(chat_id, user_id)
            except Exception as e:
                print(f"Ошибка проверки FIXED_TASK {task_id}: {e}")
                continue

            if member.status in ["member", "administrator", "creator"]:
                update_stars(user_id, stars, reason=f"Фиксированное задание #{task_id}", cur=cur)
                cur.execute("""
                    INSERT INTO task_submissions (user_id, task_id, status)
                    VALUES (?, ?, 'approved')
                """, (user_id, task_id))
                approved_count += 1
                total_stars += stars

        # === Проверяем задания из базы ===
        for task in tasks:
            task_id = task["id"]
            stars = task["stars"]
            channel = task["channel"]

            max_c = task["max_completions"] or 0
            curr_c = task["current_completions"] or 0
            if max_c > 0 and curr_c >= max_c:
                continue  # лимит исчерпан

            cur.execute("""
                SELECT status FROM task_submissions
                WHERE user_id = ? AND task_id = ?
            """, (user_id, task_id))
            row = cur.fetchone()
            if row and row["status"] == "approved":
                continue  # уже выполнено

            try:
                # если в channel указан @username или ссылка
                if channel.startswith("http"):
                    chat = await callback.bot.get_chat(channel)
                else:
                    chat = await callback.bot.get_chat(f"@{channel.lstrip('@')}")

                member = await callback.bot.get_chat_member(chat.id, user_id)
            except Exception as e:
                print(f"Ошибка проверки TASK {task_id}: {e}")
                continue

            if member.status in ["member", "administrator", "creator"]:
                update_stars(user_id, stars, reason=f"Задание #{task_id}", cur=cur)
                cur.execute("""
                    INSERT INTO task_submissions (user_id, task_id, status)
                    VALUES (?, ?, 'approved')
                """, (user_id, task_id))
                approved_count += 1
                total_stars += stars

                # увеличиваем счётчик выполнений
                cur.execute("""
                    UPDATE tasks
                    SET current_completions = current_completions + 1
                    WHERE id = ?
                """, (task_id,))

        conn.commit()

    # === Сообщение пользователю ===
    if total_stars == 0:
        await callback.message.answer("❌ Новых выполненных заданий не найдено.")
    else:
        await callback.message.answer(f"✅ Выполнено: {approved_count} заданий\n💎 Начислено: +{total_stars} ⭐️")

    await callback.answer()





admin_task_limit_editing = {}

@router.callback_query(F.data.startswith("admin_task_limit_"))
async def admin_task_limit_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    task_id = int(callback.data.split("_")[-1])
    admin_task_limit_editing[admin_id] = {"task_id": task_id}
    await callback.message.answer("Введите новый лимит выполнений (0 = без лимита):")
    await callback.answer()


@router.message(lambda m: m.from_user.id in admin_task_limit_editing)
async def handle_limit_edit(message: types.Message):
    user_id = message.from_user.id
    task_id = admin_task_limit_editing[user_id]["task_id"]

    try:
        new_limit = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число для лимита.")
        return

    if new_limit < 0:
        await message.answer("❌ Лимит не может быть отрицательным.")
        return

    from database import update_task_limit
    update_task_limit(task_id, new_limit)

    # Обновляем список заданий в админ-панели и уведомляем администратора
    try:
        await update_admin_tasks_list(message)
    except Exception:
        pass

    await message.answer(f"✅ Лимит задания #{task_id} изменён на {new_limit or '∞'}")
    del admin_task_limit_editing[user_id]




# ----------------- Admin: Manual Tasks (Ручные задания) -----------------
@router.callback_query(F.data == "admin_manual_tasks")
async def admin_manual_tasks_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return

    # <-- Заменили get_manual_tasks на get_all_manual_tasks
    from database import get_all_manual_tasks
    tasks = get_all_manual_tasks()
    if not tasks:
        kb_empty = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ручное задание", callback_data="admin_add_manual_task")],
            [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]
        ])
        await safe_edit_text(callback, "🛠 Ручных заданий пока нет.", kb_empty)
        await callback.answer()
        return

    text_lines = ["🛠 Список ручных заданий:"]
    kb = InlineKeyboardBuilder()

    for t in tasks:
        max_u = int(t.get("max_uses") or 0)
        curr_u = int(t.get("current_uses") or 0)

        max_text = max_u if max_u != 0 else "∞"
        exhausted = (max_u > 0 and curr_u >= max_u)
        status = " — лимит исчерпан" if exhausted else ""

        text_lines.append(
            f"#{t['id']} — {t.get('title','Без названия')} — {t.get('stars',0)} ⭐️ "
            f"(лимит: {max_text}, выполнено: {curr_u}){status}"
        )
        kb.button(text=f"Открыть #{t['id']}", callback_data=f"admin_manual_{t['id']}")

    kb.button(text="➕ Добавить ручное задание", callback_data="admin_add_manual_task")
    kb.button(text="⬅️ Назад в меню", callback_data="back_to_menu")
    await safe_edit_text(callback, "\n".join(text_lines), kb.as_markup())
    await callback.answer()

@router.callback_query(F.data == "admin_add_manual_task")
async def admin_add_manual_task_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return
    admin_manual_task_creation[admin_id] = {"step": 1}
    await callback.message.answer("Введите заголовок для ручного задания:")
    await callback.answer()

@router.callback_query(lambda c: c.data and re.match(r"^admin_manual_\d+$", c.data))
async def admin_manual_view_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return
    try:
        task_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return

    from database import get_manual_task, count_total_submissions
    task = get_manual_task(task_id)
    if not task:
        await callback.answer("Задание не найдено.")
        return

    # считаем лимиты (берём из max_uses / current_uses)
    max_lim = int(task.get("max_uses") or 0)
    curr = int(task.get("current_uses") or 0)

    if max_lim > 0:
        left = max_lim - curr
        if left < 0:
            left = 0
        lim_text = f"Лимит: {curr}/{max_lim} (осталось: {left})"
    else:
        lim_text = "Лимит: без ограничений"

    text = (
        f"🛠 Ручное задание #{task['id']}\n"
        f"Название: {task.get('title')}\n\n"
        f"Описание:\n{task.get('description')}\n\n"
        f"Ссылка: {task.get('link')}\n"
        f"Награда: {task.get('stars')} ⭐️\n"
        f"{lim_text}\n\n"
        f"Создано: {task.get('created_at')}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✏️ Изменить лимит", callback_data=f"manual_limit:{task['id']}"),
            InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin_manual_delete_{task['id']}")
        ],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_manual_tasks")]
    ])
    await safe_edit_text(callback, text, kb)
    await callback.answer()

@router.callback_query(F.data.startswith("admin_manual_delete_"))
async def admin_manual_delete_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.", show_alert=True)
        return

    try:
        tid = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("❌ Ошибка: неверный ID задания.", show_alert=True)
        return

    from database import delete_manual_task
    delete_manual_task(tid)

    await callback.answer("✅ Ручное задание удалено.")
    # обновляем список после удаления
    await admin_manual_tasks_cb(callback)

@router.callback_query(F.data == "manual_tasks_list")
async def manual_tasks_list_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    from database import get_manual_tasks
    tasks = get_manual_tasks()
    if not tasks:
        await callback.message.edit_text(
            "🛠 Ручных заданий нет.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Добавить свое задание", url="t.me/deluxesl")],
                    [InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")]
                ]
            )
        )
        await callback.answer()
        return

    text_lines = [f"🛠 Ручные задания: \n"]
    kb = InlineKeyboardBuilder()
    from database import count_total_submissions, get_user_submission_for_task

    for t in tasks:
        task_id = t["id"]
        stars = t["stars"]

        # проверка лимита
        try:
            max_lim = int(t.get("max_submissions") or 0)
        except Exception:
            max_lim = 0
        total = count_total_submissions(task_id)
        if max_lim > 0 and total >= max_lim:
            continue  # лимит исчерпан → не показываем задание

        # проверка заявок пользователя
        usr_sub = get_user_submission_for_task(user_id, task_id)
        if usr_sub and usr_sub["status"] in ("pending", "approved"):
            continue  # если заявка на проверке или уже одобрена → задание скрываем

        # если можно показывать
        text_lines.append(f"#{task_id} - {t.get('title','Без названия')} — {stars} ⭐️")
        kb.button(text=f"Открыть #{task_id}", callback_data=f"manual_open_{task_id}")

    # 🔥 Если кроме заголовка ничего не добавилось → заданий нет
    if len(text_lines) == 1:
        await callback.message.edit_text("🛠 Ручных заданий нет.", reply_markup=backs_menu)
        await callback.answer()
        return

    kb.button(text="⬅️", callback_data="back_to_menu")
    await safe_edit_text(callback, "\n".join(text_lines), kb.as_markup())
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("manual_open_"))
async def manual_open_cb(callback: types.CallbackQuery):
    from database import get_manual_task, get_user_submission_for_task
    try:
        task_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return
    from database import get_manual_task
    t = get_manual_task(task_id)
    if not t:
        await callback.answer("Задание не найдено.")
        return

    text = (
        f"🛠 {t.get('title')}\n\n"
        f"{t.get('description')}\n\n"
        f"Ссылка: {t.get('link')}\n\n"
        f"Награда: {t.get('stars')} ⭐️"
    )

    usr_sub = get_user_submission_for_task(callback.from_user.id, task_id)
    if usr_sub:
        text += f"\n\nВаш статус заявки: {usr_sub['status']}"
    kb_buttons = []
    if not usr_sub or usr_sub["status"] == "rejected":
        kb_buttons.append([InlineKeyboardButton(text="Начать выполнение", callback_data=f"manual_start_{task_id}")])
    kb_buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="manual_tasks_list")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)

    await safe_edit_text(callback, text, kb)
    await callback.answer()

from aiogram.fsm.context import FSMContext
from database import get_manual_task
@router.callback_query(F.data.startswith("cancel_manual_upload_"))
async def cancel_manual_upload_cb(callback: types.CallbackQuery, state: FSMContext):
    task_id = int(callback.data.split("_")[-1])
    
    # ❌ убираем пользователя из referrals, чтобы бот перестал ждать фото
    referrals.pop(callback.from_user.id, None)

    from database import get_manual_task
    task = get_manual_task(task_id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Отправить скриншот", callback_data=f"manual_start_{task_id}")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="manual_tasks_list")]
    ])

    if task:
        await callback.message.edit_text(
            f"🛠 {task['title']}\n\n{task.get('description','')}\n\nНаграда: {task['stars']} ⭐️",
            reply_markup=kb
        )
    else:
        await callback.message.edit_text("❌ Задание не найдено.")

    await callback.answer("❌ Отправка скриншота отменена")



@router.callback_query(lambda c: c.data and c.data.startswith("manual_start_"))
async def manual_start_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        task_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return
    referrals[user_id] = {"await_manual_screenshot": True, "manual_task_id": task_id}
    kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_manual_upload_{task_id}")]
    ])
    sent_msg = await callback.message.edit_text(
    "📸 Пришлите скриншот выполнения задания.\n"
    "После успешной отправки скриншота задание уйдёт на проверку.",
    reply_markup=kb
)
    referrals[user_id]["request_msg_id"] = sent_msg.message_id
    await callback.answer("Пришлите скриншот")


@router.message(F.photo)
async def handle_manual_photo(message: types.Message):
    user_id = message.from_user.id
    state = referrals.get(user_id)
    if not state or not state.get("await_manual_screenshot"):
        return
    manual_task_id = state["manual_task_id"]

    try:
        req_msg_id = state.get("request_msg_id")
        if req_msg_id:
            await message.bot.delete_message(chat_id=user_id, message_id=req_msg_id)
    except Exception as e:
        print(f"Ошибка удаления сообщения: {e}")
    file_id = message.photo[-1].file_id
    from database import create_manual_submission, submit_manual_submission, get_manual_submission_by_id, get_manual_task













    sub_id = create_manual_submission(user_id, manual_task_id, file_id)
    # сразу переводим в pending и уведомляем админов
    submit_manual_submission(sub_id)
    sub = get_manual_submission_by_id(sub_id)
    mt = get_manual_task(manual_task_id)
    notif_text = (
        f"🆕 Новая ручная заявка #{sub_id}\n"
        f"Пользователь: @{sub.get('username') or sub['user_id']} (ID {sub['user_id']})\n"
        f"Задание: {mt.get('title') or sub.get('manual_task_id')}\n"
        f"Награда: {mt.get('stars') or 0} ⭐️\n"
        f"Создано: {sub.get('created_at')}"
    )
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"manual_submission_approve_{sub_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"manual_submission_reject_{sub_id}"),
        InlineKeyboardButton(text="Не подписался на всех спонсоров", callback_data=f"manual_submission_rejectd_{sub_id}"),
        InlineKeyboardButton(text="Был уже зарегистрирован в боте", callback_data=f"manual_submission_rejectnot_{sub_id}")],

    ])
    bot = message.bot
    for admin in ADMIN_ID:
        try:
            await bot.send_photo(admin, file_id, caption=notif_text, reply_markup=admin_kb)
        except Exception as e:
            print(f"Ошибка уведомления админа {admin}: {e}")
    kb_back = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➡️ Вернуться к ручным заданиям", callback_data="manual_tasks_list")]
    ])
    await message.answer("⌛ Скриншот получен и отправлен на проверку администраторам. Ожидайте ответа.", reply_markup=kb_back)
    referrals.pop(user_id, None)


@router.callback_query(lambda c: c.data and c.data.startswith("submit_manual_"))
async def submit_manual_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    try:
        sub_id = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return
    from database import get_manual_submission_by_id, submit_manual_submission
    sub = get_manual_submission_by_id(sub_id)
    if not sub:
        await callback.answer("Заявка не найдена.")
        return
    submit_manual_submission(sub_id)
    notif_text = (
        f"🆕 Новая ручная заявка #{sub_id}\n"
        f"Пользователь: @{sub.get('username') or sub['user_id']} (ID {sub['user_id']})\n"
        f"Задание ID: {sub.get('manual_task_id')}\n"
        f"Награда: {sub.get('stars')} ⭐️\n"
        f"Создано: {sub.get('created_at')}"
    )
    s = get_manual_submission_by_id(sub_id)
    file_id = s['file_id']
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"manual_submission_approve_{sub_id}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"manual_submission_reject_{sub_id}")],
    ])
    from aiogram import Bot
    bot = callback.bot
    for admin in ADMIN_ID:
        try:
            await bot.send_photo(admin, file_id, caption=notif_text, _markup=admin_kb)
        except Exception as e:
            print(f"Ошибка уведомления админа {admin}: {e}")
    await callback.message.answer("✅ Ваша заявка отправлена на проверку. Ожидайте ответа администратора.")
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("manual_submission_approve_"))
async def admin_manual_submission_approve_cb(callback: types.CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return

    sub_id = int(callback.data.split("_")[-1])
    from database import (
        get_manual_submission_by_id,
        update_manual_submission_status,
        update_stars,
        increment_manual_task_use  # 🔥 добавляем импорт
    )

    sub = get_manual_submission_by_id(sub_id)
    if not sub or sub['status'] == 'approved':
        await callback.answer("Заявка не найдена или уже обработана.")
        return

    update_manual_submission_status(sub_id, "approved")
    uid = sub['user_id']
    stars = float(sub.get('stars') or 0)

    # начисляем звёзды
    update_stars(uid, stars, reason=f"Ручное задание #{sub['manual_task_id']} одобрено")

    # 🔥 увеличиваем счётчик выполнений задания
    increment_manual_task_use(sub['manual_task_id'])

    try:
        await bot.send_message(uid, f"✅ Ваша заявка #{sub_id} одобрена. Вы получили {stars} ⭐️")
    except Exception as e:
        print(f"Ошибка уведомления пользователя: {e}")

    await callback.answer("Заявка одобрена.")
    try:
        await callback.message.edit_caption(callback.message.caption + "\n\n✅ Одобрено")
    except:
        pass


@router.callback_query(lambda c: c.data and c.data.startswith("manual_submission_rejectd_"))
async def admin_manual_submission_rejectd_cb(callback: types.CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return
    sub_id = int(callback.data.split("_")[-1])
    from database import get_manual_submission_by_id, update_manual_submission_status
    sub = get_manual_submission_by_id(sub_id)
    if not sub or sub['status'] in ('rejected','approved'):
        await callback.answer("Заявка не найдена или уже обработана.")
        return
    update_manual_submission_status(sub_id, "rejected")
    uid = sub['user_id']
    try:
        await bot.send_message(uid, f"❌ Ваша заявка #{sub_id} отклонена. Причина: Вы не подписаны на всех спонсоров в канале илиже не выполнили задания в боте(смотрите описание задания)")
    except Exception as e:
        print(f"Ошибка уведомления пользователя: {e}")
    await callback.answer("Заявка отклонена.")
    try:
        await callback.message.edit_caption(callback.message.caption + "\\n\\n❌ Отклонено")
    except:
        pass

@router.callback_query(lambda c: c.data and c.data.startswith("manual_submission_rejectnot_"))
async def admin_manual_submission_rejectnot_cb(callback: types.CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return
    sub_id = int(callback.data.split("_")[-1])
    from database import get_manual_submission_by_id, update_manual_submission_status
    sub = get_manual_submission_by_id(sub_id)
    if not sub or sub['status'] in ('rejected','approved'):
        await callback.answer("Заявка не найдена или уже обработана.")
        return
    update_manual_submission_status(sub_id, "rejected")
    uid = sub['user_id']
    try:
        await bot.send_message(uid, f"❌ Ваша заявка #{sub_id} отклонена. Причина: Вы были уже зарегистрированы в этом боте.")
    except Exception as e:
        print(f"Ошибка уведомления пользователя: {e}")
    await callback.answer("Заявка отклонена.")
    try:
        await callback.message.edit_caption(callback.message.caption + "\\n\\n❌ Отклонено")
    except:
        pass

@router.callback_query(lambda c: c.data and c.data.startswith("manual_submission_reject_"))
async def admin_manual_submission_reject_cb(callback: types.CallbackQuery, bot: Bot):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return
    sub_id = int(callback.data.split("_")[-1])
    from database import get_manual_submission_by_id, update_manual_submission_status
    sub = get_manual_submission_by_id(sub_id)
    if not sub or sub['status'] in ('rejected','approved'):
        await callback.answer("Заявка не найдена или уже обработана.")
        return
    update_manual_submission_status(sub_id, "rejected")
    uid = sub['user_id']
    try:
        await bot.send_message(uid, f"❌ Ваша заявка #{sub_id} отклонена. Попробуйте загрузить другой скриншот!")
    except Exception as e:
        print(f"Ошибка уведомления пользователя: {e}")
    await callback.answer("Заявка отклонена.")
    try:
        await callback.message.edit_caption(callback.message.caption + "\\n\\n❌ Отклонено")
    except:
        pass




@router.callback_query(F.data == "admin_manual_submissions")
async def admin_manual_submissions_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.message.answer("🔒 Сначала войдите в админ-панель.")
        await callback.answer()
        return
    from database import get_manual_submissions
    pending = get_manual_submissions(status="pending")
    if not pending:
        await callback.message.edit_text("📥 Нет ручных заявок на проверку.", reply_markup=admin_main_kb)
        await callback.answer()
        return
    text_lines = ["📥 Ручные заявки (pending):"]
    kb = InlineKeyboardBuilder()
    for p in pending:
        sid = p["id"]
        uid = p["user_id"]
        title = p.get("title") or f'Задание {p.get("manual_task_id")}'
        stars = p.get("stars") or 0
        text_lines.append(f"#{sid} — @{p.get('username') or uid} — {title} — {stars} ⭐️")
        kb.button(text=f"Открыть #{sid}", callback_data=f"admin_manual_submission_{sid}")
    kb.button(text="⬅️ Назад в меню", callback_data="back_to_menu")
    await safe_edit_text(callback, "\n".join(text_lines), kb.as_markup())
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("admin_manual_submission_"))
async def admin_manual_submission_view_cb(callback: types.CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id not in admin_sessions:
        await callback.answer("🔒 Сначала войдите в админ-панель.")
        return
    try:
        sid = int(callback.data.split("_")[-1])
    except:
        await callback.answer()
        return
    from database import get_manual_submission_by_id, get_manual_task
    s = get_manual_submission_by_id(sid)
    if not s:
        await callback.answer("Заявка не найдена.")
        return
    mt = get_manual_task(s.get("manual_task_id"))
    uid = s.get("user_id")
    username = s.get("username") or f"User{uid}"
    text = (
        f"📥 Заявка #{sid}\n"
        f"Пользователь: @{username} (ID {uid})\n"
        f"Задание: {mt.get('title') if mt else s.get('manual_task_id')}\n"
        f"Награда: {mt.get('stars') if mt else s.get('stars') or 0} ⭐️\n"
        f"Статус: {s.get('status')}\n"
        f"Создана: {s.get('created_at')}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Одобрить", callback_data=f"manual_submission_approve_{sid}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"manual_submission_reject_{sid}")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="admin_manual_submissions")],
        [InlineKeyboardButton(text="⬅️ Назад в меню", callback_data="back_to_menu")]
    ])
    # Try to send photo as well
    try:
        await callback.message.bot.send_photo(admin_id, s.get("file_id"), caption=text, reply_markup=kb)
        try:
            await callback.message.delete()
        except:
            pass
    except Exception:
        await safe_edit_text(callback, text, kb)
    await callback.answer()

@router.callback_query(F.data == "roulette_menu")
async def show_roulette_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    if not user:
        await callback.message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        await callback.answer()
        return
    data = await flyer_check_subscription(user_id, callback.message)
    kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
        ]
    )
    if not data.get("skip"):
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        await callback.answer()  # без текста → не будет алерта
        return

    info = get_user_info(user)
    await callback.message.answer(
        f"<b>🎰 Добро пожаловать в рулетку! Выберите ставку 👇</b>\n\n"
        f"💰 Ваш баланс: {info['stars']:.2f} ⭐",
        reply_markup=roulette_keyboard(),
        parse_mode="HTML"
    )

# Кнопки ставок
def roulette_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="0.5 ⭐", callback_data="roulette_0.5"),
            InlineKeyboardButton(text="1 ⭐", callback_data="roulette_1"),
            InlineKeyboardButton(text="2 ⭐", callback_data="roulette_2"),
        ],
        [
            InlineKeyboardButton(text="3 ⭐", callback_data="roulette_5"),
            InlineKeyboardButton(text="5 ⭐", callback_data="roulette_5"),
            InlineKeyboardButton(text="10 ⭐", callback_data="roulette_10"),
        ],
        [
            InlineKeyboardButton(text="50 ⭐", callback_data="roulette_50"),
            InlineKeyboardButton(text="100 ⭐", callback_data="roulette_100"),
            InlineKeyboardButton(text="500 ⭐", callback_data="roulette_500"),
        ],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="back_to_menu")]
    ])
    return kb


@router.callback_query(lambda c: c.data.startswith("roulette_"))
async def roulette_cb(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    bet = float(callback.data.split("_")[1])
    data = await flyer_check_subscription(user_id, callback.message)
    kb = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
        ]
    )
    if not data.get("skip"):
        await callback.message.answer(
            await callback.answer(data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"), reply_markup=kb)
        )
        await callback.answer()
        return

    with get_conn() as conn:
        cur = conn.cursor()
        # Получаем баланс
        cur.execute("SELECT stars FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            await callback.answer("❌ У вас нет аккаунта!", show_alert=True)
            return

        balance = row["stars"]

        if balance < bet:
            await callback.answer("❌ Недостаточно ⭐ для этой ставки!", show_alert=True)
            return

        # Списываем ставку
        cur.execute("UPDATE users SET stars = stars - ? WHERE id = ?", (bet, user_id))

        # Рулетка: шанс 20% на победу
        if random.random() < 0.2:
            win = bet * 2
            cur.execute("UPDATE users SET stars = stars + ? WHERE id = ?", (win, user_id))
            conn.commit()
            await callback.answer(
                f"🎉 Удача! Ставка {bet} ⭐ сыграла!\nВы выиграли {win} ⭐",
                show_alert=True
            )
        else:
            conn.commit()
            await callback.answer(
                f"😔 Неудача! Ставка {bet} ⭐ не сыграла.\nНе расстраивайтесь, в следующий раз повезёт 🙏",
                show_alert=True
            )

FRUITS = ["🍎", "🍌", "🍇", "🍊", "🍉", "🍒"]

captcha_answers = {}  # user_id -> fruit


@router.callback_query(F.data == "clicker")
async def clicker_start(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)

    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, callback.message)
    if not data.get("skip"):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        await callback.answer()
        return

    # 🔹 Проверка регистрации
    if not user:
        await callback.message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        await callback.answer()
        return

    # 🔹 Проверка кулдауна
    last_click = get_last_click(user_id)
    if last_click:
        last_dt = datetime.fromisoformat(last_click)
        if datetime.utcnow() - last_dt < timedelta(minutes=10):
            await callback.answer("⏳ Можно использовать кликер раз в 10 минут!", show_alert=True)
            return

    # выбираем фрукт
    correct = random.choice(FRUITS)

    # кнопки по 3 в ряд
    shuffled = random.sample(FRUITS, len(FRUITS))
    row_size = 3
    buttons = []
    for i in range(0, len(shuffled), row_size):
        row = [
            InlineKeyboardButton(text=fruit, callback_data=f"clicker_ans_{fruit}")
            for fruit in shuffled[i:i+row_size]
        ]
        buttons.append(row)

    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

    await callback.message.answer(
        f"🤖 ПРОВЕРКА НА РОБОТА\n\n ✅ Чтобы получить награду:\nнажми на кнопку, где изображено «{correct}»",
        reply_markup=kb
    )

    captcha_answers[user_id] = correct
    await callback.answer()


@router.callback_query(lambda c: c.data.startswith("clicker_ans_"))
async def clicker_answer(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)

    # 🔹 Проверка подписки
    data = await flyer_check_subscription(user_id, callback.message)
    if not data.get("skip"):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Я подписался", callback_data="fp_check")]
            ]
        )
        await callback.message.answer(
            data.get("info", "Для продолжения подпишитесь на обязательные каналы. 👆"),
            reply_markup=kb
        )
        await callback.answer()
        return

    # 🔹 Проверка регистрации
    if not user:
        await callback.message.answer("⚠️ Вы не зарегистрированы. Введите /start")
        await callback.answer()
        return

    choice = callback.data.split("_")[-1]
    correct = captcha_answers.get(user_id)

    if not correct:
        await callback.answer("❌ Сессия истекла, попробуйте снова.", show_alert=True)
        return

    if choice != correct:
        await callback.answer("❌ Неверно, попробуйте снова через 10 минут.", show_alert=True)
        return

    # начисляем награду
    vip = get_vip_level(user_id)
    reward = 0.1
    if vip == 2:
        reward = 0.2
    elif vip == 3:
        reward = 0.4

    update_stars(user_id, reward, reason="Clicker reward")
    update_last_click(user_id)

    # удаляем сообщение с капчей
    try:
        await callback.message.delete()
    except:
        pass

    # показываем награду в алерте
    await callback.answer(f"✅ Ты получил(а): {reward} ⭐️", show_alert=True)

    # отправляем главное меню
    await callback.message.answer(
                "📋 <b>Главное меню</b>\n\n"
                "⭐️ <i>Зарабатывай звёзды, выполняя задания и приглашая друзей!</i> 👥\n\n"
                "⚠️ <b>Важно:</b>\n"
                "Честная игра = честные награды 💎\n"
                "За накрутку рефералов — ❌ <u>бан без выплат</u>.",
        reply_markup=main_menu_kb,
        parse_mode="HTML"
    )

clicker_top_kb = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Топ кликера сегодня", callback_data="top_clicker_today")],
    [InlineKeyboardButton(text="Топ кликера за всё время", callback_data="top_clicker_all")],
    [InlineKeyboardButton(text="⬅️", callback_data="back_to_menu")]
])

@router.callback_query(F.data == "clicker_top")
async def clicker_top_menu(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📊 Выберите категорию топа по кликеру:",
        reply_markup=clicker_top_kb
    )
    await callback.answer()

@router.callback_query(F.data.in_(["top_clicker_today", "top_clicker_all"]))
async def clicker_top_show(callback: types.CallbackQuery):
    today_only = callback.data == "top_clicker_today"
    title = "🥇 Топ-10 по кликеру сегодня" if today_only else "🥇 Топ-10 по кликеру за всё время"
    top = get_top_clicker_users(today_only=today_only)

    if not top:
        text = f"{title}\n\nНет данных."
    else:
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (name, value) in enumerate(top):
            emoji = medals[i] if i < 3 else f"{i+1}."
            lines.append(f"{emoji} {name} — {value} кликов")
        text = title + "\n\n" + "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=statistics_back_kb)
    await callback.answer()

@router.callback_query(F.data == "admin_vip_users")
async def admin_vip_users(callback: types.CallbackQuery):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, username, full_name, vip_level FROM users WHERE vip_level > 0")
    users = cur.fetchall()

    if not users:
        await callback.message.answer("❌ Нет пользователей с VIP-подписками")
        await callback.answer()
        return

    lines = []
    for u in users:
        name = u["full_name"] or (f"@{u['username']}" if u["username"] else str(u["id"]))
        vip_text = {1: "I степени", 2: "II степени", 3: "III степени"}.get(u["vip_level"], f"{u['vip_level']}-го уровня")
        lines.append(f"👤 {name} — VIP {vip_text}")

    await callback.message.answer("📋 Список пользователей с подписками:\n\n" + "\n".join(lines))
    await callback.answer()