from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import router
import asyncio
from database import get_conn

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    conn = get_conn()  # get_conn уже вызывает init_db внутри себя
    asyncio.run(main())