import os
import logging
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
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


# --- Настройка бота ---
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
    
    # Запускаем бота в фоновом режиме
    # Это позволяет uvicorn серверу и боту работать одновременно
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
    # Создаем задачу для запуска бота в фоне
    asyncio.create_task(setup_bot())

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Отдает главную HTML-страницу веб-приложения."""
    return templates.TemplateResponse("index.html", {"request": request})

# --- Основная точка входа для Railway ---
if __name__ == "__main__":
    # Railway предоставит переменную PORT
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
