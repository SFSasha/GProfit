from aiogram import Bot, Dispatcher, types, F
from config import BOT_TOKEN
from handlers import router
import asyncio
from database import get_conn
import logging 
from handlers import auto_check_bio_links, auto_check_usernames
import os

# Настраиваем логирование: вывод в консоль, уровень INFOd
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Получаем логгер для handlers
log = logging.getLogger(__name__)
DB_PATH = os.getenv("DB_PATH", "/data/bot.db")  # путь к базе на Railway

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
  
    # Запускаем фоновые задачи
    asyncio.create_task(auto_check_bio_links(bot))
    asyncio.create_task(auto_check_usernames(bot))

    log.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    conn = get_conn()  # get_conn уже вызывает init_db внутри себя
    asyncio.run(main())




