import os

# Telegram Bot Token — ТОЛЬКО из переменных окружения!
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не найден в переменных окружения!")

# MegaNova API Key — ТОЛЬКО из переменных окружения!
MEGANOVA_API_KEY = os.getenv("MEGANOVA_API_KEY")
if not MEGANOVA_API_KEY:
    raise ValueError("❌ MEGANOVA_API_KEY не найден в переменных окружения!")

# Railway URL (опционально)
RAILWAY_STATIC_URL = os.getenv("RAILWAY_STATIC_URL", "localhost")
WEBHOOK_URL = f"https://{RAILWAY_STATIC_URL}/webhook"
