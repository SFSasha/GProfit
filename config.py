# config.py

import os
from typing import List

# 1. Читаем BOT_TOKEN
# Если переменная не установлена (только для локальной отладки), используем заглушку
BOT_TOKEN = os.getenv("BOT_TOKEN") 
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is not set.")

# 2. Читаем ADMIN_ID и преобразуем в список целых чисел
# Примечание: В Railway ADMIN_ID должен быть записан как строка, например: 1500618394,123456789
ADMIN_ID_STR = os.getenv("ADMIN_ID", "")
if ADMIN_ID_STR:
    # Разделяем строку по запятым и преобразуем в int
    try:
        ADMIN_ID: List[int] = [int(i.strip()) for i in ADMIN_ID_STR.split(',') if i.strip()]
    except ValueError:
        print("Warning: ADMIN_ID environment variable contains non-integer values.")
        ADMIN_ID: List[int] = []
else:
    ADMIN_ID: List[int] = []