from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.utils.keyboard import InlineKeyboardBuilder
import asyncio

bot = Bot("7905138160:AAFYrDc1q5egzF0vJwa3wrfRxgQ6kd_VHuY")
dp = Dispatcher()

@dp.message(CommandStart())
async def start(message: types.Message):
    kb = InlineKeyboardBuilder()
    kb.button(
        text="🚀 Открыть мини-апп",
        web_app=types.WebAppInfo(url="https://ddddd-production.up.railway.app")
    )
    await message.answer("Добро пожаловать! Открой мини-апп:", reply_markup=kb.as_markup())

asyncio.run(dp.start_polling(bot))
