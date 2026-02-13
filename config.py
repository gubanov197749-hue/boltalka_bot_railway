import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "8326101875:AAFc5-pabDK9PXpEg_Fb-Nuarq0DqvFeIko")
MEGANOVA_API_KEY = os.getenv("MEGANOVA_API_KEY", "sk-JGE1ns1NfZxW3VVgTThgfw")
RAILWAY_STATIC_URL = os.getenv("RAILWAY_STATIC_URL", "localhost")
WEBHOOK_URL = f"https://{RAILWAY_STATIC_URL}/webhook"
