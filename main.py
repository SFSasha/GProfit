from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from handlers import router
import asyncio
from database import get_conn
import logging 
from handlers import auto_check_bio_links
from handlers import auto_check_usernames
from handlers import daily_reward_task, daily_promo_task 

# Настраиваем логирование: вывод в консоль, уровень INFO
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Получаем логгер для handlers
log = logging.getLogger(__name__)


async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
  
    # Используем log.info вместо print для важных сообщений
    asyncio.create_task(auto_check_bio_links(bot))
    asyncio.create_task(auto_check_usernames(bot))

    asyncio.create_task(daily_reward_task(bot))
    asyncio.create_task(daily_promo_task(bot))
  
    log.info("Starting bot...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    conn = get_conn()
    asyncio.run(main())





